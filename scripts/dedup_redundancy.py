"""Context redundancy of two benchmark runs (audit 2026-11-04, lot 3).

For each suite of two `raglab bench all` runs, reads the detailed reports and
counts, in the passages given to the writer (top 5):
- passages that repeat a passage ranked above them (same rule as
  `raglab.retrieval.dedup.redundant`);
- characters of context, and characters of context that are not repeated.

    python scripts/dedup_redundancy.py audit-lot3-dedup-off audit-lot3-dedup-on
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from raglab.benchmarks.compare import paired_bootstrap
from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.dedup import redundant

TOP_K = 5


def _details(suite: dict) -> dict[str, dict]:
    path = Path(suite["report_path"])
    report = json.loads(path.read_text(encoding="utf-8"))
    return {detail["id"]: detail for detail in report["details"]}


def _context(detail: dict) -> tuple[int, int, int]:
    """(repeated passages, context characters, non-repeated characters)."""
    chunks = [RetrievedChunk.model_validate(chunk) for chunk in detail["retrieved_chunks"][:TOP_K]]
    repeated = 0
    useful = 0
    for position, chunk in enumerate(chunks):
        if any(redundant(chunk, earlier) for earlier in chunks[:position]):
            repeated += 1
        else:
            useful += len(chunk.chunk_text)
    return repeated, sum(len(chunk.chunk_text) for chunk in chunks), useful


def main(before: str, after: str) -> None:
    load = lambda name: json.loads((Path("benchmarks/results") / f"{name}.json").read_text(encoding="utf-8"))  # noqa: E731
    runs = load(before), load(after)
    print(
        "| Suite | Questions | With a repeat (before -> after) | Repeated passages | Useful chars / question | Useful share |"
    )
    print("|---|---|---|---|---|---|")
    for suite_a in runs[0]["suites"]:
        suite_b = next(s for s in runs[1]["suites"] if s["suite"] == suite_a["suite"])
        a, b = _details(suite_a), _details(suite_b)
        ids = sorted(set(a) & set(b))
        if set(a) != set(b):
            sys.exit(f"{suite_a['suite']}: the runs do not cover the same questions")
        ca = [_context(a[i]) for i in ids]
        cb = [_context(b[i]) for i in ids]
        with_a = sum(1 for c in ca if c[0])
        with_b = sum(1 for c in cb if c[0])
        useful_a = [c[2] for c in ca]
        useful_b = [c[2] for c in cb]
        low, high = paired_bootstrap([float(v) for v in useful_a], [float(v) for v in useful_b])
        share = lambda cs: sum(c[2] for c in cs) / max(1, sum(c[1] for c in cs))  # noqa: E731
        print(
            f"| {suite_a['suite']} | {len(ids)} | {with_a} -> {with_b} | {sum(c[0] for c in ca)} -> {sum(c[0] for c in cb)}"
            f" | {sum(useful_a) / len(ids):.0f} -> {sum(useful_b) / len(ids):.0f} (95 % CI of the difference"
            f" [{low:+.0f} ; {high:+.0f}]) | {share(ca):.3f} -> {share(cb):.3f} |"
        )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
