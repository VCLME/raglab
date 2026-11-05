"""Proof artifact of a rejudge: everything needed to check the scores again.

For each answer of a `raglab bench rejudge` result, writes one JSON line with
the question, the recorded answer, the writer's context under both judge
protocols (raw chunk texts, v1; passages as presented, v2, rebuilt with the
recorded clock), the judge's scores and reasons, and sha256 digests of the
answer and of each context. The first line describes the run: source report
and its digest, judge, clock, protocols, code commit.

    python scripts/judging_proof.py benchmarks/judging/<rejudge>.json <report>.json benchmarks/judging/<proof>.jsonl
    python scripts/judging_proof.py --verify benchmarks/judging/<proof>.jsonl <report>.json

`--verify` rebuilds the contexts from the report and checks every digest.
Corpora are public (Légifrance consolidated codes); nothing private is written.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from raglab.experiments.rejudge import contexts


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build(rejudge_path: Path, report_path: Path, out: Path) -> None:
    rejudge = json.loads(rejudge_path.read_text(encoding="utf-8"))
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    details = {detail["id"]: detail for detail in report["details"] if detail.get("answer")}
    clock = date.fromisoformat(rejudge["clock"])
    lines = [
        {
            "kind": "rejudge_proof",
            "rejudge": rejudge_path.name,
            "report": report_path.name,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "judge": rejudge["judge"],
            "report_judge": rejudge.get("report_judge"),
            "clock": rejudge["clock"],
            "protocols": rejudge["protocols"],
            "commit": _commit(),
            "answers": len(rejudge["rows"]),
        }
    ]
    for row in rejudge["rows"]:
        detail = details[row["id"]]
        raw = contexts(detail, "raw", clock)
        presented = contexts(detail, "presented", clock)
        lines.append(
            {
                "id": row["id"],
                "question": detail["question"],
                "answer": detail["answer"],
                "answer_sha256": _sha(detail["answer"]),
                "contexts": {"raw": raw, "presented": presented},
                "contexts_sha256": {"raw": [_sha(t) for t in raw], "presented": [_sha(t) for t in presented]},
                "annotated": row["annotated"],
                "scores": {
                    "original_v1": row.get("original"),
                    "raw": row.get("raw"),
                    "presented": row.get("presented"),
                },
                "reasons": {"raw": row.get("raw_reason"), "presented": row.get("presented_reason")},
            }
        )
    out.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")
    print(f"{out}: {len(lines) - 1} answers")


def verify(proof_path: Path, report_path: Path) -> None:
    lines = [json.loads(line) for line in proof_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    header, rows = lines[0], lines[1:]
    report_bytes = report_path.read_bytes()
    problems = []
    if hashlib.sha256(report_bytes).hexdigest() != header["report_sha256"]:
        problems.append("report digest")
    details = {detail["id"]: detail for detail in json.loads(report_bytes)["details"]}
    clock = date.fromisoformat(header["clock"])
    for row in rows:
        detail = details[row["id"]]
        if _sha(detail["answer"]) != row["answer_sha256"]:
            problems.append(f"{row['id']}: answer")
        for protocol in ("raw", "presented"):
            rebuilt = [_sha(text) for text in contexts(detail, protocol, clock)]
            if rebuilt != row["contexts_sha256"][protocol]:
                problems.append(f"{row['id']}: {protocol} context")
    print(f"{proof_path.name}: {len(rows)} answers, {'OK' if not problems else problems[:5]}")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1] == "--verify":
        verify(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
