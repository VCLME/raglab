from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from raglab.config import Settings, get_settings
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

LEXML_BASE_URL = "https://www.lexml.gov.br"
LEXML_SEARCH_PATH = "/busca/search"
LEXML_LEGISLATION_FILTER = "Legislação"
LEXML_PAGE_SIZE = 20
LEXML_RESULT_PAGE_CAPTURE_BYTES = 512 * 1024
LEXML_CONNECT_TIMEOUT_SECONDS = 20
LEXML_READ_TIMEOUT_SECONDS = 60
LEXML_REQUEST_MAX_ATTEMPTS = 3

# Hard cap required by the feature request: never collect more than 2GB in total.
MAX_LEXML_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024

DOC_BLOCK_PATTERN = re.compile(r'<div id="main_\d+" class="docHit">\s*<table>(.*?)</table>\s*</div>', re.S)
ROW_PATTERN = re.compile(
    r'<td class="col2"><b>(.*?)</b></td><td class="col3">(.*?)</td><td class="col4">.*?</td></tr>',
    re.S,
)


@dataclass(slots=True)
class LexMLDocumentRecord:
    title: str
    authority: str
    locality: str
    document_date: str
    urn: str
    summary: str
    relative_href: str
    resolution_url: str
    search_page_url: str
    page_number: int


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_html(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = unescape(no_tags).replace("\xa0", " ")
    return _collapse_whitespace(normalized)


def _slugify(value: str) -> str:
    ascii_only = re.sub(r"[^A-Za-z0-9]+", "_", value)
    collapsed = re.sub(r"_+", "_", ascii_only).strip("_").lower()
    return collapsed or "document"


def _has_local_lexml_data(directory: Path) -> bool:
    if not directory.exists():
        return False
    return any(path.is_file() and path.name != ".gitkeep" for path in directory.rglob("*"))


class GetDataFromLexMLService:
    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None):
        self.settings = settings or get_settings()
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "raglab/0.1.0 (+https://github.com/VCLME/raglab)",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        self.total_downloaded_bytes = 0

    def _build_search_params(self, start_doc: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"f1-tipoDocumento": LEXML_LEGISLATION_FILTER}
        if start_doc and start_doc > 1:
            params["startDoc"] = start_doc
        return params

    def _fetch_search_page(self, *, start_doc: int | None = None) -> tuple[str | None, bool]:
        url = f"{LEXML_BASE_URL}{LEXML_SEARCH_PATH}"
        params = self._build_search_params(start_doc)

        for attempt in range(1, LEXML_REQUEST_MAX_ATTEMPTS + 1):
            try:
                with self.session.get(
                    url,
                    params=params,
                    timeout=(LEXML_CONNECT_TIMEOUT_SECONDS, LEXML_READ_TIMEOUT_SECONDS),
                    stream=True,
                ) as response:
                    response.raise_for_status()

                    buffer = bytearray()
                    limit_hit = False
                    for chunk in response.iter_content(chunk_size=8192):
                        if not chunk:
                            continue

                        remaining = MAX_LEXML_DOWNLOAD_BYTES - self.total_downloaded_bytes
                        if remaining <= 0:
                            limit_hit = True
                            break

                        if len(chunk) > remaining:
                            buffer.extend(chunk[:remaining])
                            self.total_downloaded_bytes += remaining
                            limit_hit = True
                            break

                        buffer.extend(chunk)
                        self.total_downloaded_bytes += len(chunk)

                        if len(buffer) >= LEXML_RESULT_PAGE_CAPTURE_BYTES:
                            break

                if limit_hit:
                    log_event(
                        LOGGER,
                        logging.INFO,
                        "lexml.limit_reached",
                        downloaded_bytes=self.total_downloaded_bytes,
                    )
                    return None, True

                return buffer.decode("utf-8", errors="ignore"), False
            except requests.RequestException as exc:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "lexml.page_fetch_failed",
                    attempt=attempt,
                    max_attempts=LEXML_REQUEST_MAX_ATTEMPTS,
                    start_doc=start_doc or 1,
                    error=str(exc),
                )

        log_event(
            LOGGER,
            logging.ERROR,
            "lexml.page_fetch_aborted",
            start_doc=start_doc or 1,
        )
        return None, False

    def _parse_search_page(self, html: str, *, page_number: int, search_page_url: str) -> list[LexMLDocumentRecord]:
        records: list[LexMLDocumentRecord] = []

        for block in DOC_BLOCK_PATTERN.findall(html):
            rows: dict[str, str] = {}
            for raw_key, raw_value in ROW_PATTERN.findall(block):
                key = _strip_html(raw_key).lower()
                rows[key] = raw_value

            title_html = rows.get("título") or rows.get("titulo")
            urn = _strip_html(rows.get("urn", ""))
            if not title_html or not urn:
                continue

            href_match = re.search(r'href="([^"]+)"', title_html)
            relative_href = href_match.group(1) if href_match else ""
            title = _strip_html(title_html)

            record = LexMLDocumentRecord(
                title=title,
                authority=_strip_html(rows.get("autoridade", "")),
                locality=_strip_html(rows.get("localidade", "")),
                document_date=_strip_html(rows.get("data", "")),
                urn=urn,
                summary=_strip_html(rows.get("ementa", "")),
                relative_href=relative_href,
                resolution_url=urljoin(LEXML_BASE_URL, relative_href),
                search_page_url=search_page_url,
                page_number=page_number,
            )
            records.append(record)

        return records

    def _record_paths(self, output_dir: Path, record: LexMLDocumentRecord) -> tuple[Path, Path]:
        digest = hashlib.sha1(record.urn.encode("utf-8")).hexdigest()[:12]
        stem = f"lexml_{digest}_{_slugify(record.title)[:80]}"
        return output_dir / f"{stem}.txt", output_dir / f"{stem}.json"

    def _write_record(self, output_dir: Path, record: LexMLDocumentRecord) -> None:
        text_path, metadata_path = self._record_paths(output_dir, record)
        text_tmp = text_path.with_suffix(".txt.part")
        metadata_tmp = metadata_path.with_suffix(".json.part")

        text_payload = "\n".join(
            [
                "LexML Brasil",
                f"Titulo: {record.title}",
                f"Autoridade: {record.authority}",
                f"Localidade: {record.locality}",
                f"Data: {record.document_date}",
                f"URN: {record.urn}",
                f"URL LexML: {record.resolution_url}",
                f"Pagina de busca: {record.search_page_url}",
                "",
                "Ementa:",
                record.summary,
                "",
            ]
        )
        metadata_payload = asdict(record)

        text_tmp.write_text(text_payload, encoding="utf-8")
        metadata_tmp.write_text(json.dumps(metadata_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        text_tmp.replace(text_path)
        metadata_tmp.replace(metadata_path)

    def run(
        self,
        *,
        output_dir: Path | None = None,
        page_limit: int | None = None,
    ) -> dict[str, Any]:
        target_dir = (output_dir or self.settings.lexml_documents_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        if _has_local_lexml_data(target_dir):
            log_event(
                LOGGER,
                logging.INFO,
                "lexml.collection_skipped",
                output_dir=target_dir,
                reason="local_data_exists",
            )
            return {
                "status": "skipped",
                "output_dir": str(target_dir),
                "downloaded_files": 0,
                "downloaded_bytes": 0,
                "pages_processed": 0,
                "limit_hit": False,
            }

        log_event(
            LOGGER,
            logging.INFO,
            "lexml.collection_started",
            output_dir=target_dir,
            page_limit=page_limit,
        )

        downloaded_files = 0
        pages_processed = 0
        seen_urns: set[str] = set()
        limit_hit = False
        network_failure = False
        start_doc = 1

        while page_limit is None or pages_processed < page_limit:
            query_url = f"{LEXML_BASE_URL}{LEXML_SEARCH_PATH}?f1-tipoDocumento=Legislação"
            if start_doc > 1:
                query_url = f"{query_url}&startDoc={start_doc}"

            html, page_limit_hit = self._fetch_search_page(start_doc=start_doc if start_doc > 1 else None)
            if page_limit_hit:
                limit_hit = True
                break
            if not html:
                network_failure = True
                break

            page_number = pages_processed + 1
            records = self._parse_search_page(html, page_number=page_number, search_page_url=query_url)
            if not records:
                log_event(
                    LOGGER,
                    logging.INFO,
                    "lexml.collection_stopped",
                    reason="no_more_records",
                    page_number=page_number,
                )
                break

            new_records = 0
            for record in records:
                if record.urn in seen_urns:
                    continue
                self._write_record(target_dir, record)
                seen_urns.add(record.urn)
                downloaded_files += 1
                new_records += 1

            pages_processed += 1
            log_event(
                LOGGER,
                logging.INFO,
                "lexml.page_processed",
                page_number=page_number,
                new_files=new_records,
                total_files=downloaded_files,
                downloaded_bytes=self.total_downloaded_bytes,
            )

            if new_records == 0:
                log_event(
                    LOGGER,
                    logging.INFO,
                    "lexml.collection_stopped",
                    reason="duplicates_only",
                    page_number=page_number,
                )
                break

            start_doc += LEXML_PAGE_SIZE

        if limit_hit:
            log_event(
                LOGGER,
                logging.INFO,
                "lexml.collection_stopped",
                reason="hard_limit_reached",
                downloaded_bytes=self.total_downloaded_bytes,
            )

        log_event(
            LOGGER,
            logging.INFO,
            "lexml.collection_completed",
            downloaded_files=downloaded_files,
            downloaded_bytes=self.total_downloaded_bytes,
            pages_processed=pages_processed,
            limit_hit=limit_hit,
        )

        status = "completed"
        if limit_hit:
            status = "limit_hit"
        elif network_failure and downloaded_files == 0:
            status = "failed"
        elif network_failure:
            status = "partial"

        return {
            "status": status,
            "output_dir": str(target_dir),
            "downloaded_files": downloaded_files,
            "downloaded_bytes": self.total_downloaded_bytes,
            "pages_processed": pages_processed,
            "limit_hit": limit_hit,
        }


def getDataFromLexML(
    *,
    output_dir: Path | None = None,
    page_limit: int | None = None,
    settings: Settings | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    service = GetDataFromLexMLService(settings=settings, session=session)
    return service.run(output_dir=output_dir, page_limit=page_limit)
