from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from pgvector import Vector
from sqlalchemy.dialects import postgresql

from raglab.domain.schemas import RetrievalFilters
from raglab.stores.vector.postgres import PostgresVectorStore, QueryVector


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


@pytest.mark.parametrize("mode", ["exact", "hnsw"])
def test_search_does_not_load_document_content(mode):
    # documents.content is the full text of a law for LexML: loading it for
    # each of the 50 candidates of a hybrid query cost ~13 ms per query.
    filters = RetrievalFilters(file_names=["a.txt"], tags=["droit"], metadata_equals={"lang": "fr"})
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    PostgresVectorStore(search_mode=mode).search(
        session, index_run=_index_run(), query_embedding=[0.0] * 384, top_k=50, filters=filters
    )
    knn = _statements(session)[-1]
    selected = re.split(r"\sFROM\s", knn, maxsplit=1)[0]
    assert "documents.content" not in selected
    assert "documents.metadata_json" not in selected
    assert "documents.file_name" in selected
    assert "documents.metadata_json" in knn  # still used by the filters


def test_search_maps_selected_columns_to_ranked_results():
    row = SimpleNamespace(
        id="c1",
        text="Art. 1",
        char_start=0,
        char_end=6,
        document_id="d1",
        file_name="loi.txt",
        source_path="/corpus/loi.txt",
        distance=0.25,
    )
    session = MagicMock()
    session.execute.return_value.all.return_value = [row, SimpleNamespace(**{**vars(row), "id": "c2", "distance": 1.5})]
    results = PostgresVectorStore().search(session, index_run=_index_run(), query_embedding=[0.0] * 384, top_k=2)
    assert [(r.chunk_id, r.rank, r.score) for r in results] == [("c1", 1, 0.75), ("c2", 2, 0.0)]
    assert (results[0].document_id, results[0].file_name, results[0].source_path) == (
        "d1",
        "loi.txt",
        "/corpus/loi.txt",
    )
    assert (results[0].chunk_text, results[0].char_start, results[0].char_end) == ("Art. 1", 0, 6)


def test_query_vector_sends_the_same_float32_values_in_fewer_bytes():
    values = np.random.default_rng(0).uniform(-0.5, 0.5, 384).tolist()
    compact = QueryVector(384).bind_processor(postgresql.dialect())(values)
    reference = Vector._to_db(values)  # what pgvector's VECTOR sends
    # PostgreSQL stores float4: both texts parse to the same float32 values.
    assert np.array_equal(np.array(compact[1:-1].split(","), dtype=np.float32), Vector.from_text(reference).to_numpy())
    assert len(compact) < 0.65 * len(reference)
    with pytest.raises(ValueError):
        QueryVector(384).bind_processor(postgresql.dialect())([0.0] * 3)


def test_versions_filter_is_checked_after_the_exact_ranking():
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    PostgresVectorStore().search(
        session,
        index_run=_index_run(),
        query_embedding=[0.0] * 384,
        top_k=5,
        filters=RetrievalFilters(valid_at="2026-11-03"),
    )
    ranked, full = _statements(session)
    # Ranked first, documents checked on the ranked rows only; the filtered
    # query runs when too few rows pass (none here).
    assert "FROM (SELECT" in ranked
    assert ranked.index("metadata_json ->>") > ranked.index(") AS ranked")
    assert "FROM (SELECT" not in full and "metadata_json ->>" in full


# The distance expression, then the chunk id (SQLAlchemy renders the
# expression, not its `distance` label).
TIE_BREAK = r"ORDER BY .+ <=> :query_vec, chunks\.id\s+LIMIT"


def test_equal_distances_are_ordered_by_chunk_id():
    # Chunks with the same text share an embedding: without a second key
    # their order changed from run to run.
    assert re.search(TIE_BREAK, _search(PostgresVectorStore(), 5)[0])


def test_hnsw_orders_by_distance_only():
    # A second sort key makes PostgreSQL drop the HNSW index (measured:
    # parallel seq scan and sort instead of the index scan).
    knn = _search(PostgresVectorStore(search_mode="hnsw"), 5)[-1]
    assert "chunks.id" not in knn[knn.rindex("ORDER BY") :]


def test_versions_filter_keeps_the_chunk_id_tie_break():
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    PostgresVectorStore().search(
        session,
        index_run=_index_run(),
        query_embedding=[0.0] * 384,
        top_k=5,
        filters=RetrievalFilters(valid_at="2026-11-03"),
    )
    ranked, full = _statements(session)
    assert re.search(TIE_BREAK, ranked)  # inner ranking
    assert re.search(r"ORDER BY ranked\.distance, ranked\.id\s+LIMIT", ranked)
    assert re.search(TIE_BREAK, full)
