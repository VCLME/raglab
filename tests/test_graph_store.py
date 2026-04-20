from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from raglab.graph import Neo4jGraphStore


def test_ping_returns_false_when_connectivity_fails():
    fake_driver = MagicMock(name="Driver")
    fake_driver.verify_connectivity.side_effect = RuntimeError("boom")
    with patch("raglab.graph.neo4j.GraphDatabase.driver", return_value=fake_driver):
        store = Neo4jGraphStore(uri="bolt://nope:7687", user="x", password="y")
        try:
            assert store.ping() is False
        finally:
            store.close()


def test_ping_returns_true_when_connectivity_succeeds():
    fake_driver = MagicMock(name="Driver")
    fake_driver.verify_connectivity.return_value = None
    with patch("raglab.graph.neo4j.GraphDatabase.driver", return_value=fake_driver):
        store = Neo4jGraphStore(uri="bolt://ok:7687", user="x", password="y")
        try:
            assert store.ping() is True
        finally:
            store.close()


@pytest.mark.parametrize(
    "method, kwargs",
    [
        ("upsert_chunks", {"index_run": None, "chunks": [], "embeddings": []}),
        ("search", {"index_run": None, "query_embedding": [], "top_k": 5}),
        ("expand_neighbors", {"seed_chunk_ids": [], "hops": 1}),
    ],
)
def test_unimplemented_methods_raise(method, kwargs):
    with patch("raglab.graph.neo4j.GraphDatabase.driver", return_value=MagicMock()):
        store = Neo4jGraphStore()
        with pytest.raises(NotImplementedError, match="vector-in-graph"):
            getattr(store, method)(**kwargs)


def test_delete_index_run_raises():
    with patch("raglab.graph.neo4j.GraphDatabase.driver", return_value=MagicMock()):
        store = Neo4jGraphStore()
        with pytest.raises(NotImplementedError, match="vector-in-graph"):
            store.delete_index_run("some-id")
