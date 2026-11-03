from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from raglab.benchmarks.gate import evaluate, failed, render
from raglab.cli import app

THRESHOLDS = {"piaf": {"recall@5": 0.85, "faithfulness_mean": 0.8}, "lexml_fulltext": {"recall@5": 0.5}}


def _result(piaf_recall: float, faithfulness: float | None) -> dict:
    piaf_summary = {"recall@5": piaf_recall}
    if faithfulness is not None:
        piaf_summary["faithfulness_mean"] = faithfulness
    return {
        "label": "run",
        "suites": [
            {"suite": "piaf", "summary": piaf_summary},
            {"suite": "lexml_fulltext", "summary": {"recall@5": 0.6}},
        ],
    }


def test_gate_passes_when_every_metric_is_at_or_above_its_floor():
    checks = evaluate(_result(0.85, 0.9), THRESHOLDS)
    assert [c.status for c in checks] == ["pass", "pass", "pass"]
    assert not failed(checks)


def test_gate_fails_on_a_regression():
    checks = evaluate(_result(0.80, 0.9), THRESHOLDS)
    assert failed(checks)
    assert "❌ sous le seuil" in render(checks, label="run")


def test_unmeasured_metrics_are_reported_and_only_fail_when_required():
    checks = evaluate(_result(0.9, None), THRESHOLDS)
    assert any(c.status == "not_measured" for c in checks)
    assert not failed(checks)
    assert failed(checks, require_all=True)


def test_cli_exit_code_and_summary_file(tmp_path: Path):
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"suites": THRESHOLDS}), encoding="utf-8")
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(_result(0.9, 0.9)), encoding="utf-8")
    bad.write_text(json.dumps(_result(0.7, 0.9)), encoding="utf-8")
    summary = tmp_path / "summary.md"
    runner = CliRunner()

    ok = runner.invoke(
        app, ["gate", "--results", str(good), "--thresholds", str(thresholds), "--summary-file", str(summary)]
    )
    ko = runner.invoke(app, ["gate", "--results", str(bad), "--thresholds", str(thresholds)])

    assert ok.exit_code == 0, ok.output
    assert ko.exit_code == 1
    assert "Porte de qualité" in summary.read_text(encoding="utf-8")
