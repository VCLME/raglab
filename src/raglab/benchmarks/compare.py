"""Paired comparison of two benchmark runs on the same questions.

Two runs of `raglab bench all` answer exactly the same frozen questions, so
the right test compares them question by question rather than putting two
independent confidence intervals side by side:

* Recall@k is a hit / miss per question: McNemar's exact test on the
  discordant pairs (questions one run gets and the other misses);
* MRR is a per-question reciprocal rank: paired bootstrap of the mean
  difference.

A difference is called significant when the McNemar p-value is below 0.05
(recall) or when the 95% interval of the difference excludes 0 (MRR).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

CASE_FIELDS = ("recall@1", "recall@5", "recall@10", "reciprocal_rank")


def case_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Minimal per-question outcomes kept in `benchmarks/results/*.json`."""
    rows = []
    for detail in report["details"]:
        metrics = detail["metrics"]
        row: dict[str, Any] = {"id": detail["id"]}
        if detail.get("question_type"):
            row["type"] = detail["question_type"]
        if detail.get("split"):
            row["split"] = detail["split"]
        for field in CASE_FIELDS:
            if field in metrics:
                row[field] = float(metrics[field]) if field == "reciprocal_rank" else int(bool(metrics[field]))
        rows.append(row)
    return rows


def suite_cases(suite: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-question rows of a suite: stored inline, or rebuilt from the local
    detailed report for runs recorded before rows were stored."""
    if suite.get("cases"):
        return suite["cases"]
    report_path = Path(suite.get("report_path", ""))
    if report_path.is_file():
        return case_rows(json.loads(report_path.read_text(encoding="utf-8")))
    raise ValueError(f"Pas de resultats par question pour {suite['suite']} (ni inline, ni {report_path}).")


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_bootstrap(a: list[float], b: list[float], *, resamples: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% interval of mean(b - a), resampling questions with their pair."""
    rng = random.Random(seed)
    diffs = [y - x for x, y in zip(a, b, strict=True)]
    count = len(diffs)
    means = sorted(sum(diffs[rng.randrange(count)] for _ in range(count)) / count for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def compare_suite(cases_a: list[dict[str, Any]], cases_b: list[dict[str, Any]], *, k: int = 5) -> dict[str, Any]:
    by_id_b = {row["id"]: row for row in cases_b}
    pairs = [(row, by_id_b[row["id"]]) for row in cases_a if row["id"] in by_id_b]
    if not pairs:
        raise ValueError("Aucune question commune aux deux runs.")
    key = f"recall@{k}"
    only_a = sum(1 for x, y in pairs if x[key] and not y[key])
    only_b = sum(1 for x, y in pairs if y[key] and not x[key])
    recall_a = sum(x[key] for x, _ in pairs) / len(pairs)
    recall_b = sum(y[key] for _, y in pairs) / len(pairs)
    rr_a = [x["reciprocal_rank"] for x, _ in pairs]
    rr_b = [y["reciprocal_rank"] for _, y in pairs]
    mrr_low, mrr_high = paired_bootstrap(rr_a, rr_b)
    p_value = mcnemar_exact(only_a, only_b)
    return {
        "questions": len(pairs),
        key: {
            "a": round(recall_a, 4),
            "b": round(recall_b, 4),
            "delta": round(recall_b - recall_a, 4),
            "gained": only_b,
            "lost": only_a,
            "p_value": round(p_value, 4),
            "significant": p_value < 0.05,
        },
        "mrr": {
            "a": round(sum(rr_a) / len(rr_a), 4),
            "b": round(sum(rr_b) / len(rr_b), 4),
            "delta": round((sum(rr_b) - sum(rr_a)) / len(rr_a), 4),
            "ci95": [round(mrr_low, 4), round(mrr_high, 4)],
            "significant": mrr_low > 0 or mrr_high < 0,
        },
    }


def compare_runs(run_a: dict[str, Any], run_b: dict[str, Any], *, k: int = 5) -> dict[str, Any]:
    suites_b = {suite["suite"]: suite for suite in run_b["suites"]}
    result: dict[str, Any] = {"a": run_a["label"], "b": run_b["label"], "suites": {}}
    for suite_a in run_a["suites"]:
        suite_b = suites_b.get(suite_a["suite"])
        if suite_b is None:
            continue
        cases_a, cases_b = suite_cases(suite_a), suite_cases(suite_b)
        entry = compare_suite(cases_a, cases_b, k=k)
        types = sorted({row["type"] for row in cases_a if row.get("type")})
        if types:
            entry["by_type"] = {
                question_type: compare_suite(
                    [row for row in cases_a if row.get("type") == question_type],
                    [row for row in cases_b if row.get("type") == question_type],
                    k=k,
                )
                for question_type in types
            }
        splits = sorted({row["split"] for row in cases_a if row.get("split")})
        if splits:
            # Questions never looked at while tuning are reported apart.
            entry["by_split"] = {
                split: compare_suite(
                    [row for row in cases_a if row.get("split") == split],
                    [row for row in cases_b if row.get("split") == split],
                    k=k,
                )
                for split in splits
            }
        result["suites"][suite_a["suite"]] = entry
    return result


def render(comparison: dict[str, Any], *, k: int = 5) -> str:
    key = f"recall@{k}"
    lines = [
        f"### `{comparison['a']}` → `{comparison['b']}` (comparaison appariée)",
        "",
        f"| Jeu | Questions | Recall@{k} | Gagnées / perdues | p (McNemar) | MRR | IC 95 % de l'écart MRR |",
        "|---|---|---|---|---|---|---|",
    ]

    def line(name: str, entry: dict[str, Any]) -> str:
        r, m = entry[key], entry["mrr"]
        recall = f"{r['a']:.3f} → {r['b']:.3f} ({r['delta']:+.3f}){' ✱' if r['significant'] else ''}"
        mrr = f"{m['a']:.3f} → {m['b']:.3f} ({m['delta']:+.3f}){' ✱' if m['significant'] else ''}"
        ci = f"[{m['ci95'][0]:+.3f} ; {m['ci95'][1]:+.3f}]"
        return f"| {name} | {entry['questions']} | {recall} | +{r['gained']} / −{r['lost']} | {r['p_value']:.3f} | {mrr} | {ci} |"

    for suite_name, entry in comparison["suites"].items():
        lines.append(line(suite_name, entry))
        for question_type, sub in entry.get("by_type", {}).items():
            lines.append(line(f"{suite_name} · {question_type}", sub))
        for split, sub in entry.get("by_split", {}).items():
            lines.append(line(f"{suite_name} · {split}", sub))
    lines += ["", "✱ = écart significatif (p < 0,05 pour le recall, IC 95 % excluant 0 pour le MRR)."]
    return "\n".join(lines)
