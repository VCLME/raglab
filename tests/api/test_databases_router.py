from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_returns_both_connections(neo4j_cls, client: TestClient, mock_session):
    # pg SELECT 1 succeeds → postgres status = ok
    mock_session.execute.return_value = None
    # neo4j ping returns True → status = ok
    neo4j_cls.return_value.ping.return_value = True

    response = client.get("/api/databases")
    assert response.status_code == 200
    body = response.json()

    assert len(body["databases"]) == 2
    pg = next(d for d in body["databases"] if d["kind"] == "postgres")
    neo = next(d for d in body["databases"] if d["kind"] == "neo4j")

    assert pg["status"] == "ok"
    # The compose URL uses `postgres` as host; the endpoint rewrites to
    # `localhost` so the deep-link is clickable from the user's browser.
    assert pg["host"] == "localhost"
    assert pg["user"] == "raglab"
    assert pg["database"] == "raglab"
    assert pg["deep_link"] is not None
    assert "pgsql=postgres" in pg["deep_link"]
    assert "username=raglab" in pg["deep_link"]

    assert neo["status"] == "ok"
    assert neo["host"] == "localhost"
    assert neo["deep_link"] is not None
    assert "bolt" in neo["deep_link"]


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_marks_pg_unreachable_on_query_error(
    neo4j_cls, client: TestClient, mock_session
):
    mock_session.execute.side_effect = RuntimeError("connection refused")
    neo4j_cls.return_value.ping.return_value = True

    response = client.get("/api/databases")
    body = response.json()
    pg = next(d for d in body["databases"] if d["kind"] == "postgres")
    neo = next(d for d in body["databases"] if d["kind"] == "neo4j")
    assert pg["status"] == "unreachable"
    assert neo["status"] == "ok"


@patch("raglab.api.routers.databases.Neo4jGraphStore")
def test_databases_marks_neo4j_unreachable(
    neo4j_cls, client: TestClient, mock_session
):
    mock_session.execute.return_value = None
    neo4j_cls.return_value.ping.return_value = False

    response = client.get("/api/databases")
    body = response.json()
    neo = next(d for d in body["databases"] if d["kind"] == "neo4j")
    assert neo["status"] == "unreachable"
