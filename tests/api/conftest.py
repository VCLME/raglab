from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from raglab.api.deps import get_db
from raglab.api.main import app as fastapi_app


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock(name="Session")


@pytest.fixture
def client(mock_session: MagicMock) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[MagicMock]:
        yield mock_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(fastapi_app) as test_client:
            yield test_client
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_client(mock_session: MagicMock):
    """Build a fresh app from explicit settings (API key, rate limit...)."""
    from raglab.api.main import create_app
    from raglab.config import Settings

    opened: list[TestClient] = []

    def _make(**overrides) -> TestClient:
        app = create_app(Settings(**overrides))

        def override_get_db() -> Iterator[MagicMock]:
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db
        test_client = TestClient(app)
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield _make
    for test_client in opened:
        test_client.__exit__(None, None, None)
