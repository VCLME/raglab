from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from raglab.stores.vector.postgres import PostgresVectorStore


def _index_run():
    return SimpleNamespace(id="run", embedding_space_id="space", embedding_space=SimpleNamespace(dimension=384))


def _statements(session: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in session.execute.call_args_list]


def _search(store: PostgresVectorStore, top_k: int) -> list[str]:
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    store.search(session, index_run=_index_run(), query_embedding=[0.0] * 384, top_k=top_k)
    return _statements(session)


def test_exact_mode_is_the_default_and_bypasses_the_hnsw_index():
    statements = _search(PostgresVectorStore(), 5)
    assert len(statements) == 1  # no hnsw SET LOCAL
    # The partial HNSW index is on `embedding::vector(384)`: exact mode must
    # not use that expression, so the planner cannot pick the index.
    assert "VECTOR(384)" not in statements[0].upper()
    assert "ORDER BY" in statements[0]


def test_hnsw_mode_enables_the_iterative_scan_before_the_knn_query():
    statements = _search(PostgresVectorStore(search_mode="hnsw"), 50)
    assert statements[0] == "SET LOCAL hnsw.iterative_scan = strict_order"
    assert statements[1] == "SET LOCAL hnsw.ef_search = 50"
    assert "VECTOR(384)" in statements[2].upper()


def test_hnsw_without_iterative_scan_reproduces_v0():
    statements = _search(PostgresVectorStore(search_mode="hnsw", iterative_scan=False), 5)
    assert not any("hnsw" in statement for statement in statements)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        PostgresVectorStore(search_mode="ivf")
