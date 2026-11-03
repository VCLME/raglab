from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from raglab.stores.vector.postgres import PostgresVectorStore


def _index_run():
    return SimpleNamespace(id="run", embedding_space_id="space", embedding_space=SimpleNamespace(dimension=384))


def _statements(session: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in session.execute.call_args_list]


def test_iterative_scan_is_enabled_before_the_knn_query():
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    PostgresVectorStore().search(session, index_run=_index_run(), query_embedding=[0.0] * 384, top_k=50)
    statements = _statements(session)
    assert statements[0] == "SET LOCAL hnsw.iterative_scan = strict_order"
    assert statements[1] == "SET LOCAL hnsw.ef_search = 50"
    assert "ORDER BY" in statements[2]


def test_iterative_scan_can_be_disabled_to_reproduce_v0():
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    PostgresVectorStore(iterative_scan=False).search(session, index_run=_index_run(), query_embedding=[0.0] * 384, top_k=5)
    assert not any("hnsw" in statement for statement in _statements(session))
