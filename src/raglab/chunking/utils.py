from __future__ import annotations

import re


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    pattern = re.compile(r".+?(?:[.!?]+(?:\s+|$)|\n{2,}|$)", re.DOTALL)
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        segment = text[start:end]
        stripped = segment.strip()
        if not stripped:
            continue
        left_trim = len(segment) - len(segment.lstrip())
        right_trim = len(segment.rstrip())
        adjusted_start = start + left_trim
        adjusted_end = start + right_trim
        if adjusted_end > adjusted_start:
            spans.append((adjusted_start, adjusted_end))
    return spans


def find_next_start_index(
    spans: list[tuple[int, int]],
    *,
    current_start_index: int,
    target_start_char: int,
) -> int:
    for idx in range(current_start_index + 1, len(spans)):
        if spans[idx][0] >= target_start_char:
            return idx
    return min(len(spans), current_start_index + 1)
