from __future__ import annotations

from unittest.mock import patch

from drift_samples import fake_loader


def test_drift_api_endpoint(client):
    with patch("raglab.observability.drift.load_metrics", side_effect=fake_loader()):
        response = client.post(
            "/api/experiments/drift",
            json={"baseline": {"index_run_id": "good"}, "candidate": {"index_run_id": "bad"}},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["drift_detected"] is True
    assert body["markdown"].startswith("# Rapport de derive")


def test_drift_api_rejects_an_empty_selection(client):
    response = client.post("/api/experiments/drift", json={"baseline": {}, "candidate": {"index_run_id": "x"}})
    assert response.status_code == 422
