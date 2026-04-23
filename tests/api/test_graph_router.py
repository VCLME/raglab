from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


@patch("raglab.api.routers.graph.GraphIndexingService")
@patch("raglab.api.routers.graph.get_corpus_by_name")
def test_graph_index_delegates_to_service(get_corpus, service_cls, client: TestClient):
    get_corpus.return_value = MagicMock(id="corpus-1")
    service = MagicMock()
    service.index_corpus.return_value = {
        "index_run_id": "run-1",
        "documents": 3,
        "chunks": 42,
        "backend": "neo4j",
    }
    service_cls.return_value = service

    response = client.post(
        "/api/graph/index",
        json={
            "corpus": "piaf_fr",
            "strategy": "traditional",
            "run_name": None,
            "embedding_provider": None,
            "embedding_model": None,
            "incremental": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "index_run_id": "run-1",
        "documents": 3,
        "chunks": 42,
        "backend": "neo4j",
    }
    service.index_corpus.assert_called_once()


@patch("raglab.api.routers.graph.get_corpus_by_name")
def test_graph_index_404_when_corpus_missing(get_corpus, client: TestClient):
    get_corpus.return_value = None
    response = client.post(
        "/api/graph/index",
        json={"corpus": "ghost", "strategy": "traditional"},
    )
    assert response.status_code == 404
    assert "introuvable" in response.json()["detail"].lower()


@patch("raglab.api.routers.graph.GraphQueryService")
def test_graph_query_returns_response_shape(service_cls, client: TestClient):
    from raglab.domain.enums import ChunkingStrategy
    from raglab.domain.schemas import QueryResponse

    service = MagicMock()
    service.query.return_value = QueryResponse(
        question="test?",
        index_run_id="run-1",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[],
        filters=None,
        answer="hello",
        elapsed_ms=1.0,
    )
    service_cls.return_value = service

    response = client.post(
        "/api/graph/query",
        json={
            "question": "test?",
            "corpus": "piaf_fr",
            "strategy": None,
            "index_run_id": None,
            "top_k": None,
            "generate": True,
            "filters": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "hello"
    assert body["index_run_id"] == "run-1"


@patch("raglab.api.routers.graph.Neo4jGraphStore")
def test_graph_subgraph_forwards_chunk_ids(store_cls, client: TestClient):
    store = MagicMock()
    store.subgraph_for_chunks.return_value = {
        "chunks": [
            {
                "id": "c1",
                "chunk_order": 0,
                "preview": "hello",
                "document_id": "d1",
                "file_name": "f1.txt",
            }
        ],
        "documents": [{"id": "d1", "file_name": "f1.txt"}],
        "entities": [{"id": "paris|LOCATION", "name": "paris", "type": "LOCATION"}],
        "mentions": [{"chunk_id": "c1", "entity_id": "paris|LOCATION"}],
    }
    store_cls.return_value = store

    response = client.get("/api/graph/subgraph?chunk_ids=c1,c2")
    assert response.status_code == 200
    body = response.json()
    assert len(body["chunks"]) == 1
    assert body["entities"][0]["name"] == "paris"
    assert body["mentions"] == [{"chunk_id": "c1", "entity_id": "paris|LOCATION"}]
    store.subgraph_for_chunks.assert_called_once()
    kwargs = store.subgraph_for_chunks.call_args.kwargs
    assert kwargs["chunk_ids"] == ["c1", "c2"]


def test_graph_subgraph_empty_chunks_returns_empty_response(client: TestClient):
    response = client.get("/api/graph/subgraph?chunk_ids=")
    assert response.status_code == 200
    body = response.json()
    assert body == {"chunks": [], "documents": [], "entities": [], "mentions": []}


def test_graph_runs_returns_empty_list_when_no_graph_runs(
    client: TestClient, mock_session
):
    mock_session.execute.return_value.all.return_value = []
    response = client.get("/api/graph/runs")
    assert response.status_code == 200
    assert response.json() == []
