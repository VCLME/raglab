from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from raglab.db.crud import get_or_create_corpus, upsert_document
from raglab.db.lexical import normalize_language
from raglab.document_metadata import build_document_metadata
from raglab.domain.schemas import DocumentPayload
from raglab.ingestion.readers import SUPPORTED_EXTENSIONS, compute_checksum, extract_text, guess_mime_type
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


def detect_corpus_language(root: Path) -> str | None:
    """Language declared by a benchmark loader's metadata.json next to the corpus."""
    for candidate in (root / "metadata.json", root.parent / "metadata.json"):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("language"):
            return normalize_language(payload["language"])
    return None


class IngestionService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_folder(
        self,
        folder: Path,
        *,
        corpus_name: str,
        description: str | None = None,
        tags: list[str] | None = None,
        language: str | None = None,
    ) -> dict[str, int]:
        root = folder.resolve()
        corpus_language = normalize_language(language) or detect_corpus_language(root)
        log_event(
            LOGGER,
            logging.INFO,
            "ingestion.started",
            corpus_name=corpus_name,
            folder=root,
            tags=tags or [],
            language=corpus_language,
        )
        corpus = get_or_create_corpus(
            self.session,
            name=corpus_name,
            root_path=str(root),
            description=description,
            language=corpus_language,
        )

        ingested = 0
        updated = 0
        skipped = 0

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            text = extract_text(path)
            if not text.strip():
                skipped += 1
                continue

            payload = DocumentPayload(
                source_path=path.resolve(),
                file_name=path.name,
                extension=path.suffix.lower(),
                mime_type=guess_mime_type(path),
                checksum=compute_checksum(path),
                content=text,
                char_count=len(text),
                metadata_json=build_document_metadata(path, root=root, extra_tags=tags),
            )

            _, is_new = upsert_document(self.session, corpus=corpus, payload=payload)
            if is_new:
                ingested += 1
            else:
                updated += 1

        self.session.commit()
        summary = {"ingested": ingested, "updated": updated, "skipped": skipped}
        log_event(
            LOGGER,
            logging.INFO,
            "ingestion.completed",
            corpus_name=corpus_name,
            folder=root,
            **summary,
        )
        return summary
