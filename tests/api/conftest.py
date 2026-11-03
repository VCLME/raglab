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
