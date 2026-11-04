"""Apply the version rules of `raglab.domain.versions` to a search: does
the corpus carry version metadata, the version state of each retrieved
chunk, repealed-only chunks moved last."""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, exists, select
from sqlalchemy.orm import Session

from raglab.db.models import Document, IndexRun
from raglab.domain.schemas import RetrievedChunk
from raglab.domain.versions import (
    VersionPolicy,
    is_outdated,
    is_versioned,
    marker_version,
    metadata_version,
    resolve_policy,
)

__all__ = [
    "VersionLookup",
    "annotate",
    "corpus_has_versions",
    "demote_revoked",
    "is_outdated",
    "resolve_policy",
]


def corpus_has_versions(session: Session, corpus_id: str) -> bool:
    """One document of the corpus carries version metadata (`etat`).

    Both values are written into the SQL: with bound parameters, once
    psycopg prepares the statement PostgreSQL switches to a generic plan
    that scans every document of every corpus (~40 ms when none matches:
    PIAF, LexML) instead of the corpus's index (< 1 ms).
    """
    stmt = select(
        exists().where(
            Document.corpus_id == bindparam("corpus_id", corpus_id, literal_execute=True),
            Document.metadata_json.has_key(bindparam("key", "etat", literal_execute=True)),
        )
    )
    return bool(session.execute(stmt).scalar_one())


class VersionLookup:
    """The two reads the versions option makes: whether the corpus has
    version metadata (one EXISTS) and the metadata of the retrieved chunks'
    documents (one SELECT on their ids)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def has_history(self, index_run: IndexRun) -> bool:
        return corpus_has_versions(self.session, index_run.corpus_id)

    def metadata(self, document_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not document_ids:
            return {}
        rows = self.session.execute(
            select(Document.id, Document.metadata_json).where(Document.id.in_(document_ids))
        ).all()
        return {str(document_id): meta or {} for document_id, meta in rows}


def annotate(
    chunks: list[RetrievedChunk],
    policy: VersionPolicy,
    metadata: dict[str, dict[str, Any]],
) -> list[RetrievedChunk]:
    """Attach `version` to every chunk: from its document's metadata
    (Légifrance) or from its own markers (LexML); untouched otherwise."""
    annotated: list[RetrievedChunk] = []
    for chunk in chunks:
        meta = metadata.get(str(chunk.document_id), {})
        version = metadata_version(meta, policy.on) if is_versioned(meta) else marker_version(chunk.chunk_text)
        if version is not None and not policy.filters:
            version = version.model_copy(update={"in_prompt": False})
        annotated.append(chunk.model_copy(update={"version": version}) if version is not None else chunk)
    return annotated


def demote_revoked(chunks: list[RetrievedChunk]) -> tuple[list[RetrievedChunk], int]:
    """Move chunks whose every provision is repealed (markers) after the
    others, keeping each group's order; a pinned cited article stays put.
    Returns the new list (ranks renumbered) and how many moved."""
    kept: list[RetrievedChunk] = []
    moved: list[RetrievedChunk] = []
    for chunk in chunks:
        version = chunk.version
        if version is not None and version.revoked_only and not chunk.citation_match:
            moved.append(chunk.model_copy(update={"version": version.model_copy(update={"demoted": True})}))
        else:
            kept.append(chunk)
    if not moved:
        return chunks, 0
    ordered = [*kept, *moved]
    return [chunk.model_copy(update={"rank": rank}) for rank, chunk in enumerate(ordered, start=1)], len(moved)
