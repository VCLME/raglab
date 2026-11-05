"""Conservative de-duplication of the final passages, refilled from a deeper pool.

Audit 2026-11-04, lot 3 (experimental, off by default: `RAGLAB_RETRIEVAL_DEDUP`,
option `dedup`). In Brazil expat Q28, three of the five passages were cuts of
the same sentence of Decreto 6.306 (overlapping offsets of one document):
the writer read one fact three times instead of two other passages.
Dropping duplicates from the final five alone would leave the places empty,
so the selection walks a deeper ranked pool (the re-ranker's 40 candidates)
and keeps the first `top_k` distinct passages.

A passage is dropped only when all of these hold against a passage already
kept: same document and same version state, the spans overlap on at least
`MIN_OVERLAP` of the dropped passage, and what it adds beyond the kept span
carries no number, negation or exception word (so "25 %" vs "2,5 %", "não"
or "salvo" never merge). Identical text in two documents of the same version
state is dropped too. Pinned citation passages are never dropped. Kept
passages keep their offsets, scores and ranks of origin; only `rank` is
renumbered. Chunkers are untouched: this reads chunk spans and text.
"""

from __future__ import annotations

import re
from typing import Any

from raglab.domain.schemas import RetrievedChunk

# Share of the dropped passage's span that must lie inside a kept one.
MIN_OVERLAP = 0.8
# What must not be lost: numbers (amounts, rates, dates, article numbers,
# roman numerals of items), negations and exceptions, in fr / pt / en.
_PROTECTED_RE = re.compile(
    r"\d|\b[IVXLC]{1,6}\b|"
    r"\b(?:n[ãa]o|nem|nunca|jamais|nenhum[a]?|ne|pas|sans|aucun[e]?|ni|not|no|never|none|without|"
    r"salvo|exceto|ressalvad[oa]s?|sauf|except|unless|hormis|à l'exception|exception|exce[cç][aã]o)\b",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")


def _version_key(chunk: RetrievedChunk) -> tuple[Any, ...]:
    version = chunk.version
    if version is None:
        return ()
    return (version.source, version.etat, version.in_force, version.revoked_lines, version.revoked_only)


def _normalized(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _uncovered_text(chunk: RetrievedChunk, kept: RetrievedChunk) -> str | None:
    """The part of `chunk` outside `kept`'s span, when they share a document
    and the overlap covers at least MIN_OVERLAP of `chunk`; None otherwise."""
    if chunk.document_id != kept.document_id:
        return None
    if None in (chunk.char_start, chunk.char_end, kept.char_start, kept.char_end):
        return None
    start, end = int(chunk.char_start), int(chunk.char_end)  # type: ignore[arg-type]
    kept_start, kept_end = int(kept.char_start), int(kept.char_end)  # type: ignore[arg-type]
    length = end - start
    overlap = min(end, kept_end) - max(start, kept_start)
    if length <= 0 or overlap < MIN_OVERLAP * length:
        return None
    # Offsets index the document; the chunk text starts at char_start.
    before = chunk.chunk_text[: max(0, kept_start - start)]
    after = chunk.chunk_text[max(0, kept_end - start) :]
    return before + " " + after


def redundant(chunk: RetrievedChunk, kept: RetrievedChunk) -> bool:
    """Whether `chunk` adds nothing that `kept` does not already give."""
    if _version_key(chunk) != _version_key(kept):
        return False
    if _normalized(chunk.chunk_text) == _normalized(kept.chunk_text):
        return True
    extra = _uncovered_text(chunk, kept)
    return extra is not None and _PROTECTED_RE.search(extra) is None


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
