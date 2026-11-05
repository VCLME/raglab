"""Conversation history against PostgreSQL: the store (positions, titles,
filters, language-aware full-text search, rename, delete, retention), the
API turns appended by /api/query and /api/query/stream, and the CLI.

Needs a disposable PostgreSQL database with pgvector (migrated by the test):
set RAGLAB_TEST_DATABASE_URL, e.g.
postgresql+psycopg://raglab:raglab@localhost:5432/raglab_test. Everything is
written inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from raglab.api.deps import get_current_settings, get_db, get_session_maker
from raglab.api.main import create_app
from raglab.config import Settings
from raglab.conversations import ConversationNotFoundError, ConversationStore, TurnRecord
from raglab.db.migrate import upgrade_database
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import QueryResponse, RetrievedChunk
from raglab.retrieval.service import QueryService, RetrievalOutcome

TEST_DATABASE_URL = os.environ.get("RAGLAB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="RAGLAB_TEST_DATABASE_URL not set")


@pytest.fixture()
def connection():
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.begin() as setup:
        upgrade_database(setup)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def _sessions(connection):
    """Sessions sharing the test transaction; their commits are savepoints."""
    return lambda: Session(bind=connection, join_transaction_mode="create_savepoint")


@pytest.fixture()
def session(connection):
    session = _sessions(connection)()
    yield session
    session.close()


@pytest.fixture()
def settings() -> Settings:
    return Settings(conversation_history=True)


@pytest.fixture()
def store(session, settings) -> ConversationStore:
    return ConversationStore(session, settings)


def _turn(question: str, answer: str, language: str = "fr", **extra) -> TurnRecord:
    return TurnRecord(question=question, answer=answer, language=language, **extra)


# -- store -------------------------------------------------------------------


def test_append_numbers_turns_and_titles_the_conversation(store):
    conversation = store.create(corpus_name="constitution", channel="ui")
    first = store.append(conversation.id, _turn("Quelle est la durée du mandat présidentiel ?", "Cinq ans [Rank 1]."))
    second = store.append(conversation.id, _turn("Et le Sénat ?", "Six ans."))

    loaded = store.get(conversation.id)
    assert [message.position for message in loaded.messages] == [0, 1]
    assert [message.id for message in loaded.messages] == [first.id, second.id]
    assert loaded.title == "Quelle est la durée du mandat présidentiel ?"
    assert loaded.messages[0].ts_config == "raglab_french"


def test_client_ids_are_kept_and_never_duplicated(store):
    conversation_id = str(uuid4())
    created = store.create(conversation_id=conversation_id, channel="ui")
    again = store.create(conversation_id=conversation_id, title="autre")
    assert created.id == again.id == conversation_id

    message_id = str(uuid4())
    kept = store.append(conversation_id, _turn("Q1", "R1"), message_id=message_id)
    # The same id twice (a retried request) gets a fresh one, not an error.
    retried = store.append(conversation_id, _turn("Q2", "R2"), message_id=message_id)
    assert kept.id == message_id
    assert retried.id != message_id

    with pytest.raises(ValueError):
        store.create(conversation_id="pas-un-uuid")


def test_search_is_language_aware_and_accent_insensitive(store):
    french = store.create(corpus_name="constitution")
    store.append(
        french.id, _turn("Quelle est la durée du mandat présidentiel ?", "Le Président est élu pour cinq ans.")
    )
    portuguese = store.create(corpus_name="lexml")
    store.append(portuguese.id, _turn("Qual é o prazo de arrependimento?", "Sete dias.", language="pt"))

    def found(query: str, **filters) -> list[str]:
        return [hit.conversation_id for hit in store.search(query, **filters)]

    # French stemming ("durées" -> "dur") and no accent needed.
    assert found("durees") == [french.id]
    assert found("presidents elue") == [french.id]
    # Portuguese stemming.
    assert found("arrependimentos") == [portuguese.id]
    assert found('"élu pour cinq"') == [french.id]
    assert found("mandat -cinq") == []
    assert found("le") == []
    assert found("prazo", corpus="constitution") == []

    hit = store.search("président")[0]
    assert "⟦" in hit.snippet and "⟧" in hit.snippet
    assert hit.position == 0


def test_list_filters_by_corpus_and_dates(store, session):
    old = store.create(corpus_name="lexml")
    recent = store.create(corpus_name="constitution")
    session.execute(
        text("UPDATE conversations SET created_at = :at, updated_at = :at WHERE id = :id"),
        {"at": datetime(2026, 1, 10, tzinfo=UTC), "id": old.id},
    )
    session.expire_all()

    ids = {row.conversation.id for row in store.list_conversations()}
    assert {old.id, recent.id} <= ids
    assert [
        row.conversation.id for row in store.list_conversations(corpus="lexml") if row.conversation.id == old.id
    ] == [old.id]
    assert old.id not in {row.conversation.id for row in store.list_conversations(since=date(2026, 6, 1))}
    assert recent.id not in {row.conversation.id for row in store.list_conversations(until=date(2026, 1, 10))}
    assert old.id in {row.conversation.id for row in store.list_conversations(until=date(2026, 1, 10))}


def test_rename_delete_and_retention(store, session):
    conversation = store.create()
    store.append(conversation.id, _turn("Q", "R"))
    store.rename(conversation.id, "  Mandat   présidentiel ")
    assert store.get(conversation.id).title == "Mandat présidentiel"

    store.delete(conversation.id)
    assert (
        session.execute(
            text("SELECT count(*) FROM messages WHERE conversation_id = :id"), {"id": conversation.id}
        ).scalar()
        == 0
    )
    with pytest.raises(ConversationNotFoundError):
        store.get(conversation.id)

    stale = store.create()
    session.execute(
        text("UPDATE conversations SET updated_at = now() - interval '40 days' WHERE id = :id"), {"id": stale.id}
    )
    kept = store.create()
    store.settings = Settings(conversation_history=True, conversation_retention_days=30)
    assert store.purge_expired() >= 1
    assert not store.exists(stale.id)
    assert store.exists(kept.id)


# -- API -----------------------------------------------------------------------


def _outcome(question: str) -> RetrievalOutcome:
    return RetrievalOutcome(
        question=question,
        corpus_name="constitution",
        top_k=3,
        filters=None,
        index_run=SimpleNamespace(id="11111111-1111-1111-1111-111111111111", strategy="traditional"),
        retrieved=[
            RetrievedChunk(
                chunk_id=str(uuid4()),
                document_id=str(uuid4()),
                file_name="titre_II_president.txt",
                source_path="data/titre_II_president.txt",
                chunk_text="Le Président de la République est élu pour cinq ans au suffrage universel direct.",
                score=0.91,
                rank=1,
                char_start=120,
                char_end=205,
            )
        ],
        started=0.0,
        timings_ms={"embed": 12.0, "retrieval": 3.0},
    )


class _Generator:
    def __init__(self, pieces):
        self.pieces = pieces
        self.last_stats: dict[str, float] = {}

    def stream_answer(self, question, chunks, *, model=None):
        yield from self.pieces


@pytest.fixture()
def client(connection, settings) -> Iterator[TestClient]:
    app = create_app(settings)
    factory = _sessions(connection)

    def override_get_db():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_maker] = lambda: factory
    app.dependency_overrides[get_current_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


def test_api_conversation_round_trip(client):
    created = client.post(
        "/api/conversations", json={"corpus": "constitution", "channel": "ui"}, headers={"X-Raglab-User": "alice"}
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert created.json()["actor"] == "alice"

    question = "Quelle est la durée du mandat du Président ?"
    message_id = str(uuid4())
    with (
        patch.object(QueryService, "retrieve", return_value=_outcome(question)),
        patch(
            "raglab.retrieval.service.OllamaGenerator",
            return_value=_Generator(["Le Président est élu ", "pour cinq ans [Rank 1]."]),
        ),
    ):
        stream = client.post(
            "/api/query/stream",
            json={
                "question": question,
                "corpus": "constitution",
                "conversation_id": conversation_id,
                "message_id": message_id,
            },
        )
    done = [block for block in stream.text.split("\n\n") if block.startswith("event: done")][0]
    payload = json.loads(done.split("data: ", 1)[1])
    assert payload["conversation_id"] == conversation_id
    assert payload["message_id"] == message_id

    fake = QueryResponse(
        question="Et le Sénat ?",
        index_run_id="11111111-1111-1111-1111-111111111111",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[],
        answer="Le contexte ne permet pas de répondre.",
        llm_provider="ollama",
    )
    with patch("raglab.api.routers.query.QueryService") as service:
        service.return_value.query.return_value = fake
        plain = client.post("/api/query", json={"question": "Et le Sénat ?", "conversation_id": conversation_id}).json()
    assert plain["conversation_id"] == conversation_id

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assert detail["title"] == question
    assert detail["message_count"] == 2
    first = detail["messages"][0]
    assert first["id"] == message_id
    assert first["answer"] == "Le Président est élu pour cinq ans [Rank 1]."
    assert first["sources"][0]["file_name"] == "titre_II_president.txt"
    assert (first["sources"][0]["char_start"], first["sources"][0]["cited"]) == (120, True)
    assert first["presented_context"][0].startswith("[Source rank=1]\nFichier: titre_II_president.txt")
    assert first["llm_provider"] == "ollama"
    assert first["first_token_ms"] is not None
    assert first["options"]["top_k"] == 5
    assert first["request_id"]
    assert detail["messages"][1]["question"] == "Et le Sénat ?"

    hits = client.get("/api/conversations/search", params={"q": "presidents elue"}).json()
    assert hits[0]["conversation_id"] == conversation_id
    assert client.get("/api/conversations", params={"corpus": "constitution"}).json()[0]["id"] == conversation_id
    assert client.get("/api/conversations", params={"corpus": "lexml"}).json() == []

    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Mandats"})
    assert renamed.json()["title"] == "Mandats"
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_a_generation_failure_mid_stream_is_recorded(client):
    conversation_id = client.post("/api/conversations", json={}).json()["id"]

    class Failing(_Generator):
        def stream_answer(self, question, chunks, *, model=None):
            yield "Le Prés"
            raise ValueError("modele introuvable")

    with (
        patch.object(QueryService, "retrieve", return_value=_outcome("Q ?")),
        patch("raglab.retrieval.service.OllamaGenerator", return_value=Failing([])),
    ):
        client.post("/api/query/stream", json={"question": "Q ?", "conversation_id": conversation_id})

    message = client.get(f"/api/conversations/{conversation_id}").json()["messages"][0]
    assert (message["status"], message["answer"], message["error"]) == ("failed", "Le Prés", "modele introuvable")


# -- CLI -----------------------------------------------------------------------


def test_cli_history_and_query_conversation(connection, settings, monkeypatch):
    from raglab import cli

    factory = _sessions(connection)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    runner = CliRunner()

    fake = QueryResponse(
        question="Durée du mandat ?",
        index_run_id="11111111-1111-1111-1111-111111111111",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[],
        answer="Cinq ans.",
    )
    with patch("raglab.cli.QueryService") as service:
        service.return_value.query.return_value = fake
        result = runner.invoke(
            cli.app, ["query", "Durée du mandat ?", "--corpus", "constitution", "--conversation", "new"]
        )
    assert result.exit_code == 0, result.output
    conversation_id = json.loads(result.stdout)["conversation_id"]

    listed = runner.invoke(cli.app, ["history", "list", "--corpus", "constitution", "--json"])
    assert conversation_id in [item["id"] for item in json.loads(listed.stdout)]
    shown = runner.invoke(cli.app, ["history", "show", conversation_id])
    assert "Q : Durée du mandat ?" in shown.stdout and "R : Cinq ans." in shown.stdout
    found = runner.invoke(cli.app, ["history", "search", "durees"])
    assert conversation_id in found.stdout and "[Durée]" in found.stdout

    missing = runner.invoke(cli.app, ["query", "?", "--conversation", str(uuid4())])
    assert missing.exit_code != 0

    deleted = runner.invoke(cli.app, ["history", "delete", conversation_id, "--yes"])
    assert deleted.exit_code == 0
    assert runner.invoke(cli.app, ["history", "show", conversation_id]).exit_code == 1

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(conversation_history=False))
    off = runner.invoke(cli.app, ["history", "list"])
    assert off.exit_code == 1
    assert "RAGLAB_CONVERSATION_HISTORY" in off.stderr


# -- runtime switch ------------------------------------------------------------


def test_runtime_switch_overrides_the_env_default_and_deletes_nothing(connection):
    from raglab.conversations.settings import history_setting, set_history_enabled

    off_by_env = Settings(conversation_history=False, conversation_retention_days=30)
    session = _sessions(connection)()
    assert (history_setting(session, off_by_env).enabled, history_setting(session, off_by_env).source) == (False, "env")

    on = set_history_enabled(session, off_by_env, True, actor="alice")
    assert (on.enabled, on.source, on.env_default, on.retention_days, on.updated_by) == (
        True,
        "runtime",
        False,
        30,
        "alice",
    )
    store = ConversationStore(session, off_by_env)
    kept = store.create()
    store.append(kept.id, _turn("Q", "R"))

    off = set_history_enabled(session, off_by_env, False)
    assert (off.enabled, off.source) == (False, "runtime")
    # Off stops recording; what is stored stays.
    assert store.exists(kept.id)

    reset = set_history_enabled(session, Settings(conversation_history=True), None)
    assert (reset.enabled, reset.source) == (True, "env")
    session.close()


def test_api_switch_turns_recording_on_and_off_without_restart(connection):
    settings = Settings(conversation_history=False)
    app = create_app(settings)
    factory = _sessions(connection)

    def override_get_db():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_maker] = lambda: factory
    app.dependency_overrides[get_current_settings] = lambda: settings
    with TestClient(app) as client:
        state = client.get("/api/settings/conversation-history").json()
        assert (state["enabled"], state["source"], state["env_default"]) == (False, "env", False)
        assert client.get("/api/conversations").status_code == 404
        assert client.get("/api/config").json()["conversation_history"] is False

        switched = client.put(
            "/api/settings/conversation-history", json={"enabled": True}, headers={"X-Raglab-User": "admin"}
        ).json()
        assert (switched["enabled"], switched["source"], switched["updated_by"]) == (True, "runtime", "admin")
        assert client.get("/api/config").json()["conversation_history"] is True
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        fake = QueryResponse(
            question="Q ?",
            index_run_id="11111111-1111-1111-1111-111111111111",
            strategy=ChunkingStrategy.TRADITIONAL,
            retrieved_chunks=[],
            answer="R.",
        )
        with patch("raglab.api.routers.query.QueryService") as service:
            service.return_value.query.return_value = fake
            recorded = client.post("/api/query", json={"question": "Q ?", "conversation_id": conversation_id}).json()
        assert recorded["conversation_id"] == conversation_id

        client.put("/api/settings/conversation-history", json={"enabled": False})
        assert client.get("/api/conversations").status_code == 404
        with patch("raglab.api.routers.query.QueryService") as service:
            service.return_value.query.return_value = fake
            ignored = client.post("/api/query", json={"question": "Q ?", "conversation_id": conversation_id}).json()
        assert ignored["conversation_id"] is None

        # Back on: the conversation recorded before is still there, with one turn.
        client.put("/api/settings/conversation-history", json={"enabled": True})
        assert client.get(f"/api/conversations/{conversation_id}").json()["message_count"] == 1
        reset = client.put("/api/settings/conversation-history", json={"enabled": None}).json()
        assert (reset["enabled"], reset["source"]) == (False, "env")


def test_cli_history_enable_disable_status(connection, monkeypatch):
    from raglab import cli

    factory = _sessions(connection)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(conversation_history=False))
    runner = CliRunner()

    assert "desactive (source : RAGLAB_CONVERSATION_HISTORY)" in runner.invoke(cli.app, ["history", "status"]).stdout
    assert runner.invoke(cli.app, ["history", "list"]).exit_code == 1
    enabled = runner.invoke(cli.app, ["history", "enable"])
    assert enabled.exit_code == 0 and "Historique serveur : active (source : interrupteur" in enabled.stdout
    assert runner.invoke(cli.app, ["history", "list"]).exit_code == 0
    disabled = runner.invoke(cli.app, ["history", "disable"])
    assert "deja enregistrees sont conservees" in disabled.stdout
    status = json.loads(runner.invoke(cli.app, ["history", "status", "--json"]).stdout)
    assert (status["enabled"], status["source"]) == (False, "runtime")
    reset = runner.invoke(cli.app, ["history", "reset"])
    assert "source : RAGLAB_CONVERSATION_HISTORY" in reset.stdout
