"""Drift report between two sets of stored experiment results.

A set is selected by index run, experiment run and/or a `created_at` window
(criteria combine with AND), so the report answers both "did re-indexing
change retrieval?" (two index runs) and "did last week's runs degrade?" (two
time windows).

Two kinds of checks:

- distributions (top-1 score, mean top-k score, reciprocal rank): two-sample
  Kolmogorov-Smirnov test, flagged when the p-value falls under `alpha`;
- means (RAGAS judges, MRR, recall@k): delta candidate - baseline, flagged as
  a regression when it drops by at least `mean_threshold`.

Scores come from `metrics_json["retrieved_scores"]`, stored since phase 9.6;
older results only feed the rank and RAGAS checks.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.db.models import ExperimentResult

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
RAGAS_METRICS = ("faithfulness", "answer_relevancy", "answer_correctness")


@dataclass(frozen=True)
class ResultSelection:
    index_run_id: str | None = None
    experiment_run_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None

    def is_empty(self) -> bool:
        return not (self.index_run_id or self.experiment_run_id or self.since or self.until)

    def describe(self) -> dict[str, str]:
        described = {
            "index_run_id": self.index_run_id,
            "experiment_run_id": self.experiment_run_id,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
        }
        return {key: value for key, value in described.items() if value}


def load_metrics(session: Session, selection: ResultSelection) -> list[dict[str, Any]]:
    """`metrics_json` of every experiment result matching the selection."""
    if selection.is_empty():
        raise ValueError("Selection vide : indiquez un index run, un experiment run ou une fenetre de dates.")
    stmt = select(ExperimentResult.metrics_json)
    if selection.index_run_id:
        stmt = stmt.where(ExperimentResult.index_run_id == selection.index_run_id)
    if selection.experiment_run_id:
        stmt = stmt.where(ExperimentResult.experiment_run_id == selection.experiment_run_id)
    if selection.since:
        stmt = stmt.where(ExperimentResult.created_at >= selection.since)
    if selection.until:
        stmt = stmt.where(ExperimentResult.created_at < selection.until)
    return [dict(row or {}) for row in session.execute(stmt).scalars().all()]


def ks_2samp(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov statistic and asymptotic p-value.

    Same statistic as `scipy.stats.ks_2samp`; the p-value uses the
    Kolmogorov distribution with Stephens' small-sample correction, which
    is close to scipy's `method="asymp"` and avoids a scipy dependency.
    """
    x = np.sort(np.asarray(a, dtype=float))
    y = np.sort(np.asarray(b, dtype=float))
    n, m = len(x), len(y)
    if n == 0 or m == 0:
        raise ValueError("ks_2samp a besoin de deux echantillons non vides.")
    values = np.concatenate([x, y])
    cdf_x = np.searchsorted(x, values, side="right") / n
    cdf_y = np.searchsorted(y, values, side="right") / m
    statistic = float(np.max(np.abs(cdf_x - cdf_y)))
    effective_n = math.sqrt(n * m / (n + m))
    lam = (effective_n + 0.12 + 0.11 / effective_n) * statistic
    if lam < 1e-3:
        return statistic, 1.0
    p_value = 2.0 * sum((-1) ** (j - 1) * math.exp(-2.0 * j * j * lam * lam) for j in range(1, 101))
    return statistic, min(max(p_value, 0.0), 1.0)


def _top1(metrics: dict[str, Any]) -> float | None:
    scores = metrics.get("retrieved_scores") or []
    return float(scores[0]) if scores else None


def _mean_topk(metrics: dict[str, Any]) -> float | None:
    scores = metrics.get("retrieved_scores") or []
    return float(sum(scores) / len(scores)) if scores else None


def _reciprocal_rank(metrics: dict[str, Any]) -> float | None:
    # `raglab experiment recall` and `raglab experiment run` name it differently.
    value = metrics.get("reciprocal_rank", metrics.get("retrieval_reciprocal_rank"))
    return float(value) if isinstance(value, int | float) else None


def _key(name: str) -> Callable[[dict[str, Any]], float | None]:
    def extract(metrics: dict[str, Any]) -> float | None:
        value = metrics.get(name)
        # bool is an int subclass: recall@k hits become 0/1.
        return float(value) if isinstance(value, int | float) else None

    return extract


DISTRIBUTIONS: dict[str, Callable[[dict[str, Any]], float | None]] = {
    "top1_score": _top1,
    "mean_topk_score": _mean_topk,
    "reciprocal_rank": _reciprocal_rank,
}
MEANS: dict[str, Callable[[dict[str, Any]], float | None]] = {
    **{metric: _key(metric) for metric in RAGAS_METRICS},
    "mrr": _reciprocal_rank,
    "recall@5": _key("recall@5"),
    "recall@10": _key("recall@10"),
}


def _values(results: list[dict[str, Any]], extract: Callable[[dict[str, Any]], float | None]) -> list[float]:
    return [v for v in (extract(m) for m in results) if v is not None and math.isfinite(v)]


def _quantiles(values: list[float]) -> dict[str, float]:
    points = np.quantile(np.asarray(values, dtype=float), QUANTILES)
    return {f"p{round(q * 100)}": round(float(p), 4) for q, p in zip(QUANTILES, points, strict=True)}


def compare_results(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    *,
    alpha: float = 0.05,
    mean_threshold: float = 0.05,
    min_samples: int = 10,
) -> dict[str, Any]:
    """Compare two lists of `metrics_json` and flag the drifts."""
    distributions: dict[str, Any] = {}
    for name, extract in DISTRIBUTIONS.items():
        a, b = _values(baseline, extract), _values(candidate, extract)
        entry: dict[str, Any] = {"baseline_n": len(a), "candidate_n": len(b)}
        if len(a) < min_samples or len(b) < min_samples:
            entry.update(status="insufficient", drift=False)
        else:
            statistic, p_value = ks_2samp(a, b)
            median_delta = float(np.median(b) - np.median(a))
            entry.update(
                status="ok",
                baseline_quantiles=_quantiles(a),
                candidate_quantiles=_quantiles(b),
                median_delta=round(median_delta, 4),
                ks_statistic=round(statistic, 4),
                p_value=float(f"{p_value:.4g}"),
                drift=p_value < alpha,
            )
        distributions[name] = entry

    means: dict[str, Any] = {}
    for name, extract in MEANS.items():
        a, b = _values(baseline, extract), _values(candidate, extract)
        if not a or not b:
            continue
        baseline_mean, candidate_mean = sum(a) / len(a), sum(b) / len(b)
        delta = candidate_mean - baseline_mean
        means[name] = {
            "baseline_n": len(a),
            "candidate_n": len(b),
            "baseline_mean": round(baseline_mean, 4),
            "candidate_mean": round(candidate_mean, 4),
            "delta": round(delta, 4),
            "regression": delta <= -mean_threshold,
        }

    flagged = [name for name, entry in distributions.items() if entry["drift"]]
    flagged += [name for name, entry in means.items() if entry["regression"]]
    return {
        "baseline_results": len(baseline),
        "candidate_results": len(candidate),
        "alpha": alpha,
        "mean_threshold": mean_threshold,
        "min_samples": min_samples,
        "distributions": distributions,
        "means": means,
        "flagged": flagged,
        "drift_detected": bool(flagged),
    }


def build_drift_report(
    session: Session,
    baseline: ResultSelection,
    candidate: ResultSelection,
    **options: Any,
) -> dict[str, Any]:
    report = compare_results(load_metrics(session, baseline), load_metrics(session, candidate), **options)
    return {"baseline": baseline.describe(), "candidate": candidate.describe(), **report}


_DISTRIBUTION_LABELS = {
    "top1_score": "Score top-1",
    "mean_topk_score": "Score moyen top-k",
    "reciprocal_rank": "Rang reciproque",
}


def render_markdown(report: dict[str, Any]) -> str:
    def selection(described: dict[str, str]) -> str:
        return ", ".join(f"`{k}={v}`" for k, v in described.items()) or "(non precisee)"

    verdict = "**Derive detectee** : " + ", ".join(report["flagged"]) if report["drift_detected"] else "Aucune derive."
    lines = [
        "# Rapport de derive",
        "",
        f"- Reference : {selection(report.get('baseline', {}))} ({report['baseline_results']} resultats)",
        f"- Candidat : {selection(report.get('candidate', {}))} ({report['candidate_results']} resultats)",
        f"- Seuils : KS p < {report['alpha']}, regression de moyenne >= {report['mean_threshold']}",
        "",
        verdict,
        "",
        "## Distributions (test de Kolmogorov-Smirnov)",
        "",
        "| mesure | n ref | n cand | p50 ref | p50 cand | p10 ref | p10 cand | D | p-value | derive |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, entry in report["distributions"].items():
        label = _DISTRIBUTION_LABELS.get(name, name)
        if entry["status"] != "ok":
            lines.append(
                f"| {label} | {entry['baseline_n']} | {entry['candidate_n']} | - | - | - | - | - | - | "
                f"echantillon insuffisant (< {report['min_samples']}) |"
            )
            continue
        ref, cand = entry["baseline_quantiles"], entry["candidate_quantiles"]
        lines.append(
            f"| {label} | {entry['baseline_n']} | {entry['candidate_n']} | {ref['p50']:.3f} | {cand['p50']:.3f} | "
            f"{ref['p10']:.3f} | {cand['p10']:.3f} | {entry['ks_statistic']:.3f} | {entry['p_value']:.2g} | "
            f"{'**oui**' if entry['drift'] else 'non'} |"
        )
    lines += ["", "## Moyennes", ""]
    if not report["means"]:
        lines.append("Aucune metrique commune aux deux ensembles.")
    else:
        lines += [
            "| metrique | n ref | n cand | ref | cand | delta | regression |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for name, entry in report["means"].items():
            lines.append(
                f"| {name} | {entry['baseline_n']} | {entry['candidate_n']} | {entry['baseline_mean']:.3f} | "
                f"{entry['candidate_mean']:.3f} | {entry['delta']:+.3f} | {'**oui**' if entry['regression'] else 'non'} |"
            )
    return "\n".join(lines) + "\n"
