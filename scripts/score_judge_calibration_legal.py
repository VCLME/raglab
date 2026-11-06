"""Agreement between the judge and human verdicts on the legal calibration set.

Refuses to report anything while no case carries a human verdict: model
verdicts are never compared with themselves.

    python scripts/score_judge_calibration_legal.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASES = Path(__file__).resolve().parent.parent / "benchmarks" / "judge_calibration_legal" / "cases.jsonl"
TRAP_LABELS = {"missing_condition_not_flagged", "exception_ignored", "conclusion_beyond_context"}


def main() -> None:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    annotated = [case for case in cases if case.get("human_verdict")]
    if not annotated:
        sys.exit(f"{len(cases)} cases, no human verdict yet: nothing to measure (see the README).")
    agree = sum(
        (case["model_verdicts"].get("faithfulness") == 1.0) == (case["human_verdict"] == "supported")
        for case in annotated
    )
    traps = [case for case in annotated if TRAP_LABELS & set(case.get("human_labels") or [])]
    false_faithful = sum(1 for case in traps if case["model_verdicts"].get("faithfulness") == 1.0)
    print(f"annotated {len(annotated)} / {len(cases)}")
    print(f"faithful agreement {agree}/{len(annotated)} = {agree / len(annotated):.3f}")
    print(f"trap cases {len(traps)}, judged fully faithful by the model: {false_faithful}")


if __name__ == "__main__":
    main()
