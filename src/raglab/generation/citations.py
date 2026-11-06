"""Citation markers written by the writer.

The prompt asks for `[Rank N]`, but the context headers read
`[Source rank=N]` and writers sometimes copy that form, group several ranks
in one bracket (`[Rank 1, Rank 3]`, `[Ranks 2 et 4]`) or give a range
(`[Rank 2-4]`). `normalize_citations` rewrites all of them to `[Rank N]`
markers so the UI, the history and the CLI read one form. The UI's
AnswerText.tsx parses the same grammar while the answer streams.
"""

from __future__ import annotations

import re

_KEY = r"(?:source\s*)?ranks?\s*[=:]?\s*"
_NUM = r"\d+(?:\s*(?:-|–|à|to)\s*\d+)?"
_SEP = r"\s*(?:,|;|&|\band\b|\bet\b|\be\b)\s*"
CITATION_MARKER = re.compile(
    rf"[\[(]\s*(?:{_KEY})(?:{_NUM})(?:{_SEP}(?:{_KEY})?(?:{_NUM}))*\s*[\])]",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(\d+)(?:\s*(?:-|–|à|to)\s*(\d+))?", re.IGNORECASE)
# A range longer than this is read as two ranks, not expanded.
_MAX_RANGE = 10
_TRAILING_SOURCES = re.compile(r"\n+\s*Sources?\s*:[\s\S]*$", re.IGNORECASE)


def marker_ranks(marker: str) -> list[int]:
    """The ranks one marker cites, in order: "[Rank 2-4]" -> [2, 3, 4]."""
    ranks: list[int] = []
    for start, end in _NUMBER.findall(marker):
        first = int(start)
        last = int(end) if end else first
        span = range(first, last + 1) if first <= last <= first + _MAX_RANGE else (first, last)
        ranks.extend(rank for rank in span if rank not in ranks)
    return ranks


def normalize_citations(answer: str) -> str:
    """Every citation marker of `answer` as one `[Rank N]` per cited rank."""
    return CITATION_MARKER.sub(lambda match: "".join(f"[Rank {rank}]" for rank in marker_ranks(match.group(0))), answer)


def cited_ranks(answer: str | None) -> set[int]:
    """Ranks the answer cites, ignoring a trailing "Sources:" list."""
    if not answer:
        return set()
    body = _TRAILING_SOURCES.sub("", answer)
    return {rank for match in CITATION_MARKER.finditer(body) for rank in marker_ranks(match.group(0))}
