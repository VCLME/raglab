from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from typer.testing import CliRunner

from drift_samples import fake_loader, results
from raglab.cli import app as cli_app
from raglab.observability.drift import (
    ResultSelection,
    build_drift_report,
    compare_results,
    ks_2samp,
    load_metrics,
    render_markdown,
)


def test_ks_statistic_matches_known_values():
    statistic, p_value = ks_2samp([1, 2, 3, 4], [1, 2, 3, 4])
    assert statistic == 0.0 and p_value == 1.0
    statistic, p_value = ks_2samp(list(range(50)), list(range(100, 150)))
    assert statistic == 1.0 and p_value < 1e-10
    statistic, _ = ks_2samp([0.1, 0.2, 0.3, 0.4, 0.5], [0.35, 0.45, 0.55, 0.65])
    assert statistic == pytest.approx(0.6)  # at x = 0.3: 3/5 vs 0/4
    # Reference values from scipy.stats.ks_2samp(a, b, method="asymp"), scipy 1.16.
    statistic, p_value = ks_2samp(np.linspace(0, 1, 40), np.linspace(0.2, 1.2, 30))
    assert statistic == pytest.approx(0.225)
    assert p_value == pytest.approx(0.3076, abs=0.01)
    statistic, p_value = ks_2samp(np.linspace(0, 1, 100), np.linspace(0.05, 1.05, 120))
    assert statistic == pytest.approx(0.05833, abs=1e-4)
    assert p_value == pytest.approx(0.9866, abs=0.01)


def test_planted_score_and_ragas_regression_is_flagged():
    rng = np.random.default_rng(7)
    baseline = results(rng, 200, top1_mean=0.82, faithfulness=0.85)
    # Degraded index: top-1 scores drop by 0.06 and the judge sees more
    # unfaithful answers.
    candidate = results(rng, 200, top1_mean=0.76, faithfulness=0.65)

    report = compare_results(baseline, candidate)

    top1 = report["distributions"]["top1_score"]
    assert top1["drift"] is True
    assert top1["p_value"] < 1e-6
    assert top1["median_delta"] == pytest.approx(-0.06, abs=0.015)
    assert report["means"]["faithfulness"]["regression"] is True
    assert report["drift_detected"] is True
    assert {"top1_score", "mean_topk_score", "faithfulness"} <= set(report["flagged"])


def test_same_distribution_is_not_flagged():
    rng = np.random.default_rng(11)
    baseline = results(rng, 200, top1_mean=0.82, faithfulness=0.85)
    candidate = results(rng, 200, top1_mean=0.82, faithfulness=0.85)

    report = compare_results(baseline, candidate)

    assert report["drift_detected"] is False, report["flagged"]
    assert report["distributions"]["top1_score"]["p_value"] > 0.05


def test_improvement_is_not_a_regression():
    rng = np.random.default_rng(3)
    report = compare_results(
        results(rng, 100, top1_mean=0.8, faithfulness=0.6),
        results(rng, 100, top1_mean=0.8, faithfulness=0.9),
    )
    assert report["means"]["faithfulness"]["delta"] > 0.2
    assert report["means"]["faithfulness"]["regression"] is False


def test_results_without_scores_still_compare_ranks_and_judges():
    legacy = [{"retrieval_reciprocal_rank": 0.5, "faithfulness": 1.0}] * 3
    report = compare_results(legacy, legacy, min_samples=10)
    assert report["distributions"]["top1_score"] == {
        "baseline_n": 0,
        "candidate_n": 0,
        "status": "insufficient",
        "drift": False,
    }
    assert report["means"]["mrr"]["baseline_mean"] == 0.5
    assert "echantillon insuffisant" in render_markdown(report)


def test_markdown_report_names_the_flagged_checks():
    rng = np.random.default_rng(7)
    report = compare_results(
        results(rng, 100, top1_mean=0.82, faithfulness=0.85),
        results(rng, 100, top1_mean=0.70, faithfulness=0.85),
    )
    text = render_markdown(report)
    assert "**Derive detectee**" in text
    assert "| Score top-1 |" in text


def test_load_metrics_filters_on_every_criterion():
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [{"recall@5": True}, None]
    since = datetime(2026, 10, 1, tzinfo=UTC)
    rows = load_metrics(session, ResultSelection(index_run_id="run-a", since=since))
    assert rows == [{"recall@5": True}, {}]
    sql = str(session.execute.call_args.args[0])
    assert "experiment_results.index_run_id" in sql and "experiment_results.created_at >=" in sql
    assert "experiment_run_id =" not in sql
    with pytest.raises(ValueError):
        load_metrics(session, ResultSelection())


def test_build_drift_report_describes_both_selections():
    with patch("raglab.observability.drift.load_metrics", side_effect=fake_loader()):
        report = build_drift_report(
            MagicMock(), ResultSelection(index_run_id="good"), ResultSelection(index_run_id="bad")
        )
    assert report["baseline"] == {"index_run_id": "good"}
    assert report["drift_detected"] is True


@contextmanager
def _fake_scope():
    yield MagicMock()


def test_drift_cli_json_output_and_exit_code():
    runner = CliRunner()
    with (
        patch("raglab.cli.session_scope", _fake_scope),
        patch("raglab.observability.drift.load_metrics", side_effect=fake_loader()),
    ):
        same = runner.invoke(
            cli_app,
            ["experiment", "drift", "--baseline-index-run", "good", "--candidate-index-run", "good", "--fail-on-drift"],
        )
        degraded = runner.invoke(
            cli_app,
            [
                "experiment",
                "drift",
                "--baseline-index-run",
                "good",
                "--candidate-index-run",
                "bad",
                "--format",
                "json",
                "--fail-on-drift",
            ],
        )
    assert same.exit_code == 0, same.output
    assert "Aucune derive." in same.output
    assert degraded.exit_code == 1
    assert json.loads(degraded.output)["drift_detected"] is True
