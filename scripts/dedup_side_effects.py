"""Does de-duplication change anything besides the passages it drops?

For two `raglab bench all` runs on the same questions, dedup off and on, from
their detailed reports: per suite, the questions where dedup dropped nothing
but the retrieved passages still differ (another set, or the same set in
another order), and recall@5 changes split by whether dedup dropped a
passage. A pure filter shows 0 differences on untouched questions.

    python scripts/dedup_side_effects.py pinned-order-dedup-off pinned-order-dedup-on --k 10

`--reference <label>` also compares the first run with an earlier dedup-off
run, to check a change leaves dedup-off results as they were.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _run(label: str) -> dict:
    return json.loads((Path("benchmarks/results") / f"{label}.json").read_text(encoding="utf-8"))


def _details(run: dict, suite: str) -> dict[str, dict]:
    path = next(s["report_path"] for s in run["suites"] if s["suite"] == suite)
    for root in [Path("."), *(Path(p) for p in os.environ.get("RAGLAB_REPORT_ROOTS", "").split(os.pathsep) if p)]:
        if (root / path).exists():
            report = json.loads((root / path).read_text(encoding="utf-8"))
            return {detail["id"]: detail for detail in report["details"]}
    sys.exit(f"{suite}: report {path} not found (set RAGLAB_REPORT_ROOTS)")


def _ids(detail: dict, k: int) -> list[str]:
    return [chunk["chunk_id"] for chunk in detail["retrieved_chunks"][:k]]


def _translation_fallback(detail: dict) -> bool:
    return bool((detail.get("query_translation") or {}).get("notice") == "writer_unavailable")


def compare(off: dict[str, dict], on: dict[str, dict], k: int) -> dict:
    touched = {i for i, d in on.items() if (d.get("dedup_stats") or {}).get("dropped")}
    other_set, other_order, fallbacks, gained, lost = [], [], [], [], []
    for i, detail in on.items():
        if _translation_fallback(detail) or _translation_fallback(off[i]):
            fallbacks.append(i)
            continue
        a, b = _ids(off[i], k), _ids(detail, k)
        if i not in touched:
            if set(a) != set(b):
                other_set.append(i)
            elif a != b:
                other_order.append(i)
        before, after = bool(off[i]["metrics"].get("recall@5")), bool(detail["metrics"].get("recall@5"))
        if after and not before:
            gained.append(i)
        elif before and not after:
            lost.append(i)
    return {
        "questions": len(on),
        "touched": len(touched),
        "untouched_other_set": other_set,
        "untouched_other_order": other_order,
        "recall5_gained": gained,
        "recall5_lost": lost,
        "translation_fallbacks": fallbacks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("off")
    parser.add_argument("on")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--reference", help="earlier dedup-off run the first run should equal")
    args = parser.parse_args()
    off, on = _run(args.off), _run(args.on)
    reference = _run(args.reference) if args.reference else None
    print(f"`{args.off}` → `{args.on}`, top-{args.k}\n")
    print("| Suite | Questions | Dedup dropped in | Untouched, other set | Untouched, other order | Recall@5 +/− |")
    print("|---|---|---|---|---|---|")
    notes = []
    for suite in [s["suite"] for s in off["suites"]]:
        a, b = _details(off, suite), _details(on, suite)
        row = compare(a, b, args.k)
        print(
            f"| {suite} | {row['questions']} | {row['touched']} | {len(row['untouched_other_set'])}"
            f" | {len(row['untouched_other_order'])} | +{len(row['recall5_gained'])} / −{len(row['recall5_lost'])} |"
        )
        for key in ("untouched_other_set", "untouched_other_order", "recall5_gained", "recall5_lost"):
            if row[key]:
                notes.append(f"- {suite}, {key}: {', '.join(row[key])}")
        if row["translation_fallbacks"]:
            notes.append(
                f"- {suite}, left out (query translation fell back): {', '.join(row['translation_fallbacks'])}"
            )
        if reference is not None:
            ref = _details(reference, suite)
            changed = [i for i in a if i in ref and _ids(a[i], args.k) != _ids(ref[i], args.k)]
            notes.append(
                f"- {suite}: {len(changed)} questions differ from `{args.reference}`"
                + (f" ({', '.join(changed[:10])})" if changed else "")
            )
    if notes:
        print("\n" + "\n".join(notes))


if __name__ == "__main__":
    main()
