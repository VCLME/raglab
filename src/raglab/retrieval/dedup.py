"""Conservative de-duplication of the final passages, refilled from a deeper pool.

Audit 2026-11-04, lot 3 (experimental, off by default: `RAGLAB_RETRIEVAL_DEDUP`,
option `dedup`). In Brazil expat Q28, three of the five passages were cuts of
the same sentence of Decreto 6.306 (overlapping offsets of one document):
the writer read one fact three times instead of two other passages.
Dropping duplicates from the final five alone would leave the places empty,
so the selection walks a deeper ranked pool (the re-ranker's 40 candidates)
and keeps the first `top_k` distinct passages.

A passage is dropped only when, against a passage already kept, it shares
the document and the version state and its span lies entirely inside the
kept one: then it adds no character. Text a passage adds beyond a kept span
is never judged useless, whatever it says ("These duties concern legal
persons." carries no number, negation or exception and still says who is
bound): v2 dropped such passages above 80 % overlap, which a review showed
wrong. Identical wording at another place (another article, another law,
another version file) is kept: in legal text the provision that says it
matters (v1 merged it and lost questions, see docs). Pinned citation
passages are never dropped. Kept
passages keep their offsets, scores and ranks of origin; only `rank` is
renumbered. Chunkers are untouched: this reads chunk spans and text.
"""

from __future__ import annotations

from typing import Any

from raglab.domain.schemas import RetrievedChunk


def _version_key(chunk: RetrievedChunk) -> tuple[Any, ...]:
    version = chunk.version
    if version is None:
        return ()
    return (version.source, version.etat, version.in_force, version.revoked_lines, version.revoked_only)


def _contained(chunk: RetrievedChunk, kept: RetrievedChunk) -> bool:
    """Whether `chunk`'s span lies entirely inside `kept`'s, in one document."""
    if chunk.document_id != kept.document_id:
        return False
    if None in (chunk.char_start, chunk.char_end, kept.char_start, kept.char_end):
        return False
    start, end = int(chunk.char_start), int(chunk.char_end)  # type: ignore[arg-type]
    kept_start, kept_end = int(kept.char_start), int(kept.char_end)  # type: ignore[arg-type]
    return end > start and kept_start <= start and end <= kept_end


def redundant(chunk: RetrievedChunk, kept: RetrievedChunk) -> bool:
    """Whether `chunk` adds nothing that `kept` does not already give."""
    return _version_key(chunk) == _version_key(kept) and _contained(chunk, kept)


def select_distinct(ranked: list[RetrievedChunk], top_k: int) -> tuple[list[RetrievedChunk], dict[str, Any]]:
    """The first `top_k` passages of `ranked` that are not redundant with a
    passage kept before them. Returns them (ranks renumbered) and stats:
    pool size, dropped passages (with the passage they repeat) and how many
    places were refilled from beyond the first `top_k`."""
    kept: list[RetrievedChunk] = []
    dropped: list[dict[str, str]] = []
    for position, chunk in enumerate(ranked):
        if len(kept) >= top_k:
            break
        twin = None if chunk.citation_match else next((other for other in kept if redundant(chunk, other)), None)
        if twin is not None:
            dropped.append({"chunk_id": chunk.chunk_id, "duplicate_of": twin.chunk_id, "position": str(position + 1)})
            continue
        kept.append(chunk)
    refilled = sum(1 for chunk in kept if ranked.index(chunk) >= top_k)
    stats = {"pool": len(ranked), "dropped": dropped, "refilled": refilled}
    return [chunk.model_copy(update={"rank": rank}) for rank, chunk in enumerate(kept, start=1)], stats
