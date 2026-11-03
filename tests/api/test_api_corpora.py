from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_delete_corpus_returns_counts_and_deletes(client, mock_session):
    fake_corpus = SimpleNamespace(id="corpus-1", name="demo")
    scalar_one_or_none = MagicMock(return_value=fake_corpus)

    # session.execute is called four times: SELECT corpus, COUNT docs, COUNT runs, COUNT chunks.
    responses = [
        SimpleNamespace(scalar_one_or_none=scalar_one_or_none),
        SimpleNamespace(scalar_one=MagicMock(return_value=12)),
        SimpleNamespace(scalar_one=MagicMock(return_value=3)),
        SimpleNamespace(scalar_one=MagicMock(return_value=42)),
    ]
    mock_session.execute.side_effect = responses

    response = client.delete("/api/corpora/demo")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "corpus": "demo",
        "documents_deleted": 12,
        "index_runs_deleted": 3,
        "chunks_deleted": 42,
    }
    mock_session.delete.assert_called_once_with(fake_corpus)
    mock_session.flush.assert_called_once()


def test_delete_corpus_returns_404_when_missing(client, mock_session):
    mock_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    response = client.delete("/api/corpora/unknown")
    assert response.status_code == 404
    assert "unknown" in response.json()["detail"]


def test_list_corpora_flags_legal_corpora(client, mock_session):
    legal = SimpleNamespace(id="c-legi", name="legi_consommation", description=None)
    plain = SimpleNamespace(id="c-piaf", name="piaf_fr", description="QA")
    corpora = SimpleNamespace(scalars=MagicMock(return_value=SimpleNamespace(all=lambda: [legal, plain])))

    def scalar(value):
        return SimpleNamespace(scalar_one=MagicMock(return_value=value))

    # Per corpus: COUNT docs, COUNT runs, EXISTS legal document.
    mock_session.execute.side_effect = [
        corpora,
        scalar(120),
        scalar(1),
        scalar(True),
        scalar(1522),
        scalar(2),
        scalar(False),
    ]

    response = client.get("/api/corpora")

    assert response.status_code == 200
    body = response.json()
    assert [c["features"] for c in body] == [{"legal_citations": True}, {"legal_citations": False}]
    assert body[0]["documents_count"] == 120


def test_legal_articles_query_checks_both_metadata_keys():
    from sqlalchemy.dialects import postgresql

    from raglab.api.routers.corpora import legal_articles_query

    sql = str(
        legal_articles_query("0f8c2b8e-6a1d-4b52-9c3e-1d2f3a4b5c6d").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "EXISTS" in sql
    assert "documents.metadata_json ? 'number'" in sql
    assert "documents.metadata_json ? 'article_number'" in sql
    assert "documents.corpus_id = '0f8c2b8e" in sql
