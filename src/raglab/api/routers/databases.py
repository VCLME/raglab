from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db
from raglab.api.schemas import DatabaseConnection, DatabasesResponse
from raglab.config import Settings
from raglab.graph.neo4j import Neo4jGraphStore

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["databases"])


def _parse_pg_url(url: str) -> tuple[str, int, str, str, str]:
    """Extract host/port/user/password/db from a SQLAlchemy Postgres URL.

    Defaults cover the cases where the URL drops a component. Host falls
    back to `localhost` so the deep-link works when the user is on the
    host machine (the docker URL points at `postgres`, a name only
    visible inside the compose network).
    """
    parsed = urlparse(url.replace("+psycopg", "").replace("+asyncpg", ""))
    host = parsed.hostname or "localhost"
    # Translate the in-network compose name to the host-side equivalent.
    if host == "postgres":
        host = "localhost"
    port = parsed.port or 5432
    user = parsed.username or "raglab"
    password = parsed.password or "raglab"
    database = (parsed.path or "/raglab").lstrip("/")
    return host, port, user, password, database


def _adminer_deep_link(adminer_url: str, *, user: str, database: str) -> str:
    """Build an Adminer URL with server/user/db prefilled.

    Adminer reads `pgsql`, `username` and `db` from the query string and
    auto-fills the login form. Password is never in the URL (security).
    The driver is `pgsql`; the server inside Docker is `postgres`, which
    is what Adminer's ADMINER_DEFAULT_SERVER env var also resolves to.
    """
    base = adminer_url.rstrip("/")
    return (
        f"{base}/?pgsql=postgres"
        f"&username={quote(user)}"
        f"&db={quote(database)}"
    )


def _neo4j_http_url(bolt_uri: str) -> str:
    """Map a bolt URI to the matching Neo4j Browser URL.

    Inside compose we use `bolt://neo4j:7687`; from the host machine the
    Browser is reachable on `http://localhost:7474`. We rewrite the host
    the same way as for Postgres to keep the deep-link clickable from
    the user's browser.
    """
    parsed = urlparse(bolt_uri)
    host = parsed.hostname or "localhost"
    if host == "neo4j":
        host = "localhost"
    return f"http://{host}:7474"


def _neo4j_deep_link(http_url: str, bolt_uri: str, user: str) -> str:
    """Return a Neo4j Browser URL that pre-selects the server.

    The `dbms` query parameter tells Neo4j Browser which DBMS to
    auto-fill in the login card. Password still has to be typed — Neo4j
    does not read it from the URL.
    """
    parsed = urlparse(bolt_uri)
    host = parsed.hostname or "localhost"
    if host == "neo4j":
        host = "localhost"
    port = parsed.port or 7687
    return f"{http_url}/browser/?dbms=bolt%3A%2F%2F{quote(user)}%40{host}%3A{port}"


@router.get("/api/databases", response_model=DatabasesResponse)
def list_databases(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> DatabasesResponse:
    # --- PostgreSQL -------------------------------------------------
    pg_host, pg_port, pg_user, pg_pw, pg_db = _parse_pg_url(settings.database_url)
    pg_status = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        LOGGER.warning("databases.postgres_unreachable", extra={"error": str(exc)})
        pg_status = "unreachable"

    postgres = DatabaseConnection(
        kind="postgres",
        label="PostgreSQL + pgvector",
        status=pg_status,
        host=pg_host,
        port=pg_port,
        user=pg_user,
        password=pg_pw,
        database=pg_db,
        url=settings.database_url,
        web_url=settings.adminer_url,
        deep_link=_adminer_deep_link(settings.adminer_url, user=pg_user, database=pg_db),
    )

    # --- Neo4j ------------------------------------------------------
    neo4j_status = "ok"
    store = Neo4jGraphStore()
    try:
        if not store.ping():
            neo4j_status = "unreachable"
    except Exception as exc:
        LOGGER.warning("databases.neo4j_unreachable", extra={"error": str(exc)})
        neo4j_status = "unreachable"
    finally:
        store.close()

    neo4j_http = _neo4j_http_url(settings.neo4j_uri)
    neo4j_parsed = urlparse(settings.neo4j_uri)
    neo4j_host = neo4j_parsed.hostname or "localhost"
    if neo4j_host == "neo4j":
        neo4j_host = "localhost"
    neo4j = DatabaseConnection(
        kind="neo4j",
        label="Neo4j (graph store)",
        status=neo4j_status,
        host=neo4j_host,
        port=neo4j_parsed.port or 7687,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
        url=settings.neo4j_uri,
        web_url=neo4j_http,
        deep_link=_neo4j_deep_link(neo4j_http, settings.neo4j_uri, settings.neo4j_user),
    )

    return DatabasesResponse(databases=[postgres, neo4j])
