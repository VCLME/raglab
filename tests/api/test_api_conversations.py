"""Conversation history endpoints and the query's `conversation_id` without a
database: history off, unknown conversation, the ids returned to the client.
The database side is in tests/test_conversations_postgres.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from raglab.api.deps import get_current_settings, get_session_maker
from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import QueryResponse

CONVERSATION = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def make_client(make_client):
    """Routes read their settings through get_current_settings: hand them
    the app's own."""

    def _make(**overrides):
        client = make_client(**overrides)
        settings = Settings(**overrides)
        client.app.dependency_overrides[get_current_settings] = lambda: settings
        return client

    return _make


def _response() -> QueryResponse:
    return QueryResponse(
        question="Que dit la loi ?",
        index_run_id="11111111-1111-1111-1111-111111111111",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[],
        answer="Rien.",
    )


def test_config_says_whether_the_server_keeps_the_history(make_client):
    assert make_client().get("/api/config").json()["conversation_history"] is False
    on = make_client(conversation_history=True, conversation_retention_days=30).get("/api/config").json()
    assert (on["conversation_history"], on["conversation_retention_days"]) == (True, 30)


def test_history_endpoints_answer_404_when_the_history_is_off(make_client):
    client = make_client(conversation_history=False)
    for method, path in [
        ("get", "/api/conversations"),
        ("get", "/api/conversations/search?q=loi"),
        ("get", f"/api/conversations/{CONVERSATION}"),
        ("delete", f"/api/conversations/{CONVERSATION}"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 404, path
        assert response.json()["error"] == "ConversationHistoryDisabledError"


def test_query_ignores_the_conversation_when_the_history_is_off(make_client):
    client = make_client(conversation_history=False)
    with (
        patch("raglab.api.routers.query.QueryService") as service,
        patch("raglab.api.routers.query.TurnRecorder") as recorder,
    ):
        service.return_value.query.return_value = _response()
        body = client.post("/api/query", json={"question": "?", "conversation_id": CONVERSATION}).json()

    recorder.assert_not_called()
    assert body["conversation_id"] is None
    assert body["message_id"] is None


def test_query_into_an_unknown_conversation_is_a_404(make_client):
    client = make_client(conversation_history=True)
    with (
        patch("raglab.api.routers.query.ConversationStore") as store,
        patch("raglab.api.routers.query.QueryService") as service,
    ):
        store.return_value.exists.return_value = False
        response = client.post("/api/query", json={"question": "?", "conversation_id": CONVERSATION})

    assert response.status_code == 404
    assert response.json()["error"] == "ConversationNotFoundError"
    service.return_value.query.assert_not_called()


def test_query_returns_the_ids_the_turn_was_recorded_under(make_client):
    client = make_client(conversation_history=True)
    client.app.dependency_overrides[get_session_maker] = lambda: MagicMock
    with (
        patch("raglab.api.routers.query.ConversationStore") as store,
        patch("raglab.api.routers.query.QueryService") as service,
        patch("raglab.api.routers.query.TurnRecorder") as recorder,
    ):
        store.return_value.exists.return_value = True
        service.return_value.query.return_value = _response()
        recorder.return_value.conversation_id = CONVERSATION
        recorder.return_value.completed.return_value = "33333333-3333-3333-3333-333333333333"
        body = client.post(
            "/api/query",
            json={"question": "?", "corpus": "lexml", "top_k": 7, "conversation_id": CONVERSATION},
        ).json()

    assert body["conversation_id"] == CONVERSATION
    assert body["message_id"] == "33333333-3333-3333-3333-333333333333"
    kwargs = recorder.call_args.kwargs
    assert kwargs["corpus_name"] == "lexml"
    assert kwargs["requested"]["top_k"] == 7


def test_a_failed_query_is_recorded_as_failed(make_client):
    client = make_client(conversation_history=True)
    client.app.dependency_overrides[get_session_maker] = lambda: MagicMock
    with (
        patch("raglab.api.routers.query.ConversationStore") as store,
        patch("raglab.api.routers.query.QueryService") as service,
        patch("raglab.api.routers.query.TurnRecorder") as recorder,
    ):
        store.return_value.exists.return_value = True
        service.return_value.query.side_effect = ValueError("Aucun index pour ce corpus.")
        response = client.post("/api/query", json={"question": "?", "conversation_id": CONVERSATION})

    assert response.status_code == 400
    recorder.return_value.failed.assert_called_once_with("Aucun index pour ce corpus.")


def test_history_setting_without_a_runtime_switch_is_the_env_default(make_client):
    body = (
        make_client(conversation_history=True, conversation_retention_days=90)
        .get("/api/settings/conversation-history")
        .json()
    )
    assert body == {
        "enabled": True,
        "source": "env",
        "env_default": True,
        "retention_days": 90,
        "updated_at": None,
        "updated_by": None,
    }
