from __future__ import annotations

from pathlib import Path

import pytest

from raglab.api.main import app as fastapi_app
from raglab.config import Settings
from raglab.domain.errors import SourceBusyError
from raglab.sources.jobs import SourceJobs, get_source_jobs


class FakeJobs(SourceJobs):
    """Real registry and statuses, no thread and no network."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(
            Settings(data_dir=tmp_path, legifrance_dir=tmp_path / "legi", eurlex_dir=tmp_path / "eurlex"),
            repo_root=tmp_path,
        )
        self.started: list[tuple[str, bool]] = []

    def start(self, name: str, *, ingest: bool = True) -> dict:
        if self.started:
            raise SourceBusyError(f"La collecte {name} tourne deja (etape fetch).")
        self.started.append((name, ingest))
        self._begin(name)
        return self.status(name)


@pytest.fixture
def jobs(tmp_path):
    fake = FakeJobs(tmp_path)
    fastapi_app.dependency_overrides[get_source_jobs] = lambda: fake
    yield fake
    fastapi_app.dependency_overrides.pop(get_source_jobs, None)


def test_list_sources(client, jobs):
    response = client.get("/api/sources")
    assert response.status_code == 200
    rows = {row["source"]: row for row in response.json()}
    assert rows["legi"]["corpus"] == "bench_legi_consommation_fr"
    assert rows["legi"]["state"] == "idle"
    assert rows["legi"]["command"] == "raglab legifrance fetch --code consommation"
    assert rows["eurlex"]["corpus"] == "bench_eurlex_compliance"


def test_fetch_starts_a_job_and_answers_202(client, jobs):
    response = client.post("/api/sources/eurlex/fetch", json={"ingest": False})
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "running"
    assert body["stage"] == "fetch"
    assert body["progress"] == {"done": 0, "total": None}
    assert jobs.started == [("eurlex", False)]


def test_fetch_without_a_body_ingests(client, jobs):
    assert client.post("/api/sources/legi/fetch").status_code == 202
    assert jobs.started == [("legi", True)]


def test_a_second_fetch_is_a_409(client, jobs):
    client.post("/api/sources/legi/fetch")
    response = client.post("/api/sources/legi/fetch")
    assert response.status_code == 409
    assert response.json()["error"] == "SourceBusyError"


def test_status_reports_progress_and_error(client, jobs):
    job = jobs._jobs["legi"]
    job.state, job.stage, job.done, job.total = "failed", "fetch", 3, 10
    job.error = {"status_code": 502, "detail": "git a echoue", "error": "SourceFetchError"}

    response = client.get("/api/sources/legi/status")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "failed"
    assert body["progress"] == {"done": 3, "total": 10}
    assert body["error"]["error"] == "SourceFetchError"
    assert body["corpus"] == "bench_legi_consommation_fr"


def test_unknown_source_is_a_404(client, jobs):
    assert client.get("/api/sources/civil/status").status_code == 404
    assert client.post("/api/sources/civil/fetch").status_code == 404
