from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from raglab.graph import Neo4jGraphStore


@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_ping_returns_false_when_connectivity_fails(driver_factory):
    fake_driver = MagicMock(name="Driver")
    fake_driver.verify_connectivity.side_effect = RuntimeError("boom")
    driver_factory.return_value = fake_driver
    store = Neo4jGraphStore(uri="bolt://nope:7687", user="x", password="y")
    try:
        assert store.ping() is False
    finally:
        store.close()


@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_ping_returns_true_when_connectivity_succeeds(driver_factory):
    fake_driver = MagicMock(name="Driver")
    fake_driver.verify_connectivity.return_value = None
    driver_factory.return_value = fake_driver
    store = Neo4jGraphStore(uri="bolt://ok:7687", user="x", password="y")
    try:
        assert store.ping() is True
    finally:
        store.close()


@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_expand_neighbors_not_implemented(driver_factory):
    driver_factory.return_value = MagicMock()
    store = Neo4jGraphStore()
    with pytest.raises(NotImplementedError, match="knowledge-graph"):
        store.expand_neighbors(seed_chunk_ids=["x"], hops=1)


@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_upsert_chunks_rejects_mismatched_lengths(driver_factory):
    driver_factory.return_value = MagicMock()
    store = Neo4jGraphStore()
    index_run = MagicMock()
    index_run.embedding_space.dimension = 3
    with pytest.raises(ValueError, match="align"):
        store.upsert_chunks(
            index_run=index_run,
            chunks=[MagicMock(document_id="d1")],
            documents={"d1": MagicMock(metadata_json={})},
            embeddings=[],
        )


@patch("raglab.graph.neo4j.ensure_vector_index")
@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_upsert_chunks_runs_merge_cypher(driver_factory, ensure_idx):
    fake_driver = MagicMock(name="Driver")
    fake_session = MagicMock(name="Session")
    fake_driver.session.return_value.__enter__.return_value = fake_session
    driver_factory.return_value = fake_driver

    chunk = MagicMock()
    chunk.id = "chunk-1"
    chunk.document_id = "doc-1"
    chunk.chunk_order = 0
    chunk.text = "Hello world"

    document = MagicMock()
    document.id = "doc-1"
    document.file_name = "hello.txt"
    document.source_path = "data/hello.txt"
    document.metadata_json = {"tags": ["a", "b"], "authority": "X"}

    index_run = MagicMock()
    index_run.id = "run-1"
    index_run.corpus_id = "corpus-1"
    index_run.strategy = "traditional"
    index_run.embedding_space.dimension = 3

    store = Neo4jGraphStore()
    store.upsert_chunks(
        index_run=index_run,
        chunks=[chunk],
        documents={"doc-1": document},
        embeddings=[[0.1, 0.2, 0.3]],
    )

    assert fake_session.run.call_count == 1
    cypher, params = fake_session.run.call_args[0]
    assert "MERGE (c:Chunk" in cypher
    assert "embedding_d3" in cypher
    assert params["run_id"] == "run-1"
    row = params["rows"][0]
    assert row["chunk_id"] == "chunk-1"
    assert row["tags"] == ["a", "b"]
    # Neo4j can't store nested maps; metadata is serialised as JSON.
    import json
    assert json.loads(row["metadata_json"]) == {"authority": "X"}


@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_hybrid_search_reranks_with_entity_overlap(driver_factory):
    fake_driver = MagicMock(name="Driver")
    fake_session = MagicMock(name="Session")
    fake_driver.session.return_value.__enter__.return_value = fake_session

    # Cypher returns 4 chunks ordered by vector score. Chunk c2 is a
    # weaker vector hit but shares entities with the top seed (c1), so
    # hybrid should bump it above c3 and c4.
    fake_session.run.return_value = iter(
        [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "file_name": "a.txt",
                "source_path": "a.txt",
                "chunk_text": "seed",
                "score": 0.92,
                "entity_keys": ["paris|LOCATION", "macron|PERSON"],
            },
            {
                "chunk_id": "c2",
                "document_id": "d2",
                "file_name": "b.txt",
                "source_path": "b.txt",
                "chunk_text": "shares entities with seed",
                "score": 0.70,
                "entity_keys": ["paris|LOCATION", "macron|PERSON"],
            },
            {
                "chunk_id": "c3",
                "document_id": "d3",
                "file_name": "c.txt",
                "source_path": "c.txt",
                "chunk_text": "closer but no entity overlap",
                "score": 0.80,
                "entity_keys": ["tokyo|LOCATION"],
            },
            {
                "chunk_id": "c4",
                "document_id": "d4",
                "file_name": "d.txt",
                "source_path": "d.txt",
                "chunk_text": "nothing",
                "score": 0.50,
                "entity_keys": [],
            },
        ]
    )
    driver_factory.return_value = fake_driver

    index_run = MagicMock()
    index_run.id = "run-1"
    index_run.embedding_space.dimension = 384

    from raglab.graph import Neo4jGraphStore

    store = Neo4jGraphStore()
    results = store.hybrid_search(
        index_run=index_run,
        query_embedding=[0.0] * 384,
        top_k=3,
        filters=None,
        seed_top_n=1,      # only c1 seeds entities
        entity_weight=0.5, # bridge weight = vector weight
    )

    assert [r.chunk_id for r in results] == ["c1", "c2", "c3"]
    assert results[0].rank == 1
    # c2 bridge = 1.0 (shares all seed entities) → 0.5*0.70 + 0.5*1.0 = 0.85
    # c3 bridge = 0.0 → 0.5*0.80 + 0 = 0.40
    # so c2 > c3 thanks to the re-rank
    assert results[1].chunk_id == "c2"
    assert results[1].score > results[2].score


def test_hybrid_search_rejects_invalid_weights():
    from raglab.graph import Neo4jGraphStore

    store = Neo4jGraphStore()
    index_run = MagicMock()
    index_run.embedding_space.dimension = 3

    with pytest.raises(ValueError, match="entity_weight"):
        store.hybrid_search(
            index_run=index_run, query_embedding=[0.0], top_k=1, entity_weight=1.5
        )
    with pytest.raises(ValueError, match="seed_top_n"):
        store.hybrid_search(
            index_run=index_run, query_embedding=[0.0], top_k=1, seed_top_n=0
        )


@patch("raglab.graph.neo4j.GraphDatabase.driver")
def test_search_builds_cypher_with_filters(driver_factory):
    fake_driver = MagicMock(name="Driver")
    fake_session = MagicMock(name="Session")
    fake_driver.session.return_value.__enter__.return_value = fake_session
    fake_session.run.return_value = iter(
        [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "file_name": "f.txt",
                "source_path": "data/f.txt",
                "chunk_text": "hello",
                "score": 0.92,
            }
        ]
    )
    driver_factory.return_value = fake_driver

    index_run = MagicMock()
    index_run.id = "run-1"
    index_run.embedding_space.dimension = 384

    from raglab.domain.schemas import RetrievalFilters

    filters = RetrievalFilters(file_names=["f.txt"])

    store = Neo4jGraphStore()
    results = store.search(
        index_run=index_run,
        query_embedding=[0.0] * 384,
        top_k=5,
        filters=filters,
    )

    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert results[0].rank == 1
    cypher, params = fake_session.run.call_args[0]
    assert "db.index.vector.queryNodes" in cypher
    assert "d.file_name IN $file_names" in cypher
    assert params["fetch_k"] == 25  # top_k * 5 because filters active
    assert params["top_k"] == 5
