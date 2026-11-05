"""Grade the same recorded answers again under another judge protocol.

Audit 2026-11-04, lot 2: until 8711e3c the faithfulness judge read the raw
text of the chunks the writer got, while the writer read them with a
version line (and, for compiled Brazilian texts, repealed provisions
replaced by a note). This module isolates the effect of that difference:
the answers of a detailed recall report are not regenerated, only judged
again, once on the raw texts (protocol v1) and once on the passages as
presented (v2), rebuilt from the recorded chunks and versions with the
clock frozen on the day of the run.

The original scores stay where they are; the new ones go to a new file.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from raglab.benchmarks.compare import mcnemar_exact, paired_bootstrap
from raglab.config import Settings, get_settings
from raglab.domain.schemas import RetrievedChunk
from raglab.experiments.ragas import JudgeConfig
from raglab.experiments.recall import _build_judges
from raglab.generation.prompts import presented_passages
from raglab.llm.local_server import LocalLLMServer

PROTOCOLS = ("raw", "presented")


def contexts(detail: dict[str, Any], protocol: str, today: date) -> list[str]:
    """The writer's context of one recorded answer, under a protocol."""
    size = detail.get("generation_context_size") or None
    chunks = detail["retrieved_chunks"][:size]
    if protocol == "raw":
        return [chunk["chunk_text"] for chunk in chunks]
    if detail.get("generation_context") is not None:
        return list(detail["generation_context"])
    return presented_passages([RetrievedChunk.model_validate(chunk) for chunk in chunks], today=today)


def annotated(detail: dict[str, Any], today: date) -> bool:
    """Whether the presented context differs from the raw one."""
    size = detail.get("generation_context_size") or None
    chunks = detail["retrieved_chunks"][:size]
    raw = [chunk["chunk_text"] for chunk in chunks]
    shown = presented_passages([RetrievedChunk.model_validate(chunk) for chunk in chunks], today=today)
    plain = presented_passages(
        [RetrievedChunk.model_validate({**chunk, "version": None}) for chunk in chunks], today=today
    )
    return shown != plain or not raw


def rejudge(
    report_path: Path,
    *,
    protocols: tuple[str, ...] = PROTOCOLS,
    today: date,
    settings: Settings | None = None,
    judge: JudgeConfig | None = None,
) -> dict[str, Any]:
    """Faithfulness of every answered case of the report, per protocol."""
    settings = settings or get_settings()
    judge = judge or JudgeConfig()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    details = [detail for detail in report["details"] if detail.get("answer")]
    judges = _build_judges(settings, judge)
    rows: list[dict[str, Any]] = []

    def grade_all() -> None:
        for detail in details:
            row: dict[str, Any] = {
                "id": detail["id"],
                "annotated": annotated(detail, today),
                "original": (detail.get("metrics") or {}).get("faithfulness"),
            }
            for protocol in protocols:
                verdict = judges["faithfulness"].score(
                    question=detail["question"],
                    answer=detail["answer"],
                    retrieved_texts=contexts(detail, protocol, today),
                )
                row[protocol] = verdict.score
                row[f"{protocol}_reason"] = verdict.reason
            rows.append(row)

    if judge.backend == "llamacpp":
        with LocalLLMServer(settings, profile=judge.profile or settings.judge_model_profile):
            grade_all()
    else:
        grade_all()
    return {
        "kind": "rejudge",
        "created_at": datetime.now(UTC).isoformat(),
        "report": str(report_path).replace("\\", "/"),
        "report_judge": report.get("judge"),
        "judge": judge.label(settings),
        "clock": today.isoformat(),
        "protocols": list(protocols),
        "summary": summarize(rows, protocols),
        "rows": rows,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict[str, Any]], protocols: tuple[str, ...] | list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"answers": len(rows), "annotated": sum(bool(row["annotated"]) for row in rows)}
    for key in ("original", *protocols):
        summary[key] = _mean([row[key] for row in rows if row.get(key) is not None])
    if "raw" in protocols and "presented" in protocols:
        pairs = [
            (row["raw"], row["presented"]) for row in rows if row["raw"] is not None and row["presented"] is not None
        ]
        low, high = paired_bootstrap([a for a, _ in pairs], [b for _, b in pairs]) if pairs else (0.0, 0.0)
        full_raw = sum(1 for a, b in pairs if a == 1.0 and b != 1.0)
        full_presented = sum(1 for a, b in pairs if b == 1.0 and a != 1.0)
        summary["paired"] = {
            "answers": len(pairs),
            "delta": _mean([b - a for a, b in pairs]),
            "ci95": [round(low, 4), round(high, 4)],
            "fully_faithful_only_raw": full_raw,
            "fully_faithful_only_presented": full_presented,
            "p_mcnemar_fully_faithful": round(mcnemar_exact(full_raw, full_presented), 4),
            "changed": sum(1 for a, b in pairs if a != b),
        }
        if "original" in summary:
            same = [
                (row["original"], row["raw"])
                for row in rows
                if row.get("original") is not None and row["raw"] is not None
            ]
            summary["raw_vs_original_changed"] = sum(1 for a, b in same if a != b)
    return summary
