from __future__ import annotations

from unittest.mock import patch

from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import QueryResponse, RetrievedChunk


def test_query_endpoint_returns_retrieved_chunks_and_answer(client):
    fake = QueryResponse(
        question="Que dit la loi ?",
        index_run_id="11111111-1111-1111-1111-111111111111",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                file_name="foo.txt",
                source_path="data/foo.txt",
                chunk_text="extrait",
                score=0.91,
                rank=1,
            )
        ],
        filters=None,
        answer="La loi dispose que…",
        elapsed_ms=123.4,
    )
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.return_value = fake
        response = client.post(
            "/api/query",
            json={
                "question": "Que dit la loi ?",
                "corpus": "lexml",
                "strategy": "traditional",
                "top_k": 3,
                "generate": True,
                "filters": {
                    "tags": ["legal"],
                    "metadata_equals": {"authority": "Senado Federal"},
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "La loi dispose que…"
    assert body["retrieved_chunks"][0]["file_name"] == "foo.txt"
    assert body["strategy"] == "traditional"
    assert body["elapsed_ms"] == 123.4
