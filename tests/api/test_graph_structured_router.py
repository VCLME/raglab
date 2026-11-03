from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from raglab.domain.errors import GraphUnavailableError


@patch("raglab.api.routers.graph.StructuredGraphService")
def test_build_returns_the_summary(service_cls, client: TestClient):
    service = service_cls.return_value
    service.build.return_value = {
        "index_run_id": "run-1",
        "corpus": "bench_lexml_pt",
        "profile": "laws",
        "duration_ms": 1234.5,
        "nodes": {"Article": 3984},
        "relationships": {"CITES->Article": 1100},
        "stats": {},
    }
    response = client.post("/api/graph/build", json={"corpus": "bench_lexml_pt", "profile": "laws"})
    assert response.status_code == 200
    assert response.json()["nodes"] == {"Article": 3984}
    service.build.assert_called_once_with(corpus_name="bench_lexml_pt", index_run_id=None, profile="laws")
    service.store.close.assert_called_once()


@patch("raglab.api.routers.graph.StructuredGraphService")
def test_build_without_neo4j_is_a_503(service_cls, client: TestClient):
    service_cls.return_value.build.side_effect = GraphUnavailableError("Neo4j inaccessible")
    response = client.post("/api/graph/build", json={"corpus": "bench_lexml_pt"})
    assert response.status_code == 503
    assert response.json()["error"] == "GraphUnavailableError"


def test_build_rejects_an_unknown_profile(client: TestClient):
    response = client.post("/api/graph/build", json={"corpus": "x", "profile": "contracts"})
    assert response.status_code == 422


@patch("raglab.api.routers.graph.StructuredGraphService")
def test_status_says_when_neo4j_is_off(service_cls, client: TestClient, mock_session: MagicMock):
    service = service_cls.return_value
    service.resolve_index_run.return_value = SimpleNamespace(id="run-1", corpus_id="c-1")
    service.store.ping.return_value = False
    mock_session.get.return_value = SimpleNamespace(name="bench_lexml_pt")
    response = client.get("/api/graph/status", params={"corpus": "bench_lexml_pt"})
    assert response.status_code == 200
    assert response.json() == {
        "index_run_id": "run-1",
        "corpus": "bench_lexml_pt",
        "available": False,
        "graph": None,
        "counts": {},
    }


@patch("raglab.api.routers.graph.StructuredGraphStore")
def test_neighbourhood_shape(store_cls, client: TestClient):
    store = store_cls.return_value.__enter__.return_value
    store.ping.return_value = True
    store.neighbourhood.return_value = {
        "nodes": [
            {"id": "law", "kind": "law", "label": "Lei nº 9.307/1996", "focus": True},
            {"id": "art", "kind": "article", "label": "Art. 2º — Lei nº 9.307/1996", "number": "2"},
        ],
        "edges": [{"source": "art", "target": "law", "type": "PART_OF"}],
        "isolated_articles": 4,
    }
    response = client.get("/api/graph/neighbourhood", params={"index_run_id": "run-1", "law": "law", "article": "2"})
    assert response.status_code == 200
    body = response.json()
    assert body["isolated_articles"] == 4 and body["edges"][0]["type"] == "PART_OF"
    store.neighbourhood.assert_called_once_with("run-1", law_uid="law", article="2")


@patch("raglab.api.routers.graph.StructuredGraphStore")
def test_laws_without_neo4j_is_a_503(store_cls, client: TestClient):
    store_cls.return_value.__enter__.return_value.ping.return_value = False
    response = client.get("/api/graph/laws", params={"index_run_id": "run-1"})
    assert response.status_code == 503


def test_config_exposes_the_entity_graph_flag(client: TestClient, monkeypatch):
    from raglab.config import get_settings

    assert client.get("/api/config").json()["entity_graph_enabled"] is False
    monkeypatch.setenv("RAGLAB_ENTITY_GRAPH_ENABLED", "true")
    get_settings.cache_clear()
    assert client.get("/api/config").json()["entity_graph_enabled"] is True
