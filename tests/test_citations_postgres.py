"""The citation resolver's lookups against PostgreSQL metadata.

Needs a disposable PostgreSQL database with pgvector (migrated by the test):
set RAGLAB_TEST_DATABASE_URL, e.g.
postgresql+psycopg://raglab:raglab@localhost:5432/raglab_test. Everything is
written inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from raglab.db.migrate import upgrade_database
from raglab.retrieval.citations import Citation, document_chunks, find_code_article, find_law_document

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


def _seed(session: Session, documents: dict[str, tuple[dict, list[str]]]) -> tuple[SimpleNamespace, dict[str, str]]:
    """One corpus and index run; `documents` maps a name to (metadata, chunk texts)."""
    corpus_id, space_id, run_id = str(uuid4()), str(uuid4()), str(uuid4())
    session.execute(
        text("INSERT INTO corpora (id, name, language) VALUES (:id, :name, 'fr')"),
        {"id": corpus_id, "name": f"citations-{corpus_id}"},
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
            "VALUES (:id, :corpus, :space, 'citations', 'traditional', 100, 0, 'completed', '{}')"
        ),
        {"id": run_id, "corpus": corpus_id, "space": space_id},
    )
    ids: dict[str, str] = {}
    for name, (metadata, chunks) in documents.items():
        document_id = ids[name] = str(uuid4())
        content = "\n".join(chunks)
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
                "path": f"/{name}",
                "name": name,
                "content": content,
                "count": len(content),
                "metadata": json.dumps(metadata),
            },
        )
        for order, chunk in enumerate(chunks):
            session.execute(
                text(
                    "INSERT INTO chunks (id, index_run_id, document_id, chunk_order, text, char_start, char_end, "
                    "token_estimate, metadata_json) VALUES (:id, :run, :doc, :order, :text, 0, :end, 1, '{}')"
                ),
                {"id": str(uuid4()), "run": run_id, "doc": document_id, "order": order, "text": chunk, "end": 1},
            )
    return SimpleNamespace(id=run_id, corpus_id=corpus_id), ids


def _article(number: str, etat: str, start: str, code: str = "consommation") -> dict:
    return {"code": code, "article_number": number, "etat": etat, "date_debut": start}


def test_a_cited_article_resolves_to_its_version_in_force(session):
    run, ids = _seed(
        session,
        {
            "l221-18-v1.txt": (_article("L221-18", "MODIFIE", "2016-07-01"), ["ancien texte"]),
            "l221-18-v2.txt": (_article("L221-18", "VIGUEUR", "2022-05-28"), ["Article L221-18", "suite"]),
            "l121-21-old.txt": (_article("L121-21", "MODIFIE", "1993-07-27"), ["texte de 1993"]),
            "l121-21-last.txt": (_article("L121-21", "ABROGE", "2015-08-08"), ["texte de 2015"]),
            "lei_8078_1990.txt": ({"number": "8078", "year": 1990}, ["Art. 49. O consumidor pode desistir"]),
        },
    )

    found = find_code_article(session, run, Citation(None, "L221-18", code="consommation"))
    assert found is not None and (found.document_id, found.etat) == (ids["l221-18-v2.txt"], "VIGUEUR")
    # Without the code named, the article number alone is enough.
    assert find_code_article(session, run, Citation(None, "L221-18")).document_id == ids["l221-18-v2.txt"]
    # A repealed article resolves to its last version.
    assert find_code_article(session, run, Citation(None, "L121-21")).document_id == ids["l121-21-last.txt"]
    # Another code, or an article absent from the corpus: nothing.
    assert find_code_article(session, run, Citation(None, "L221-18", code="civil")) is None
    assert find_code_article(session, run, Citation(None, "L999-1")) is None

    pinned = document_chunks(session, run, ids["l221-18-v2.txt"])
    assert [chunk.chunk_text for chunk in pinned] == ["Article L221-18", "suite"]
    assert all(chunk.citation_match for chunk in pinned)

    # The Brazilian lookup is untouched by the French metadata.
    assert find_law_document(session, run, Citation("8078", "49")) == ids["lei_8078_1990.txt"]


def _unit(language: str, number: str, in_force: bool = True, valid_from: str = "2016-05-04") -> dict:
    return {
        "celex": "32016R0679",
        "unit": "article",
        "unit_number": number,
        "language": language,
        "in_force": in_force,
        "valid_from": valid_from,
    }


def test_an_eu_citation_resolves_to_the_unit_in_the_question_language(session):
    from raglab.retrieval.citations import find_eu_unit, has_eu_act

    run, ids = _seed(
        session,
        {
            "gdpr_en_art037_oj.txt": (_unit("en", "37", in_force=False), ["Article 37 old"]),
            "gdpr_en_art037_c.txt": (_unit("en", "37"), ["Article 37 corrected"]),
            "gdpr_fr_art037_oj.txt": (_unit("fr", "37"), ["Article 37 fr"]),
        },
    )
    citation = Citation(None, "37", celex="32016R0679", unit="article", language="fr")
    assert find_eu_unit(session, run, citation).document_id == ids["gdpr_fr_art037_oj.txt"]
    # No Portuguese copy: the version in force in another language.
    portuguese = Citation(None, "37", celex="32016R0679", unit="article", language="pt")
    assert find_eu_unit(session, run, portuguese).document_id == ids["gdpr_en_art037_c.txt"]
    assert find_eu_unit(session, run, Citation(None, "99", celex="32016R0679", unit="article")) is None
    assert has_eu_act(session, run, "32016R0679") and not has_eu_act(session, run, "32022R2554")
