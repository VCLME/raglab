"""Download EU acts from CELLAR, the Publications Office repository behind
EUR-Lex (open, no account; reuse under Commission Decision 2011/833/EU).

`http://publications.europa.eu/resource/celex/<CELEX>` content-negotiates:
`Accept: application/xhtml+xml` with `Accept-Language: fra` redirects to the
French XHTML manifestation of the act (Official Journal text, or the
consolidated text for a "0..." CELEX). The EUR-Lex HTML pages themselves sit
behind a bot challenge and are not used.

Requests are sequential, spaced by `delay` seconds, retried with backoff on
429 / 5xx, and cached on disk: a second fetch reads the cache and makes no
request at all.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from raglab.eurlex.acts import CELLAR_LANGUAGES
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

CELLAR_RESOURCE = "http://publications.europa.eu/resource/celex/{celex}"
SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
USER_AGENT = "raglab-corpus/1.0 (+https://github.com/VCLME/raglab; research corpus, sequential requests)"


@dataclass(slots=True, frozen=True)
class Download:
    celex: str
    language: str
    path: Path
    url: str | None
    sha256: str
    cached: bool


def raw_path(raw_dir: Path, celex: str, language: str) -> Path:
    return raw_dir / f"{celex}.{language}.xhtml"


class CellarClient:
    def __init__(self, raw_dir: Path, *, delay: float = 1.0, retries: int = 4, timeout: float = 60.0) -> None:
        self.raw_dir = raw_dir
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def _wait(self) -> None:
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def fetch(self, celex: str, language: str, *, missing_ok: bool = False) -> Download | None:
        """The XHTML of `celex` in `language` ("fr", "en", "pt"), from the
        cache when present; None for a 404 when `missing_ok`."""
        path = raw_path(self.raw_dir, celex, language)
        if path.exists():
            data = path.read_bytes()
            return Download(celex, language, path, None, hashlib.sha256(data).hexdigest(), cached=True)
        headers = {"Accept": "application/xhtml+xml", "Accept-Language": CELLAR_LANGUAGES[language]}
        url = CELLAR_RESOURCE.format(celex=celex)
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                response = self._session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as exc:
                if attempt == self.retries:
                    raise
                log_event(LOGGER, logging.WARNING, "eurlex.fetch.retry", celex=celex, language=language, error=str(exc))
                time.sleep(2**attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "eurlex.fetch.retry",
                    celex=celex,
                    language=language,
                    status=response.status_code,
                )
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code == 404 and missing_ok:
                log_event(LOGGER, logging.WARNING, "eurlex.fetch.missing", celex=celex, language=language)
                return None
            response.raise_for_status()
            if "xhtml" not in response.headers.get("Content-Type", "") or not response.content.strip():
                raise RuntimeError(f"CELLAR n'a pas renvoye de XHTML pour {celex} ({language}): {response.url}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            log_event(
                LOGGER,
                logging.INFO,
                "eurlex.fetch.downloaded",
                celex=celex,
                language=language,
                bytes=len(response.content),
                url=response.url,
            )
            return Download(
                celex, language, path, response.url, hashlib.sha256(response.content).hexdigest(), cached=False
            )
        raise RuntimeError(f"CELLAR injoignable pour {celex} ({language})")


def consolidations_query(celex: str) -> str:
    """SPARQL listing the consolidated versions CELLAR holds for an act."""
    return (
        "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
        "SELECT DISTINCT ?celex WHERE { ?w cdm:resource_legal_id_celex ?celex . "
        f'FILTER(STRSTARTS(STR(?celex), "0{celex[1:]}-")) }} ORDER BY ?celex'
    )


def list_consolidations(celex: str, *, timeout: float = 60.0) -> list[str]:
    response = requests.post(
        SPARQL_ENDPOINT,
        data={"query": consolidations_query(celex)},
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    rows = response.json()["results"]["bindings"]
    return sorted(row["celex"]["value"] for row in rows)
