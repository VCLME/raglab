"""Ingesting the same folder from two locations keeps one document per file.

Needs a disposable PostgreSQL database with pgvector (migrated by the test):
set RAGLAB_TEST_DATABASE_URL, e.g.
postgresql+psycopg://raglab:raglab@localhost:5432/raglab_test. Everything is
written inside a transaction that is rolled back.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from raglab.db.migrate import upgrade_database
from raglab.db.models import Corpus, Document
from raglab.ingestion.service import IngestionService

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


def _folder(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


def _documents(session: Session, corpus_name: str) -> int:
    return session.scalar(select(func.count()).select_from(Document).join(Corpus).where(Corpus.name == corpus_name))


def test_same_files_from_another_checkout_are_not_duplicated(session, tmp_path):
    corpus = f"ingest-{uuid4()}"
    files = {"a.txt": "Premier document.", "b.txt": "Second document."}
    service = IngestionService(session)

    first = service.ingest_folder(_folder(tmp_path / "checkout-1", files), corpus_name=corpus)
    second = service.ingest_folder(_folder(tmp_path / "checkout-2", files), corpus_name=corpus)

    assert (first["ingested"], second["ingested"], second["updated"]) == (2, 0, 2)
    assert _documents(session, corpus) == 2


def test_a_changed_file_elsewhere_is_a_new_document(session, tmp_path):
    corpus = f"ingest-{uuid4()}"
    service = IngestionService(session)

    service.ingest_folder(_folder(tmp_path / "one", {"a.txt": "Version 1."}), corpus_name=corpus)
    service.ingest_folder(_folder(tmp_path / "two", {"a.txt": "Version 2."}), corpus_name=corpus)

    assert _documents(session, corpus) == 2
