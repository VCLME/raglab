"""Answer-level comparison of two production runs (review of #83-#85, lot 4).

For each suite of two `raglab bench all` runs made on the same questions
(here de-duplication off and on), from their detailed reports:

- answer correctness (judge, against the reference answer): mean, and
  "fully correct" (score 1.0) as a binary success;
- faithfulness (judge protocol v2, passages as presented): mean, and
  "unsupported claims" = share of answers scored below 1.0;
- false refusals: the writer's fixed no-context sentence although an
  expected passage is in the top 5;
- evidence levels (article, provision, complete) where an evidence file
  exists (Brazil expat, unreviewed groups);
- wall time per question = retrieval + generation, p50 / p95.

Binary successes: exact McNemar. Means: paired bootstrap, resampling groups
of linked questions together (a Brazil expat paraphrase with the question it
rewrites), questions alone elsewhere.

    python scripts/pipeline_report.py pipeline-2026-11-dedup-off pipeline-2026-11-dedup-on
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys
from pathlib import Path

from raglab.benchmarks.compare import mcnemar_exact
from raglab.benchmarks.evidence import load_evidence, score_case
from raglab.generation.prompts import NO_CONTEXT_ANSWERS


def _report(run: dict, suite: str) -> dict:
    path = next(s["report_path"] for s in run["suites"] if s["suite"] == suite)
    for root in [Path("."), *(Path(p) for p in os.environ.get("RAGLAB_REPORT_ROOTS", "").split(os.pathsep) if p)]:
        if (root / path).exists():
            return json.loads((root / path).read_text(encoding="utf-8"))
    sys.exit(f"{suite}: report {path} not found (set RAGLAB_REPORT_ROOTS)")


def _groups(suite: str) -> dict[str, str]:
    """question id -> group id (paraphrases join the question they rewrite)."""
    path = Path("benchmarks") / suite / "ground_truth.jsonl"
    groups = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            origin = (row.get("context") or {}).get("paraphrase_of")
            groups[row["id"]] = str(origin) if origin else row["id"]
    return groups


def _cluster_bootstrap(diffs: dict[str, float], groups: dict[str, str], resamples: int = 2000, seed: int = 0):
    by_group: dict[str, list[float]] = {}
    for key, value in diffs.items():
        by_group.setdefault(groups.get(key, key), []).append(value)
    names = sorted(by_group)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        values = [v for name in (names[rng.randrange(len(names))] for _ in names) for v in by_group[name]]
        means.append(sum(values) / len(values))
    means.sort()
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def _refusal(answer: str | None) -> bool:
    text = (answer or "").strip().lower()
    sentences = [s.lower() for s in NO_CONTEXT_ANSWERS.values()] + ["je ne trouve pas", "não encontrei", "cannot find"]
    return any(sentence[:25] in text for sentence in sentences)


def _case(detail: dict, evidence: dict | None, expected: list) -> dict:
    metrics = detail.get("metrics") or {}
    hit = bool(metrics.get("recall@5"))
    timings = detail.get("timings_ms") or {}
    wall = sum(float(timings.get(key, 0.0)) for key in ("embed", "retrieval", "rerank", "generation"))
    levels = score_case(detail["retrieved_chunks"][:5], expected, evidence) if evidence else {}
    return {
        "answered": bool(detail.get("answer")),
        "correct": metrics.get("answer_correctness"),
        "faithful": metrics.get("faithfulness"),
        "refused": _refusal(detail.get("answer")),
        "false_refusal": _refusal(detail.get("answer")) and hit,
        "hit": hit,
        "complete": levels.get("complete"),
        "provision": levels.get("provision"),
        "wall_ms": wall,
    }


def _p(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def main(before: str, after: str) -> None:
    load = lambda name: json.loads((Path("benchmarks/results") / f"{name}.json").read_text(encoding="utf-8"))  # noqa: E731
    runs = load(before), load(after)
    print(f"`{before}` → `{after}`, same questions, paired.\n")
    print(
        "| Suite | Answers | Correctness (mean) | Fully correct | Faithfulness v2 (mean) | Unsupported claims"
        " | False refusals | Complete evidence | Wall p50 / p95 ms |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for suite in runs[0]["suites"]:
        _suite(suite["suite"], runs)


def _suite(name: str, runs: tuple[dict, dict]) -> None:
    report_a, report_b = _report(runs[0], name), _report(runs[1], name)
    protocols = (
        report_a.get("judge_protocol") or "v1 (raw context)",
        report_b.get("judge_protocol") or "v1 (raw context)",
    )
    a = {d["id"]: d for d in report_a["details"]}
    b = {d["id"]: d for d in report_b["details"]}
    if set(a) != set(b):
        sys.exit(f"{name}: the runs do not cover the same questions")
    evidence_path = Path("benchmarks") / name / "evidence_v1.jsonl"
    evidence = load_evidence(evidence_path) if evidence_path.exists() else {}
    truth = {
        json.loads(line)["id"]: json.loads(line).get("expected_spans", [])
        for line in (Path("benchmarks") / name / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    groups = _groups(name) if name == "br_expat" else {}
    ca = {i: _case(a[i], evidence.get(i), truth.get(i, [])) for i in a}
    cb = {i: _case(b[i], evidence.get(i), truth.get(i, [])) for i in b}
    answered = [i for i in a if ca[i]["answered"] and cb[i]["answered"]]

    def mean(cases, key, ids):
        values = [cases[i][key] for i in ids if cases[i][key] is not None]
        return sum(values) / len(values) if values else float("nan")

    def paired(key, transform=lambda v: v):
        ids = [i for i in answered if ca[i][key] is not None and cb[i][key] is not None]
        diffs = {i: transform(cb[i][key]) - transform(ca[i][key]) for i in ids}
        low, high = _cluster_bootstrap(diffs, groups) if diffs else (0.0, 0.0)
        return f"[{low:+.3f} ; {high:+.3f}]"

    def binary(predicate):
        won = sum(1 for i in answered if predicate(cb[i]) and not predicate(ca[i]))
        lost = sum(1 for i in answered if predicate(ca[i]) and not predicate(cb[i]))
        return f"+{won} / −{lost} (p = {mcnemar_exact(won, lost):.2f})"

    fully = lambda c: c["correct"] == 1.0  # noqa: E731
    unsupported = lambda c: c["faithful"] is not None and c["faithful"] < 1.0  # noqa: E731
    wall_a = [ca[i]["wall_ms"] for i in answered]
    wall_b = [cb[i]["wall_ms"] for i in answered]
    evidence_cell = "—"
    if evidence:
        ids = [i for i in a if ca[i]["complete"] is not None]
        evidence_cell = (
            f"{sum(bool(ca[i]['complete']) for i in ids) / len(ids):.3f} → "
            f"{sum(bool(cb[i]['complete']) for i in ids) / len(ids):.3f} "
            f"{binary(lambda c: bool(c['complete']))}"
        )
    print(
        f"| {name} | {len(answered)} | {mean(ca, 'correct', answered):.3f} → {mean(cb, 'correct', answered):.3f}"
        f" {paired('correct')} | {sum(fully(ca[i]) for i in answered)} → {sum(fully(cb[i]) for i in answered)}"
        f" {binary(fully)} | {mean(ca, 'faithful', answered):.3f} → {mean(cb, 'faithful', answered):.3f}"
        f" {paired('faithful')} | {sum(unsupported(ca[i]) for i in answered)} → {sum(unsupported(cb[i]) for i in answered)}"
        f" | {sum(ca[i]['false_refusal'] for i in answered)} → {sum(cb[i]['false_refusal'] for i in answered)}"
        f" | {evidence_cell} | {statistics.median(wall_a):.0f} / {_p(wall_a, 0.95):.0f} →"
        f" {statistics.median(wall_b):.0f} / {_p(wall_b, 0.95):.0f} |"
    )
    dedup = [b[i].get("dedup_stats") or {} for i in b]
    dropped = sum(len(stats.get("dropped") or []) for stats in dedup)
    changed = sum(1 for stats in dedup if stats.get("dropped"))
    print(
        f"|   ↳ {name}: dedup dropped {dropped} passages in {changed} questions;"
        f" judge protocol {protocols[0]} → {protocols[1]} | | | | | | | | |"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
