"""BM25 computed in PostgreSQL, checked against hand-computed values.

Needs a disposable PostgreSQL database with pgvector (migrated by the test):
set RAGLAB_TEST_DATABASE_URL, e.g.
postgresql+psycopg://raglab:raglab@localhost:5432/raglab_test. Everything is
written inside a transaction that is rolled back.
"""

from __future__ import annotations

import math
import os
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from raglab.db.lexical import refresh_lexical_index
from raglab.db.migrate import upgrade_database
from raglab.domain.schemas import RetrievalFilters
from raglab.stores.lexical.postgres import PostgresLexicalStore

TEST_DATABASE_URL = os.environ.get("RAGLAB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="RAGLAB_TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.begin() as connection:
        upgrade_database(connection)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _seed(session: Session, *, corpus_language: str | None, documents: list[tuple[str, str | None]]) -> str:
    """Insert one corpus / index run with one chunk per (text, document language)."""
    corpus_id, space_id, run_id = str(uuid4()), str(uuid4()), str(uuid4())
    session.execute(
        text("INSERT INTO corpora (id, name, language) VALUES (:id, :name, :language)"),
        {"id": corpus_id, "name": f"bm25-{corpus_id}", "language": corpus_language},
    )
    session.execute(
        text(
            "INSERT INTO embedding_spaces (id, name, provider, model_name, dimension, distance_metric, "
            "query_prefix, passage_prefix, is_default) "
            "VALUES (:id, :name, 'test', 'test', 3, 'cosine', '', '', false)"
        ),
        {"id": space_id, "name": f"test:{space_id}"},
    )
    session.execute(
        text(
            "INSERT INTO index_runs (id, corpus_id, embedding_space_id, name, strategy, chunk_size, "
            "chunk_overlap, status, config_json) "
            "VALUES (:id, :corpus, :space, 'bm25', 'traditional', 100, 0, 'completed', '{}')"
        ),
        {"id": run_id, "corpus": corpus_id, "space": space_id},
    )
    for position, (chunk_text, language) in enumerate(documents, start=1):
        document_id = str(uuid4())
        metadata = f'{{"language": "{language}"}}' if language else "{}"
        session.execute(
            text(
                "INSERT INTO documents (id, corpus_id, source_path, file_name, extension, checksum, mime_type, "
                "content, char_count, metadata_json) "
                "VALUES (:id, :corpus, :path, :name, '.txt', 'x', 'text/plain', :content, :count, "
                "CAST(:metadata AS jsonb))"
            ),
            {
                "id": document_id,
                "corpus": corpus_id,
                "path": f"/d{position}.txt",
                "name": f"d{position}.txt",
                "content": chunk_text,
                "count": len(chunk_text),
                "metadata": metadata,
            },
        )
        session.execute(
            text(
                "INSERT INTO chunks (id, index_run_id, document_id, chunk_order, text, char_start, char_end, "
                "token_estimate, metadata_json) VALUES (:id, :run, :doc, 0, :text, 0, :end, 1, '{}')"
            ),
            {"id": str(uuid4()), "run": run_id, "doc": document_id, "text": chunk_text, "end": len(chunk_text)},
        )
    return run_id


def test_bm25_matches_hand_computed_scores(session):
    # "xx" is not a supported language: raglab_simple (no stemming, no
    # stopwords), so lexemes are the words themselves.
    run_id = _seed(
        session,
        corpus_language="xx",
        documents=[("chat noir chat", None), ("chien noir", None), ("oiseau bleu", None)],
    )
    stats = refresh_lexical_index(session, run_id, default_language="fr")
    assert stats == {"doc_count": 3, "avg_length": pytest.approx(7 / 3), "ts_configs": ["raglab_simple"]}
    doc_freq = dict(
        session.execute(
            text("SELECT lexeme, doc_freq FROM lexical_term_stats WHERE index_run_id = :run"), {"run": run_id}
        ).all()
    )
    assert doc_freq == {"chat": 1, "noir": 2, "chien": 1, "oiseau": 1, "bleu": 1}

    store = PostgresLexicalStore(k1=1.2, b=0.75)
    results, lexemes = store.search(session, index_run=SimpleNamespace(id=run_id), question="Chat NOIR ?", top_k=10)

    # N = 3, avgdl = 7/3, k1 = 1.2, b = 0.75
    # idf(chat) = ln(1 + (3 - 1 + 0.5) / (1 + 0.5)) = ln(8/3) ~ 0.980829
    # idf(noir) = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)) = ln(1.6) ~ 0.470004
    # d1 "chat noir chat": |d| = 3, K = 1.2 * (0.25 + 0.75 * 3 / (7/3)) = 1.457143
    #   chat: tf 2 -> 0.980829 * 2 * 2.2 / (2 + 1.457143) = 1.248328
    #   noir: tf 1 -> 0.470004 * 2.2 / (1 + 1.457143)     = 0.420817  => 1.669145
    # d2 "chien noir": |d| = 2, K = 1.2 * (0.25 + 0.75 * 2 / (7/3)) = 1.071429
    #   noir: tf 1 -> 0.470004 * 2.2 / (1 + 1.071429)     = 0.499176
    # d3 "oiseau bleu": no query term, not a candidate.
    assert lexemes == ["chat", "noir"]
    assert [chunk.file_name for chunk in results] == ["d1.txt", "d2.txt"]
    assert results[0].score == pytest.approx(1.669145, abs=1e-5)
    assert results[1].score == pytest.approx(0.499176, abs=1e-5)
    assert [chunk.lexical_rank for chunk in results] == [1, 2]
    assert results[0].lexical_score == results[0].score
    assert results[0].dense_rank is None

    # Same numbers from the closed form, to keep the comments honest.
    idf_chat, idf_noir = math.log(8 / 3), math.log(1.6)
    norm_d1 = 1.2 * (0.25 + 0.75 * 3 / (7 / 3))
    expected_d1 = idf_chat * 2 * 2.2 / (2 + norm_d1) + idf_noir * 2.2 / (1 + norm_d1)
    assert results[0].score == pytest.approx(expected_d1)


def test_bm25_or_semantics_filters_and_empty_queries(session):
    run_id = _seed(
        session,
        corpus_language="xx",
        documents=[("alpha beta", None), ("gamma", None), ("delta", None)],
    )
    refresh_lexical_index(session, run_id, default_language="fr")
    store = PostgresLexicalStore()
    run = SimpleNamespace(id=run_id)

    results, _ = store.search(session, index_run=run, question="alpha gamma zeta", top_k=10)
    assert sorted(chunk.file_name for chunk in results) == ["d1.txt", "d2.txt"]

    filtered, _ = store.search(
        session,
        index_run=run,
        question="alpha gamma",
        top_k=10,
        filters=RetrievalFilters(file_names=["d2.txt"]),
    )
    assert [chunk.file_name for chunk in filtered] == ["d2.txt"]

    nothing, lexemes = store.search(session, index_run=run, question="?!", top_k=10)
    assert (nothing, lexemes) == ([], [])


def test_rare_term_first_pass_returns_the_exact_top_k(session):
    # "lei" is in every chunk (a frequent term), "8.666" in two of them.
    documents = [(f"lei art {position}", None) for position in range(30)]
    documents += [("lei 8.666 licitacoes", None), ("lei lei 8.666", None)]
    run_id = _seed(session, corpus_language="xx", documents=documents)
    refresh_lexical_index(session, run_id, default_language="fr")
    run = SimpleNamespace(id=run_id)

    pruned = PostgresLexicalStore()
    exhaustive = PostgresLexicalStore()
    exhaustive.COMMON_TERM_FRACTION = 2.0  # every term selects candidates
    with patch.object(PostgresLexicalStore, "_score", wraps=PostgresLexicalStore._score) as scoring:
        fast, _ = pruned.search(session, index_run=run, question="lei 8.666", top_k=2)
    # One pass: the 2nd score beats the bound idf(lei) * (k1 + 1).
    assert scoring.call_count == 1
    assert scoring.call_args.kwargs["candidate_lexemes"] == ["8.666"]
    full, _ = exhaustive.search(session, index_run=run, question="lei 8.666", top_k=2)
    assert [(c.chunk_id, c.score) for c in fast] == [(c.chunk_id, pytest.approx(c.score)) for c in full]
    assert {c.file_name for c in fast} == {"d31.txt", "d32.txt"}

    # Asking for more chunks than the rare term can supply falls back to
    # the full OR query.
    with patch.object(PostgresLexicalStore, "_score", wraps=PostgresLexicalStore._score) as scoring:
        deep, _ = pruned.search(session, index_run=run, question="lei 8.666", top_k=10)
    assert scoring.call_count == 2
    assert len(deep) == 10


def test_text_search_config_follows_document_then_corpus_language(session):
    run_id = _seed(
        session,
        corpus_language="fr",
        documents=[("As legislações federais", "pt"), ("Les législations fédérales", None)],
    )
    stats = refresh_lexical_index(session, run_id, default_language="fr")
    assert sorted(stats["ts_configs"]) == ["raglab_french", "raglab_portuguese"]
    vectors = dict(
        session.execute(
            text(
                "SELECT d.file_name, c.lexical_tsv::text FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.index_run_id = :run"
            ),
            {"run": run_id},
        ).all()
    )
    # Portuguese stemmer and stopwords for d1 ("as" dropped), French for d2
    # ("les" kept: not in the French list); accents removed in both.
    assert vectors["d1.txt"] == "'feder':3 'legislaco':2"
    assert "'legisl':2" in vectors["d2.txt"] and "'federal':3" in vectors["d2.txt"]

    # The query is tokenised with both configs, so either form matches.
    results, lexemes = PostgresLexicalStore().search(
        session, index_run=SimpleNamespace(id=run_id), question="législation", top_k=10
    )
    assert "legisl" in lexemes
    assert {chunk.file_name for chunk in results} >= {"d2.txt"}
