from __future__ import annotations

import re
from collections.abc import Callable


def relevance_flags[T](items: list[T], *, is_relevant: Callable[[T], bool]) -> list[bool]:
    return [bool(is_relevant(item)) for item in items]


def first_relevant_rank(flags: list[bool]) -> int | None:
    for index, flag in enumerate(flags, start=1):
        if flag:
            return index
    return None


def reciprocal_rank(flags: list[bool]) -> float:
    rank = first_relevant_rank(flags)
    if rank is None:
        return 0.0
    return 1.0 / rank


def hit_at_k(flags: list[bool], k: int) -> bool:
    if k < 1:
        raise ValueError("k doit etre >= 1")
    return any(flags[:k])


def precision_at_k(flags: list[bool], k: int) -> float:
    if k < 1:
        raise ValueError("k doit etre >= 1")
    return sum(flags[:k]) / k


def outdated_hit_at_k(relevant: list[bool], outdated: list[bool], k: int) -> bool:
    """An outdated version is in the top-k and ranked above the version that
    answers (or the answer is not in the top-k at all): the "versions"
    failure mode at retrieval time (phase 9.10)."""
    if k < 1:
        raise ValueError("k doit etre >= 1")
    first_outdated = first_relevant_rank(outdated[:k])
    if first_outdated is None:
        return False
    first_relevant = first_relevant_rank(relevant[:k])
    return first_relevant is None or first_outdated < first_relevant


def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").split())


_ARTICLE_RE = re.compile(r"\b(LO|L|R|D|A)\.?\s*(\d+(?:-\d+)*)\b", re.IGNORECASE)


def _article_mentions(text: str) -> set[str]:
    """Article numbers cited in a text, normalised ("L. 121-21" -> "L121-21")."""
    return {f"{letters.upper()}{number}" for letters, number in _ARTICLE_RE.findall(text)}


def answer_cites_outdated(answer: str | None, trap: dict | None, expected_article: str | None = None) -> bool:
    """The answer states what only the outdated version says: the trap's
    own answer ("sept jours" where the version in force says "quatorze
    jours"), or, when the outdated version is another article, its number
    without the expected one."""
    if not answer or not trap:
        return False
    outdated_answer = trap.get("answer")
    if outdated_answer and _normalise(outdated_answer) in _normalise(answer):
        expected = trap.get("expected_answer")
        if not expected or _normalise(expected) not in _normalise(answer):
            return True
    article = trap.get("article")
    if article and expected_article and article != expected_article:
        cited = _article_mentions(answer)
        return article in cited and expected_article not in cited
    return False
