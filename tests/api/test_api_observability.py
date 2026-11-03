from __future__ import annotations

from prometheus_client import REGISTRY


def requests_total(route: str, status: str, method: str = "GET") -> float:
    labels = {"route": route, "method": method, "status": status}
    return REGISTRY.get_sample_value("raglab_http_requests_total", labels) or 0.0


def test_metrics_endpoint_serves_prometheus_text(client):
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    for name in (
        "raglab_http_requests_total",
        "raglab_stage_duration_seconds",
        "raglab_retrieval_top1_score",
        "raglab_cache_lookups_total",
        "raglab_abstentions_total",
        "raglab_generation_tokens_per_second",
    ):
        assert f"# TYPE {name}" in body


def test_requests_are_counted_by_route_template(client, mock_session):
    mock_session.get.return_value = None
    before = requests_total("/api/experiments/{run_id}", "404")
    assert client.get("/api/experiments/abc").status_code == 404
    assert client.get("/api/experiments/def").status_code == 404
    assert requests_total("/api/experiments/{run_id}", "404") == before + 2
    assert requests_total("/api/experiments/abc", "404") == 0.0


def test_unknown_paths_share_one_label(client):
    before = requests_total("unmatched", "404")
    client.get("/scanner/probe-1")
    client.get("/scanner/probe-2")
    assert requests_total("unmatched", "404") == before + 2


def test_metrics_scrapes_are_not_counted(client):
    client.get("/metrics")
    client.get("/metrics")
    assert requests_total("/metrics", "200") == 0.0


def test_rejected_requests_are_counted_and_metrics_stay_public(make_client):
    api = make_client(api_key="secret-key")
    before = requests_total("unmatched", "401")
    assert api.get("/api/corpora").status_code == 401
    assert requests_total("unmatched", "401") == before + 1
    assert api.get("/metrics").status_code == 200


def test_metrics_can_be_disabled(make_client):
    api = make_client(metrics_enabled=False)
    assert api.get("/metrics").status_code == 404
