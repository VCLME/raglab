"""The versions option against PostgreSQL metadata: the SQL validity filter,
the corpus check, the metadata lookup and the cited article of a date.

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

from raglab.db.migrate import upgrade_database
from raglab.db.models import Document
from raglab.retrieval.citations import Citation, find_code_article
from raglab.retrieval.versions import VersionLookup
from raglab.stores.vector.postgres import valid_at_condition

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
