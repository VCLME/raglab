"""Evidence sufficiency: was the article found, the provision, all the evidence?

Recall@5 counts a question found when one passage overlaps the expected
article. A question can need several provisions together (a fine needs the
offence and the amount), and the same evidence can exist in two texts (the
law and the decree that repeats it). Evidence files (`evidence_*.jsonl`,
versioned next to a frozen set, which they never modify) describe that:

    {"id": "brx-04", "groups": [{"label": "...", "spans": [{file_name, start, end, text}, ...]}, ...],
     "annotation": "auto-by-file" | "human", "reviewed_by": null | "<name>"}

Every span of a group is needed (cumulative); any one group is enough
(alternatives). Three levels are scored on the top-k passages of a recorded
run, without running anything again:

- `article`: a passage overlaps one of the question's `expected_spans`;
- `provision`: a passage covers at least one evidence span;
- `complete`: for some group, every span is covered.

A span counts as covered when one passage of the same file overlaps at least
half of it (a provision is one line; a chunk boundary may cut it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIN_SPAN_COVER = 0.5


def load_evidence(path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["id"]: row for row in rows}


def _covers(chunk: dict[str, Any], span: dict[str, Any]) -> bool:
    if chunk.get("file_name") != span["file_name"]:
        return False
    if chunk.get("char_start") is None or chunk.get("char_end") is None:
        return False
    overlap = min(int(chunk["char_end"]), int(span["end"])) - max(int(chunk["char_start"]), int(span["start"]))
    length = max(1, int(span["end"]) - int(span["start"]))
    return overlap >= MIN_SPAN_COVER * length


def _overlaps(chunk: dict[str, Any], span: dict[str, Any]) -> bool:
    if chunk.get("file_name") != span.get("file_name"):
        return False
    if chunk.get("char_start") is None or chunk.get("char_end") is None:
        return False
    return min(int(chunk["char_end"]), int(span["end"])) > max(int(chunk["char_start"]), int(span["start"]))


def score_case(
    chunks: list[dict[str, Any]], expected_spans: list[dict[str, Any]], evidence: dict[str, Any] | None
) -> dict[str, Any]:
    article = any(_overlaps(chunk, span) for chunk in chunks for span in expected_spans)
    if evidence is None or not evidence.get("groups"):
        return {"article": article, "provision": None, "complete": None}
    spans = [span for group in evidence["groups"] for span in group["spans"]]
    provision = any(_covers(chunk, span) for chunk in chunks for span in spans)
    complete = any(
        all(any(_covers(chunk, span) for chunk in chunks) for span in group["spans"]) for group in evidence["groups"]
    )
    return {"article": article, "provision": provision, "complete": complete}


def score_report(
    report: dict[str, Any], expected: dict[str, list[dict[str, Any]]], evidence: dict[str, dict[str, Any]], k: int = 5
) -> dict[str, Any]:
    """Per-question levels on the top-k passages of a detailed recall report."""
    rows = []
    for detail in report["details"]:
        chunks = detail["retrieved_chunks"][:k]
        levels = score_case(chunks, expected.get(detail["id"], []), evidence.get(detail["id"]))
        rows.append({"id": detail["id"], **levels})
    scored = [row for row in rows if row["provision"] is not None]
    return {
        "k": k,
        "questions": len(rows),
        "with_evidence": len(scored),
        "article": round(sum(row["article"] for row in scored) / max(1, len(scored)), 4),
        "provision": round(sum(bool(row["provision"]) for row in scored) / max(1, len(scored)), 4),
        "complete": round(sum(bool(row["complete"]) for row in scored) / max(1, len(scored)), 4),
        "rows": rows,
    }
