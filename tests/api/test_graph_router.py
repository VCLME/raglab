from __future__ import annotations

from fastapi.testclient import TestClient


def _assert_not_implemented(response):
    assert response.status_code == 501
    body = response.json()
    assert "Endpoint scaffolded" in body["detail"]


def test_graph_index_returns_501(client: TestClient):
    _assert_not_implemented(client.post("/api/graph/index", json={}))


def test_graph_query_returns_501(client: TestClient):
    _assert_not_implemented(client.post("/api/graph/query", json={}))


def test_graph_runs_returns_501(client: TestClient):
    _assert_not_implemented(client.get("/api/graph/runs"))
