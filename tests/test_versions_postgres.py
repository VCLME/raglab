"""The versions option against PostgreSQL metadata: the SQL validity filter,
the corpus check, the metadata lookup, the cited article of a date and the
dense / BM25 searches that rank first and keep the versions in force.

Needs a disposable PostgreSQL database with pgvector (migrated by the test):
set RAGLAB_TEST_DATABASE_URL, e.g.
postgresql+psycopg://raglab:raglab@localhost:5432/raglab_test. Everything is
written inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import os
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

import raglab.stores.lexical.postgres as lexical_module
import raglab.stores.vector.postgres as vector_module
from raglab.db.lexical import refresh_lexical_index
from raglab.db.migrate import upgrade_database
from raglab.db.models import Document
from raglab.domain.schemas import RetrievalFilters
from raglab.retrieval.citations import Citation, find_code_article
from raglab.retrieval.versions import VersionLookup
from raglab.stores.lexical.postgres import PostgresLexicalStore
from raglab.stores.vector.postgres import PostgresVectorStore, valid_at_condition

TEST_DATABASE_URL = os.environ.get("RAGLAB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="RAGLAB_TEST_DATABASE_URL not set")


@pytest.fixture()
def session():
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.begin() as connection:
        upgrade_database(connection)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _corpus(session: Session, documents: dict[str, dict]) -> tuple[SimpleNamespace, dict[str, str]]:
    corpus_id = str(uuid4())
    session.execute(
        text("INSERT INTO corpora (id, name, language) VALUES (:id, :name, 'fr')"),
        {"id": corpus_id, "name": f"versions-{corpus_id}"},
    )
    ids: dict[str, str] = {}
    for name, metadata in documents.items():
        ids[name] = str(uuid4())
        session.execute(
            text(
                "INSERT INTO documents (id, corpus_id, source_path, file_name, extension, checksum, mime_type, "
                "content, char_count, metadata_json) "
                "VALUES (:id, :corpus, :path, :name, '.txt', 'x', 'text/plain', 'texte', 5, CAST(:metadata AS jsonb))"
            ),
            {"id": ids[name], "corpus": corpus_id, "path": f"/{name}", "name": name, "metadata": json.dumps(metadata)},
        )
    return SimpleNamespace(id=str(uuid4()), corpus_id=corpus_id), ids


def _version(number: str, etat: str, start: str, end: str | None) -> dict:
    return {"code": "consommation", "article_number": number, "etat": etat, "date_debut": start, "date_fin": end}


DOCUMENTS = {
    "l121-21-1993.txt": _version("L121-21", "MODIFIE", "1993-07-27", "2014-06-14"),
    "l121-21-2014.txt": _version("L121-21", "ABROGE", "2014-06-14", "2016-07-01"),
    "l121-21-2016.txt": _version("L121-21", "VIGUEUR", "2016-07-01", None),
    "l221-18.txt": _version("L221-18", "VIGUEUR", "2016-07-01", None),
    "annule.txt": _version("L999-1", "ANNULE", "2000-01-01", None),
    "upload.txt": {"tags": ["notes"]},
}


def _valid(session: Session, run: SimpleNamespace, day: str) -> set[str]:
    rows = session.execute(
        select(Document.file_name).where(Document.corpus_id == run.corpus_id, valid_at_condition(day))
    ).scalars()
    return set(rows)


def test_the_sql_filter_keeps_the_versions_of_the_day(session):
    run, _ = _corpus(session, DOCUMENTS)
    assert _valid(session, run, "2026-11-03") == {"l121-21-2016.txt", "l221-18.txt", "upload.txt"}
    assert _valid(session, run, "2015-12-31") == {"l121-21-2014.txt", "upload.txt"}
    assert _valid(session, run, "2010-01-01") == {"l121-21-1993.txt", "upload.txt"}
    # The end date is exclusive: on 1 July 2016 the new versions apply.
    assert _valid(session, run, "2016-07-01") == {"l121-21-2016.txt", "l221-18.txt", "upload.txt"}


def test_version_lookup_reads_the_corpus_and_the_documents(session):
    run, ids = _corpus(session, DOCUMENTS)
    lookup = VersionLookup(session)
    assert lookup.has_history(run)
    plain, _ = _corpus(session, {"piaf.txt": {"tags": ["piaf"]}})
    assert not lookup.has_history(plain)
    metadata = lookup.metadata([ids["l221-18.txt"], ids["upload.txt"]])
    assert metadata[ids["l221-18.txt"]]["etat"] == "VIGUEUR"
    assert metadata[ids["upload.txt"]] == {"tags": ["notes"]}


def test_a_cited_reused_number_resolves_to_the_version_of_the_date(session):
    run, ids = _corpus(session, DOCUMENTS)
    citation = Citation(None, "L121-21", code="consommation")
    assert find_code_article(session, run, citation).document_id == ids["l121-21-2016.txt"]
    assert find_code_article(session, run, citation, on=date(2015, 12, 31)).document_id == ids["l121-21-2014.txt"]
    assert find_code_article(session, run, citation, on=date(2000, 1, 1)).document_id == ids["l121-21-1993.txt"]


# Six repealed versions of L121-21 word for word closest to the question,
# then what is in force on 2026-11-03: the current version, L221-18 and an
# upload without version metadata. (name, metadata, text, embedding)
RANKED = [
    *[
        (f"l121-21-v{n}.txt", _version("L121-21", "ABROGE", f"199{n}-01-01", f"199{n + 1}-01-01"),
         "retractation retractation delai sept jours", [1.0, 0.0, 0.0])
        for n in range(6)
    ],
    ("l121-21-2016.txt", _version("L121-21", "VIGUEUR", "2016-07-01", None),
     "retractation delai quatorze jours", [0.9, 0.1, 0.0]),
    ("l221-18.txt", _version("L221-18", "VIGUEUR", "2016-07-01", None),
     "delai retractation contrat conclu a distance", [0.6, 0.4, 0.0]),
    ("upload.txt", {"tags": ["notes"]}, "notes sur le delai", [0.1, 0.9, 0.0]),
]  # fmt: skip
IN_FORCE_ORDER = ["l121-21-2016.txt", "l221-18.txt", "upload.txt"]


def _indexed(session: Session) -> SimpleNamespace:
    """A corpus of RANKED with one chunk, one 3-d embedding and the BM25 index per document."""
    corpus_id, space_id, run_id = str(uuid4()), str(uuid4()), str(uuid4())
    session.execute(
        text("INSERT INTO corpora (id, name, language) VALUES (:id, :name, 'xx')"),
        {"id": corpus_id, "name": f"ranked-{corpus_id}"},
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
            "VALUES (:id, :corpus, :space, 'ranked', 'traditional', 100, 0, 'completed', '{}')"
        ),
        {"id": run_id, "corpus": corpus_id, "space": space_id},
    )
    for name, metadata, chunk_text, embedding in RANKED:
        document_id, chunk_id = str(uuid4()), str(uuid4())
        session.execute(
            text(
                "INSERT INTO documents (id, corpus_id, source_path, file_name, extension, checksum, mime_type, "
                "content, char_count, metadata_json) VALUES (:id, :corpus, :path, :name, '.txt', 'x', "
                "'text/plain', :content, 1, CAST(:metadata AS jsonb))"
            ),
            {
                "id": document_id,
                "corpus": corpus_id,
                "path": f"/{name}",
                "name": name,
                "content": chunk_text,
                "metadata": json.dumps(metadata),
            },
        )
        session.execute(
            text(
                "INSERT INTO chunks (id, index_run_id, document_id, chunk_order, text, char_start, char_end, "
                "token_estimate, metadata_json) VALUES (:id, :run, :doc, 0, :text, 0, 1, 1, '{}')"
            ),
            {"id": chunk_id, "run": run_id, "doc": document_id, "text": chunk_text},
        )
        session.execute(
            text(
                "INSERT INTO chunk_embeddings (id, chunk_id, embedding_space_id, embedding) "
                "VALUES (:id, :chunk, :space, CAST(:embedding AS vector))"
            ),
            {"id": str(uuid4()), "chunk": chunk_id, "space": space_id, "embedding": str(embedding)},
        )
    refresh_lexical_index(session, run_id, default_language="fr")
    return SimpleNamespace(
        id=run_id,
        corpus_id=corpus_id,
        embedding_space_id=space_id,
        embedding_space=SimpleNamespace(dimension=3),
    )


def _searches(session: Session, run: SimpleNamespace, top_k: int, filters: RetrievalFilters | None):
    dense = PostgresVectorStore().search(
        session, index_run=run, query_embedding=[1.0, 0.0, 0.0], top_k=top_k, filters=filters
    )
    lexical, _ = PostgresLexicalStore().search(
        session, index_run=run, question="delai de retractation", top_k=top_k, filters=filters
    )
    return [chunk.file_name for chunk in dense], [chunk.file_name for chunk in lexical]


@pytest.mark.parametrize("depth", [8, 1], ids=["ranked-first", "too-shallow"])
@pytest.mark.parametrize("top_k", [2, 3, 5])
def test_searches_keep_the_versions_in_force_after_ranking(session, monkeypatch, depth, top_k):
    """The repealed versions rank first; whether the in-force rows come from
    the first ranked rows (depth 8), from the filtered query once too few
    survive (depth 1: two rows checked), or the run has fewer than top_k in
    force (top_k 5), the result is the filtered ranking."""
    monkeypatch.setattr(vector_module, "VALID_AT_DEPTH", depth)
    monkeypatch.setattr(lexical_module, "VALID_AT_DEPTH", depth)
    run = _indexed(session)
    dense, lexical = _searches(session, run, top_k, RetrievalFilters(valid_at="2026-11-03"))
    assert dense == IN_FORCE_ORDER[:top_k]
    assert lexical == IN_FORCE_ORDER[:top_k]
    # Without the filter the repealed versions come first.
    dense, lexical = _searches(session, run, top_k, None)
    assert dense[0].startswith("l121-21-v")
    assert lexical[0].startswith("l121-21-v")


def test_ranking_first_keeps_the_other_filters(session):
    run = _indexed(session)
    filters = RetrievalFilters(valid_at="2026-11-03", metadata_equals={"article_number": "L221-18"})
    assert _searches(session, run, 3, filters) == (["l221-18.txt"], ["l221-18.txt"])
    filters = RetrievalFilters(valid_at="1993-06-01", file_names=["l121-21-v3.txt", "l121-21-2016.txt"])
    assert _searches(session, run, 3, filters) == (["l121-21-v3.txt"], ["l121-21-v3.txt"])
