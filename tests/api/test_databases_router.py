from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from raglab.api.deps import get_current_settings
from raglab.api.main import app
from raglab.config import Settings


def _by_kind(body: dict, kind: str) -> dict:
    return next(d for d in body["databases"] if d["kind"] == kind)


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_returns_both_connections(neo4j_cls, client: TestClient, mock_session):
    # pg SELECT 1 succeeds -> postgres status = ok
    mock_session.execute.return_value = None
    # neo4j ping returns True -> status = ok
    neo4j_cls.return_value.ping.return_value = True

    response = client.get("/api/databases")
    assert response.status_code == 200
    body = response.json()

    assert len(body["databases"]) == 2
    pg = _by_kind(body, "postgres")
    neo = _by_kind(body, "neo4j")

    assert pg["status"] == "ok"
    # The compose URL uses `postgres` as host; the endpoint rewrites to
    # `localhost` so the deep-link is clickable from the user's browser.
    assert pg["host"] == "localhost"
    assert pg["user"] == "raglab"
    assert pg["database"] == "raglab"
    assert pg["deep_link"] is not None
    assert "pgsql=postgres" in pg["deep_link"]
    assert "username=raglab" in pg["deep_link"]
    # The connection string never carries the password.
    assert ":***@" in pg["url"]

    assert neo["status"] == "ok"
    assert neo["host"] == "localhost"
    assert neo["deep_link"] is not None
    # connectURL carries the full auth (user:password@host:port) so the
    # Neo4j Browser login card is pre-filled end-to-end.
    assert "connectURL" in neo["deep_link"]
    assert "neo4j" in neo["deep_link"]  # user
    assert "raglab_neo4j" in neo["deep_link"]  # password


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_shows_only_the_dev_default_passwords(neo4j_cls, client: TestClient, mock_session):
    mock_session.execute.return_value = None
    neo4j_cls.return_value.ping.return_value = True
    defaults = client.get("/api/databases").json()
    assert _by_kind(defaults, "postgres")["password"] == "raglab"
    assert _by_kind(defaults, "neo4j")["password"] == "raglab_neo4j"

    app.dependency_overrides[get_current_settings] = lambda: Settings(
        _env_file=None,
        database_url="postgresql+psycopg://raglab:s3cret-pg@db.internal:5433/raglab",
        neo4j_password="s3cret-neo",
    )
    try:
        body = client.get("/api/databases").json()
    finally:
        app.dependency_overrides.pop(get_current_settings, None)
    pg = _by_kind(body, "postgres")
    neo = _by_kind(body, "neo4j")
    assert pg["password"] is None and pg["password_is_default"] is False
    assert pg["password_env"] == "RAGLAB_DATABASE_URL"
    assert pg["host"] == "db.internal" and pg["port"] == 5433
    assert neo["password"] is None
    assert "s3cret" not in str(body)


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_marks_pg_unreachable_on_query_error(neo4j_cls, client: TestClient, mock_session):
    mock_session.execute.side_effect = RuntimeError("connection refused")
    neo4j_cls.return_value.ping.return_value = True

    response = client.get("/api/databases")
    body = response.json()
    assert _by_kind(body, "postgres")["status"] == "unreachable"
    assert _by_kind(body, "neo4j")["status"] == "ok"


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_marks_neo4j_unreachable(neo4j_cls, client: TestClient, mock_session):
    mock_session.execute.return_value = None
    neo4j_cls.return_value.ping.return_value = False

    response = client.get("/api/databases")
    assert _by_kind(response.json(), "neo4j")["status"] == "unreachable"
