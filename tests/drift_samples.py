"""Synthetic experiment results for the drift tests."""

from __future__ import annotations

import numpy as np


def results(
    rng: np.random.Generator,
    n: int,
    *,
    top1_mean: float,
    faithfulness: float,
    rr_hit_rate: float = 0.7,
) -> list[dict]:
    """`metrics_json` rows as `raglab experiment recall` stores them."""
    rows = []
    for _ in range(n):
        top1 = float(np.clip(rng.normal(top1_mean, 0.04), 0, 1))
        hit = rng.random() < rr_hit_rate
        rows.append(
            {
                "retrieved_scores": [top1, top1 - 0.02, top1 - 0.05, top1 - 0.06, top1 - 0.08],
                "reciprocal_rank": 1.0 if hit else 0.0,
                "recall@5": hit,
                "faithfulness": float(rng.random() < faithfulness),
            }
        )
    return rows


def fake_loader(rng_seed: int = 7):
    rng = np.random.default_rng(rng_seed)
    data = {
        "good": results(rng, 80, top1_mean=0.82, faithfulness=0.85),
        "bad": results(rng, 80, top1_mean=0.70, faithfulness=0.60),
    }
    return lambda _session, selection: data[selection.index_run_id]
