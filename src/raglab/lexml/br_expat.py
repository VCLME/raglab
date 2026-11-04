"""The "Brazil expat" corpus: the 19 federal texts behind 30 real questions.

A French national settling in Brazil with a company taxed on presumed profit
(lucro presumido) runs into immigration law, company tax, social security and
personal tax. The owner's business assistant compiled 30 questions they
actually faced; this module collects the texts that answer them:

- laws, complementary laws, decrees and the constitutional amendment from
  planalto.gov.br, in their compiled version (amendments applied in place,
  revoked wording struck through and dropped, "Redação dada pela" and
  "(Revogado)" markers kept for the versions brick);
- the two Receita Federal normative instructions from the JSON API behind
  normas.receita.fazenda.gov.br, in their current ("vigente") view: segments
  the source marks as superseded (`omitir`) are dropped.

One `.txt` + `.json` sidecar per text under `corpus/`, the downloaded pages
under `raw/` (a later run reads the cache and makes no request), and a
`manifest.json` with the checksum of every text. The sidecar keeps the fields
of the LexML full-text corpus (`number`, `year`, `urn`...), so the citation
resolver finds "Lei 9.249/1995" the same way.

Brazilian legislation is in the public domain (Lei 9.610/1998, art. 8º, IV).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import requests

from raglab.config import Settings, get_settings
from raglab.ingestion.readers import normalize_text
from raglab.lexml.fulltext import PLANALTO_BASE_URL, REQUEST_TIMEOUT_SECONDS, USER_AGENT, _decode, extract_planalto_text
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

RECEITA_API_URL = "https://normasinternet2.receita.fazenda.gov.br/api/consulta-externa/ato/{id}/visao/vigente"
RECEITA_PAGE_URL = "https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto={id}&visao=compilado"

_HEADINGS = {
    "lei": r"LEI\s+N",
    "lc": r"LEI\s+COMPLEMENTAR\s+N",
    "decreto": r"DECRETO\s+N",
    "ec": r"EMENDA\s+CONSTITUCIONAL\s+N",
}
_URN_KINDS = {
    "lei": "lei",
    "lc": "lei.complementar",
    "decreto": "decreto",
    "ec": "emenda.constitucional",
    "in": "instrucao.normativa",
}


@dataclass(frozen=True, slots=True)
class Norm:
    key: str
    kind: str  # lei | lc | decreto | ec | in
    number: str  # digits only, as the citation resolver reads it
    year: int
    signed_on: str  # ISO date
    title: str
    theme: str  # immigration | company_tax | social_security | personal_tax
    source: str  # planalto | receita
    path: str = ""  # Planalto page, relative to ccivil_03
    receita_id: int | None = None
    authority: str = "federal"
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def urn(self) -> str:
        authority = "federal" if self.kind != "in" else "secretaria.receita.federal"
        return f"urn:lex:br:{authority}:{_URN_KINDS[self.kind]}:{self.signed_on};{self.number}"

    @property
    def stem(self) -> str:
        return self.key

    @property
    def url(self) -> str:
        if self.source == "receita":
            return RECEITA_PAGE_URL.format(id=self.receita_id)
        return f"{PLANALTO_BASE_URL}/{self.path}"


# Compiled pages: Planalto updates them in place when a law is amended, so a
# later collection may differ (the manifest says which file).
NORMS: tuple[Norm, ...] = (
    Norm(
        "lei_13445_2017",
        "lei",
        "13445",
        2017,
        "2017-05-24",
        "Lei nº 13.445, de 24 de maio de 2017 (Lei de Migração)",
        "immigration",
        "planalto",
        "_ato2015-2018/2017/lei/l13445.htm",
    ),
    Norm(
        "decreto_9199_2017",
        "decreto",
        "9199",
        2017,
        "2017-11-20",
        "Decreto nº 9.199, de 20 de novembro de 2017 (regulamenta a Lei de Migração)",
        "immigration",
        "planalto",
        "_ato2015-2018/2017/decreto/d9199.htm",
    ),
    Norm(
        "lei_7115_1983",
        "lei",
        "7115",
        1983,
        "1983-08-29",
        "Lei nº 7.115, de 29 de agosto de 1983 (prova documental por declaração)",
        "immigration",
        "planalto",
        "leis/l7115.htm",
    ),
    Norm(
        "lei_10406_2002",
        "lei",
        "10406",
        2002,
        "2002-01-10",
        "Lei nº 10.406, de 10 de janeiro de 2002 (Código Civil)",
        "immigration",
        "planalto",
        "leis/2002/l10406compilada.htm",
    ),
    Norm(
        "lei_9249_1995",
        "lei",
        "9249",
        1995,
        "1995-12-26",
        "Lei nº 9.249, de 26 de dezembro de 1995 (IRPJ e CSLL)",
        "company_tax",
        "planalto",
        "leis/l9249.htm",
    ),
    Norm(
        "lei_9430_1996",
        "lei",
        "9430",
        1996,
        "1996-12-27",
        "Lei nº 9.430, de 27 de dezembro de 1996 (legislação tributária federal)",
        "company_tax",
        "planalto",
        "leis/l9430.htm",
    ),
    Norm(
        "lei_10833_2003",
        "lei",
        "10833",
        2003,
        "2003-12-29",
        "Lei nº 10.833, de 29 de dezembro de 2003 (Cofins não cumulativa)",
        "company_tax",
        "planalto",
        "leis/2003/l10.833.htm",
    ),
    Norm(
        "lei_10637_2002",
        "lei",
        "10637",
        2002,
        "2002-12-30",
        "Lei nº 10.637, de 30 de dezembro de 2002 (PIS/Pasep não cumulativo)",
        "company_tax",
        "planalto",
        "leis/2002/l10637.htm",
    ),
    Norm(
        "lei_15270_2025",
        "lei",
        "15270",
        2025,
        "2025-11-26",
        "Lei nº 15.270, de 26 de novembro de 2025 (tributação mínima e dividendos)",
        "company_tax",
        "planalto",
        "_ato2023-2026/2025/lei/l15270.htm",
    ),
    Norm(
        "lc_116_2003",
        "lc",
        "116",
        2003,
        "2003-07-31",
        "Lei Complementar nº 116, de 31 de julho de 2003 (ISS)",
        "company_tax",
        "planalto",
        "leis/lcp/lcp116.htm",
    ),
    Norm(
        "lc_123_2006",
        "lc",
        "123",
        2006,
        "2006-12-14",
        "Lei Complementar nº 123, de 14 de dezembro de 2006 (Simples Nacional)",
        "company_tax",
        "planalto",
        "leis/lcp/lcp123.htm",
    ),
    Norm(
        "in_rfb_1700_2017",
        "in",
        "1700",
        2017,
        "2017-03-14",
        "Instrução Normativa RFB nº 1.700, de 14 de março de 2017 (IRPJ e CSLL)",
        "company_tax",
        "receita",
        receita_id=81268,
    ),
    Norm(
        "in_srf_208_2002",
        "in",
        "208",
        2002,
        "2002-09-27",
        "Instrução Normativa SRF nº 208, de 27 de setembro de 2002 (residência fiscal, não residentes)",
        "personal_tax",
        "receita",
        receita_id=15079,
    ),
    Norm(
        "lei_8212_1991",
        "lei",
        "8212",
        1991,
        "1991-07-24",
        "Lei nº 8.212, de 24 de julho de 1991 (custeio da Seguridade Social)",
        "social_security",
        "planalto",
        "leis/l8212cons.htm",
    ),
    Norm(
        "lei_10666_2003",
        "lei",
        "10666",
        2003,
        "2003-05-08",
        "Lei nº 10.666, de 8 de maio de 2003 (contribuinte individual)",
        "social_security",
        "planalto",
        "leis/2003/l10.666.htm",
    ),
    Norm(
        "ec_103_2019",
        "ec",
        "103",
        2019,
        "2019-11-12",
        "Emenda Constitucional nº 103, de 12 de novembro de 2019 (reforma da Previdência)",
        "social_security",
        "planalto",
        "constituicao/emendas/emc/emc103.htm",
    ),
    Norm(
        "decreto_8300_2014",
        "decreto",
        "8300",
        2014,
        "2014-08-29",
        "Decreto nº 8.300, de 29 de agosto de 2014 (acordo de previdência social Brasil-França)",
        "social_security",
        "planalto",
        "_ato2011-2014/2014/decreto/d8300.htm",
    ),
    Norm(
        "lei_14754_2023",
        "lei",
        "14754",
        2023,
        "2023-12-12",
        "Lei nº 14.754, de 12 de dezembro de 2023 (aplicações financeiras no exterior)",
        "personal_tax",
        "planalto",
        "_ato2023-2026/2023/lei/l14754.htm",
    ),
    Norm(
        "decreto_6306_2007",
        "decreto",
        "6306",
        2007,
        "2007-12-14",
        "Decreto nº 6.306, de 14 de dezembro de 2007 (Regulamento do IOF)",
        "personal_tax",
        "planalto",
        "_ato2007-2010/2007/decreto/d6306.htm",
    ),
)

_TAG_RE = re.compile(r"<[^>]+>")


def extract_receita_text(payload: dict[str, Any]) -> str:
    """Current text of a Receita Federal act, one segment per line.

    The `vigente` view lists every segment, old wording included; the ones
    the source marks `omitir` (superseded or revoked) are left out. The
    source wraps ordinals in `<strike>` for display ("Art. 1<strike>º</strike>"),
    so tags are stripped, not their content.
    """
    lines = [str(payload.get("epigrafeCompleta") or "").strip()]
    segments = [*payload.get("ementas", []), *payload.get("outrosSegmentos", [])]
    for segment in sorted(segments, key=lambda row: row.get("ordemSegmentoAto") or 0):
        if segment.get("omitir") or segment.get("tachado"):
            continue
        text = unescape(_TAG_RE.sub("", str(segment.get("textoIntegra") or ""))).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            lines.append(text)
    return normalize_text("\n".join(line for line in lines if line))


class BrExpatCollector:
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

    def _download(self, url: str, raw_path: Path) -> bytes:
        if raw_path.exists():
            return raw_path.read_bytes()
        self._sleep(self.delay_seconds)
        response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        raw_path.write_bytes(response.content)
        return response.content

    def text_of(self, norm: Norm, raw_dir: Path) -> str:
        if norm.source == "receita":
            content = self._download(RECEITA_API_URL.format(id=norm.receita_id), raw_dir / f"{norm.key}.json")
            return extract_receita_text(json.loads(content.decode("utf-8")))
        content = self._download(norm.url, raw_dir / f"{norm.key}.htm")
        return extract_planalto_text(_decode(content), heading=re.compile(rf"^{_HEADINGS[norm.kind]}", re.IGNORECASE))

    def collect(
        self,
        *,
        output_dir: Path | None = None,
        keys: set[str] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Fetch every text (or the `keys` given) and write the corpus.

        A text that cannot be fetched is reported in `missing` and the
        collection goes on with the others.
        """
        base_dir = (output_dir or self.settings.br_expat_dir).resolve()
        corpus_dir = base_dir / "corpus"
        raw_dir = base_dir / "raw"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
        norms = [norm for norm in NORMS if keys is None or norm.key in keys]
        kept: list[dict[str, Any]] = []
        missing: list[dict[str, str]] = []
        for done, norm in enumerate(norms, start=1):
            try:
                text = self.text_of(norm, raw_dir)
            except (requests.RequestException, ValueError) as exc:
                log_event(LOGGER, logging.WARNING, "br_expat.fetch_failed", key=norm.key, url=norm.url, error=str(exc))
                missing.append({"key": norm.key, "url": norm.url, "error": str(exc)})
                if progress:
                    progress(done, len(norms))
                continue
            text_path = corpus_dir / f"{norm.stem}.txt"
            text_path.write_text(text, encoding="utf-8")
            text_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "key": norm.key,
                        "kind": norm.kind,
                        "number": norm.number,
                        "year": norm.year,
                        "signed_on": norm.signed_on,
                        "title": norm.title,
                        "theme": norm.theme,
                        "urn": norm.urn,
                        "source": norm.source,
                        "source_url": norm.url,
                        "language": "pt",
                        "tags": ["br_expat", norm.kind, norm.theme],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            kept.append(
                {
                    "file_name": text_path.name,
                    "urn": norm.urn,
                    "chars": len(text),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "source_url": norm.url,
                }
            )
            if progress:
                progress(done, len(norms))

        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "documents": sorted(kept, key=lambda row: row["file_name"]),
            "missing": missing,
        }
        (base_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        log_event(
            LOGGER,
            logging.INFO,
            "br_expat.completed",
            output_dir=base_dir,
            documents=len(kept),
            missing=len(missing),
            total_chars=sum(row["chars"] for row in kept),
        )
        return {
            "output_dir": str(base_dir),
            "corpus_dir": str(corpus_dir),
            "documents": len(kept),
            "missing": missing,
        }
