from __future__ import annotations

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
