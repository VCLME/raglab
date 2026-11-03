from __future__ import annotations

import math

from raglab.benchmarks.compare import compare_suite, mcnemar_exact, paired_bootstrap, render


def _cases(hits: list[int], rr: list[float], types: list[str] | None = None) -> list[dict]:
    rows = []
    for index, (hit, rank) in enumerate(zip(hits, rr, strict=True)):
        row = {"id": f"q{index}", "recall@5": hit, "reciprocal_rank": rank}
        if types:
            row["type"] = types[index]
        rows.append(row)
    return rows


def test_mcnemar_exact_matches_the_binomial_tail():
    assert mcnemar_exact(0, 0) == 1.0
    assert math.isclose(mcnemar_exact(0, 6), 2 / 64)
    assert mcnemar_exact(5, 5) == 1.0


def test_paired_bootstrap_brackets_a_clear_gain():
    low, high = paired_bootstrap([0.0] * 50, [1.0] * 30 + [0.0] * 20)
    assert 0.4 < low < 0.6 < high < 0.75


def test_compare_counts_gains_and_losses_on_the_same_questions():
    before = _cases([0] * 40 + [1] * 60, [0.0] * 40 + [1.0] * 60)
    after = _cases([1] * 30 + [0] * 10 + [1] * 58 + [0] * 2, [0.5] * 30 + [0.0] * 10 + [1.0] * 58 + [0.0] * 2)
    entry = compare_suite(before, after)
    recall = entry["recall@5"]
    assert (recall["gained"], recall["lost"]) == (30, 2)
    assert recall["delta"] == 0.28 and recall["significant"]
    assert entry["mrr"]["significant"]


def test_noise_is_not_called_significant():
    before = _cases([1, 0] * 50, [1.0, 0.0] * 50)
    after = _cases([0, 1] * 2 + [1, 0] * 48, [0.0, 1.0] * 2 + [1.0, 0.0] * 48)
    entry = compare_suite(before, after)
    assert not entry["recall@5"]["significant"]
    assert not entry["mrr"]["significant"]


def test_render_marks_significant_rows():
    before = _cases([0] * 40, [0.0] * 40)
    after = _cases([1] * 40, [1.0] * 40)
    text = render({"a": "v1", "b": "hybrid", "suites": {"lexml_fulltext": compare_suite(before, after)}})
    assert "`v1` → `hybrid`" in text
    assert "0.000 → 1.000 (+1.000) ✱" in text
