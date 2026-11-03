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
