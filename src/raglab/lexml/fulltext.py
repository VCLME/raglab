"""Full-text collection of Brazilian federal laws for the LexML benchmark.

The historical LexML collector (`getDataFromLexML`) only saves search-result
records: a title and an ementa of a few hundred characters. That is enough to
smoke-test ingestion but not to benchmark retrieval: there are no articles,
no cross references, nothing to search *inside*. This module builds a
full-text corpus instead:

1. list the federal laws signed in a range of years through the Senado open
   data API (`legis.senado.leg.br/dadosabertos`, JSON, no authentication);
2. draw a deterministic sample per year (fixed seed);
3. fetch the consolidated text from planalto.gov.br, drop revoked passages
   (struck-through text) and keep the rest as plain text;
4. write one `.txt` + `.json` sidecar per law under `corpus/`, plus a
   `manifest.json` with
   the checksum of every text, so a later run can tell whether it is
   benchmarking the same corpus.

Brazilian legislation is in the public domain (Lei 9.610/1998, art. 8º, IV).
The LexML search engine itself sits behind a bot challenge, so it is not
used here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from raglab.config import Settings, get_settings
from raglab.ingestion.readers import normalize_text
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

SENADO_LIST_URL = "https://legis.senado.leg.br/dadosabertos/legislacao/lista"
PLANALTO_BASE_URL = "https://www.planalto.gov.br/ccivil_03"
USER_AGENT = "Mozilla/5.0 (compatible; raglab-benchmark/0.1; +https://github.com/VCLME/raglab)"
REQUEST_TIMEOUT_SECONDS = (20, 60)

_ATO_PERIODS = (
    (2004, 2006),
    (2007, 2010),
    (2011, 2014),
    (2015, 2018),
    (2019, 2022),
    (2023, 2026),
)
_BLOCK_TAGS = {"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote"}
_HEADING_RE = re.compile(r"^LEI\s+N", re.IGNORECASE)
_SKIPPED_TAGS = {"script", "style", "title", "strike", "s", "del"}


@dataclass(slots=True)
class FederalLaw:
    number: str
    year: int
    signed_on: str  # ISO date
    title: str
    ementa: str

    @property
    def urn(self) -> str:
        return f"urn:lex:br:federal:lei:{self.signed_on};{self.number}"

    @property
    def stem(self) -> str:
        return f"lei_{self.number}_{self.year}"


def planalto_candidate_urls(number: str, year: int) -> list[str]:
    """Planalto has used several file layouts over time; try them in order."""
    dotted = f"{int(number):,}".replace(",", ".")
    if year >= 2004:
        for start, end in _ATO_PERIODS:
            if start <= year <= end:
                return [f"{PLANALTO_BASE_URL}/_ato{start}-{end}/{year}/lei/l{number}.htm"]
        return []
    if year >= 2002:
        return [
            f"{PLANALTO_BASE_URL}/leis/{year}/l{number}.htm",
            f"{PLANALTO_BASE_URL}/leis/{year}/l{dotted}.htm",
        ]
    return [
        f"{PLANALTO_BASE_URL}/leis/l{number}.htm",
        f"{PLANALTO_BASE_URL}/leis/l{number}compilado.htm",
        f"{PLANALTO_BASE_URL}/leis/l{number}orig.htm",
    ]


class _PlanaltoTextParser(HTMLParser):
    """Collect visible text, skipping revoked (struck-through) passages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        # Only skipping elements are tracked: Planalto pages leave most <p>
        # and <font> tags unclosed, so a full element stack would drift.
        self._skipping: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        style = " ".join((value or "") for name, value in attrs if name == "style").lower()
        if tag in _SKIPPED_TAGS or "line-through" in style:
            self._skipping.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag in self._skipping:
            # Close up to the matching opener, tolerating unclosed children.
            while self._skipping and self._skipping.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            # Source newlines are just HTML wrapping; only block tags break lines.
            self.parts.append(re.sub(r"\s+", " ", data))


def extract_planalto_text(html: str) -> str:
    """Turn a Planalto law page into plain text, one paragraph per line."""
    parser = _PlanaltoTextParser()
    parser.feed(html)
    parser.close()
    raw = unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
    lines = [line for line in lines if line]
    # Drop the masthead (Presidência / Casa Civil / links to regulations)
    # that precedes the law heading on every page.
    for index, line in enumerate(lines):
        if _HEADING_RE.match(line):
            lines = lines[index:]
            break
    # One paragraph per line, so the chunkers' sentence splitter sees
    # article boundaries.
    return normalize_text("\n".join(lines))


def _decode(content: bytes) -> str:
    # Planalto serves windows-1252 without declaring it in most pages.
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _parse_br_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()


class FullTextCollector:
    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
        *,
        delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.delay_seconds = delay_seconds
        self._sleep = sleep

    def list_laws(self, year: int) -> list[FederalLaw]:
        response = self.session.get(
            SENADO_LIST_URL,
            params={"tipo": "LEI", "ano": str(year)},
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        documents = response.json().get("ListaDocumento", {}).get("documentos", {}).get("documento", [])
        if isinstance(documents, dict):
            documents = [documents]
        laws: list[FederalLaw] = []
        for document in documents:
            number = str(document.get("numero") or "").strip()
            signed = str(document.get("dataassinatura") or "").strip()
            if not number.isdigit() or not signed:
                continue
            laws.append(
                FederalLaw(
                    number=number,
                    year=year,
                    signed_on=_parse_br_date(signed),
                    title=str(document.get("normaNome") or f"Lei nº {number}").strip(),
                    ementa=str(document.get("ementa") or "").strip(),
                )
            )
        return sorted(laws, key=lambda law: int(law.number))

    def fetch_text(self, law: FederalLaw) -> tuple[str, str] | None:
        """Return (text, source_url) or None when no Planalto page matches."""
        for url in planalto_candidate_urls(law.number, law.year):
            self._sleep(self.delay_seconds)
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            except requests.RequestException as exc:
                log_event(LOGGER, logging.WARNING, "lexml.fulltext.fetch_failed", url=url, error=str(exc))
                continue
            if response.status_code != 200:
                continue
            html = _decode(response.content)
            if "Ocorreu um erro" in html[:2000]:
                continue
            return extract_planalto_text(html), response.url
        return None

    def collect(
        self,
        *,
        output_dir: Path | None = None,
        years: Iterable[int],
        per_year: int,
        seed: int = 42,
        min_chars: int = 3000,
        max_chars: int = 150_000,
    ) -> dict[str, Any]:
        """Collect up to `per_year` laws per year and write the corpus.

        Laws are visited in a seeded random order and kept until `per_year`
        of them fall inside [min_chars, max_chars]: tiny honorific laws carry
        nothing to retrieve, and a handful of codes would otherwise dominate
        the corpus. Files already on disk are reused, so an interrupted run
        can be resumed.
        """
        base_dir = (output_dir or self.settings.lexml_fulltext_dir).resolve()
        target_dir = base_dir / "corpus"
        target_dir.mkdir(parents=True, exist_ok=True)
        rng = random.Random(seed)
        kept: list[dict[str, Any]] = []
        skipped = {"not_found": 0, "too_short": 0, "too_long": 0}

        for year in years:
            laws = self.list_laws(year)
            rng.shuffle(laws)
            kept_this_year = 0
            for law in laws:
                if kept_this_year >= per_year:
                    break
                text_path = target_dir / f"{law.stem}.txt"
                if text_path.exists():
                    sidecar = json.loads(text_path.with_suffix(".json").read_text(encoding="utf-8"))
                    text = text_path.read_text(encoding="utf-8")
                    source_url = sidecar.get("source_url", "")
                else:
                    fetched = self.fetch_text(law)
                    if fetched is None:
                        skipped["not_found"] += 1
                        continue
                    text, source_url = fetched
                    if len(text) < min_chars:
                        skipped["too_short"] += 1
                        continue
                    if len(text) > max_chars:
                        skipped["too_long"] += 1
                        continue
                    text_path.write_text(text, encoding="utf-8")
                    text_path.with_suffix(".json").write_text(
                        json.dumps(
                            {
                                **asdict(law),
                                "urn": law.urn,
                                "source": "planalto",
                                "source_url": source_url,
                                "language": "pt",
                                "tags": ["lexml", "lei_federal"],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                kept_this_year += 1
                kept.append(
                    {
                        "file_name": text_path.name,
                        "urn": law.urn,
                        "chars": len(text),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "source_url": source_url,
                    }
                )
            log_event(LOGGER, logging.INFO, "lexml.fulltext.year_done", year=year, kept=kept_this_year)

        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "seed": seed,
            "per_year": per_year,
            "min_chars": min_chars,
            "max_chars": max_chars,
            "documents": sorted(kept, key=lambda row: row["file_name"]),
            "skipped": skipped,
        }
        (base_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        log_event(
            LOGGER,
            logging.INFO,
            "lexml.fulltext.completed",
            output_dir=base_dir,
            documents=len(kept),
            total_chars=sum(row["chars"] for row in kept),
            skipped=skipped,
        )
        return {
            "output_dir": str(base_dir),
            "corpus_dir": str(target_dir),
            "documents": len(kept),
            "skipped": skipped,
        }
