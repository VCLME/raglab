"""Connection details of the two stores, for the Atelier's Databases page.

Design from PR #25 (owner): one entry per store with its reachability, its
connection details and a deep link that opens the admin tool with the login
form pre-filled (Adminer for PostgreSQL, Neo4j Browser for Neo4j).

Secrets: a password is returned only when it is the dev default raglab ships
(`docker-compose.yml`); any other password stays on the server and the entry
says which variable holds it. Connection strings always come back with the
password masked.
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db
from raglab.api.schemas import DatabaseConnection, DatabasesResponse
from raglab.config import Settings
from raglab.graph import Neo4jGraphStore
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["databases"])

# The credentials of docker-compose.yml: shown, since anyone with the repo has them.
DEV_POSTGRES_PASSWORD = "raglab"
DEV_NEO4J_PASSWORD = "raglab_neo4j"

# Compose service names are only resolvable inside the compose network.
_COMPOSE_HOSTS = {"postgres", "neo4j"}


def _host_side(host: str | None) -> str:
    """The host as seen from the user's browser (compose names become localhost)."""
    if not host or host in _COMPOSE_HOSTS:
        return "localhost"
    return host


def _parse_pg_url(url: str) -> tuple[str, int, str, str, str]:
    """Host, port, user, password and database of a SQLAlchemy Postgres URL."""
    parsed = urlparse(url.replace("+psycopg", "").replace("+asyncpg", ""))
    return (
        _host_side(parsed.hostname),
        parsed.port or 5432,
        parsed.username or "raglab",
        parsed.password or "",
        (parsed.path or "/raglab").lstrip("/") or "raglab",
    )


def _mask_password(url: str) -> str:
    """The URL with its password replaced by `***`."""
    parsed = urlparse(url)
    if not parsed.password:
        return url
    netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
    return parsed._replace(netloc=netloc).geturl()


def _adminer_deep_link(adminer_url: str, *, user: str, database: str) -> str:
    """Adminer with driver, server, user and database pre-filled.

    The server is `postgres`, the compose name Adminer resolves (it runs in
    the same network). Adminer never reads a password from the URL.
    """
    base = adminer_url.rstrip("/")
    return f"{base}/?pgsql=postgres&username={quote(user)}&db={quote(database)}"


def _neo4j_http_url(bolt_uri: str) -> str:
    """Neo4j Browser for a bolt URI (the HTTP port of the compose service)."""
    return f"http://{_host_side(urlparse(bolt_uri).hostname)}:7474"


def _neo4j_deep_link(http_url: str, bolt_uri: str, user: str, password: str | None) -> str:
    """Neo4j Browser with its connection card pre-filled.

    `connectURL` takes `neo4j://user[:password]@host:port`. The password is
    put in only when it is the dev default: the URL lands in the browser
    history.
    """
    parsed = urlparse(bolt_uri)
    auth = quote(user, safe="") + (f":{quote(password, safe='')}" if password else "")
    connect = f"neo4j://{auth}@{_host_side(parsed.hostname)}:{parsed.port or 7687}"
    return f"{http_url}/browser/?connectURL={quote(connect, safe='')}"


@router.get("/api/databases", response_model=DatabasesResponse)
def list_databases(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> DatabasesResponse:
    """PostgreSQL and Neo4j: reachability, connection details, admin deep links."""
    pg_host, pg_port, pg_user, pg_password, pg_db = _parse_pg_url(settings.database_url)
    pg_status = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        log_event(LOGGER, logging.WARNING, "databases.postgres_unreachable", error=type(exc).__name__)
        pg_status = "unreachable"
    pg_default = pg_password == DEV_POSTGRES_PASSWORD
    postgres = DatabaseConnection(
        kind="postgres",
        label="PostgreSQL + pgvector",
        status=pg_status,
        host=pg_host,
        port=pg_port,
        user=pg_user,
        password=pg_password if pg_default else None,
        password_is_default=pg_default,
        password_env="RAGLAB_DATABASE_URL",
        database=pg_db,
        url=_mask_password(settings.database_url),
        web_url=settings.adminer_url,
        deep_link=_adminer_deep_link(settings.adminer_url, user=pg_user, database=pg_db),
    )

    neo4j_status = "ok"
    store = Neo4jGraphStore()
    try:
        if not store.ping():
            neo4j_status = "unreachable"
    except Exception as exc:
        log_event(LOGGER, logging.WARNING, "databases.neo4j_unreachable", error=type(exc).__name__)
        neo4j_status = "unreachable"
    finally:
        store.close()
    neo4j_default = settings.neo4j_password == DEV_NEO4J_PASSWORD
    neo4j_password = settings.neo4j_password if neo4j_default else None
    neo4j_parsed = urlparse(settings.neo4j_uri)
    neo4j_http = _neo4j_http_url(settings.neo4j_uri)
    neo4j = DatabaseConnection(
        kind="neo4j",
        label="Neo4j",
        status=neo4j_status,
        host=_host_side(neo4j_parsed.hostname),
        port=neo4j_parsed.port or 7687,
        user=settings.neo4j_user,
        password=neo4j_password,
        password_is_default=neo4j_default,
        password_env="RAGLAB_NEO4J_PASSWORD",
        database=settings.neo4j_database,
        url=settings.neo4j_uri,
        web_url=neo4j_http,
        deep_link=_neo4j_deep_link(neo4j_http, settings.neo4j_uri, settings.neo4j_user, neo4j_password),
    )

    return DatabasesResponse(databases=[postgres, neo4j])
