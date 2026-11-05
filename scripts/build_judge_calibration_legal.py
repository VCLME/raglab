"""Prepare benchmarks/judge_calibration_legal/cases.jsonl (no human verdict invented).

Legal answers where a judge is most likely wrong: a rule quoted while its
condition is not shown to hold (Brazil expat Q29: reciprocity, list of
countries absent), exceptions, conclusions the passages do not carry. Cases
are the recorded Brazil expat answers of the query-translation run (all 38)
and the two traps of the other two runs, with the writer's context as
presented (rebuilt with the run's clock), the recorded judge verdicts
(model, protocol v1), and empty human fields to fill.

    python scripts/build_judge_calibration_legal.py <report qt> <report full> <report naive>
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from raglab.experiments.rejudge import contexts

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "benchmarks" / "judge_calibration_legal" / "cases.jsonl"
CLOCK = date(2026, 11, 4)
TRAPS = ("brx-29", "brx-30")


def _cases(report_path: Path, run: str, ids: tuple[str, ...] | None) -> list[dict]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    truth = {
        json.loads(line)["id"]: json.loads(line)
        for line in (ROOT / "benchmarks" / "br_expat" / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    out = []
    for detail in report["details"]:
        if not detail.get("answer") or (ids is not None and detail["id"] not in ids):
            continue
        case = truth[detail["id"]]
        metrics = detail.get("metrics") or {}
        out.append(
            {
                "id": f"{run}:{detail['id']}",
                "question": detail["question"],
                "reference_answer": case.get("ground_truth_answer"),
                "expected_behaviour": (case.get("context") or {}).get("expected_behaviour"),
                "context_presented": contexts(detail, "presented", CLOCK),
                "answer": detail["answer"],
                "model_verdicts": {
                    "judge": report.get("judge"),
                    "protocol": "faithfulness-raw-context-v1",
                    "faithfulness": metrics.get("faithfulness"),
                    "faithfulness_reason": metrics.get("faithfulness_reason"),
                    "answer_correctness": metrics.get("answer_correctness"),
                    "answer_correctness_reason": metrics.get("answer_correctness_reason"),
                },
                # Filled by a person, never by a model.
                "human_verdict": None,
                "human_labels": [],
                "human_annotator": None,
                "human_notes": None,
            }
        )
    return out


def main(qt: str, full: str, naive: str) -> None:
    cases = [
        *_cases(Path(qt), "brexpat-qt-v1", None),
        *_cases(Path(full), "brexpat-full-v1", TRAPS),
        *_cases(Path(naive), "brexpat-naive-v1", TRAPS),
    ]
    TARGET.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")
    print(f"{TARGET.relative_to(ROOT)}: {len(cases)} cases, 0 human verdicts")


if __name__ == "__main__":
    main(*sys.argv[1:4])
