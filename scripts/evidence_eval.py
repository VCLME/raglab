"""Evidence levels (article, provision, complete) of recorded runs.

    python scripts/evidence_eval.py br_expat brexpat-naive-v1 brexpat-full-v1 brexpat-qt-v1

Reads benchmarks/<suite>/evidence_v1.jsonl and each run's detailed report
(its `report_path`, looked up in the current directory or RAGLAB_DATA_DIR's
parent). Paired McNemar on `complete` between consecutive runs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from raglab.benchmarks.compare import mcnemar_exact
from raglab.benchmarks.evidence import load_evidence, score_report


def _report(label: str, suite: str) -> dict:
    run = json.loads((Path("benchmarks/results") / f"{label}.json").read_text(encoding="utf-8"))
    path = next(s["report_path"] for s in run["suites"] if s["suite"] == suite)
    roots = [Path("."), *(Path(p) for p in os.environ.get("RAGLAB_REPORT_ROOTS", "").split(os.pathsep) if p)]
    for root in roots:
        if (root / path).exists():
            return json.loads((root / path).read_text(encoding="utf-8"))
    sys.exit(f"{label}: report {path} not found (set RAGLAB_REPORT_ROOTS)")


def main(suite: str, labels: list[str]) -> None:
    evidence = load_evidence(Path("benchmarks") / suite / "evidence_v1.jsonl")
    truth = {
        json.loads(line)["id"]: json.loads(line)["expected_spans"]
        for line in (Path("benchmarks") / suite / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    previous = None
    print(
        "| Run | Questions with evidence | Article | Provision | Complete evidence | Complete: won / lost vs previous |"
    )
    print("|---|---|---|---|---|---|")
    for label in labels:
        scored = score_report(_report(label, suite), truth, evidence)
        rows = {row["id"]: row for row in scored["rows"] if row["complete"] is not None}
        delta = ""
        if previous is not None:
            won = sum(1 for i in rows if rows[i]["complete"] and not previous[i]["complete"])
            lost = sum(1 for i in rows if previous[i]["complete"] and not rows[i]["complete"])
            delta = f"+{won} / −{lost} (p = {mcnemar_exact(won, lost):.3f})"
        print(
            f"| {label} | {scored['with_evidence']} | {scored['article']:.3f} | {scored['provision']:.3f}"
            f" | {scored['complete']:.3f} | {delta} |"
        )
        previous = rows


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
