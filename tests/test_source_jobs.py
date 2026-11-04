from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
import requests

from raglab.config import Settings
from raglab.domain.errors import SourceBusyError
from raglab.eurlex.collector import EurlexCollector
from raglab.legifrance.collector import CodeCollector
from raglab.sources.jobs import SourceJobs


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        legifrance_dir=tmp_path / "data" / "legifrance",
        eurlex_dir=tmp_path / "data" / "eurlex",
        **overrides,
    )


def _write_corpus(output_dir: Path, text: str = "Article L221-18") -> dict:
    corpus_dir = output_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "a.txt").write_text(text, encoding="utf-8")
    return {"output_dir": str(output_dir), "corpus_dir": str(corpus_dir), "documents": 1}


def _freeze(repo_root: Path, suite: str, text: str) -> None:
    manifest = repo_root / "benchmarks" / suite / "corpus_manifest.json"
    manifest.parent.mkdir(parents=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest.write_text(json.dumps({"documents": [{"file_name": "a.txt", "sha256": digest}]}), encoding="utf-8")


@pytest.fixture(autouse=True)
def no_job_outlives_its_test():
    yield
    alive = [thread.name for thread in threading.enumerate() if thread.name.startswith("raglab-source-")]
    assert alive == [], "a fetch job thread outlived its test (join it with SourceJobs.wait)"


@pytest.fixture
def ingested(monkeypatch) -> list[str]:
    calls: list[str] = []

    def fake_ingest(self, source, suite):
        calls.append(suite.corpus_name)
        return {"ingested": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(SourceJobs, "_ingest", fake_ingest)
    return calls


def _fake_legi(monkeypatch, behaviour):
    monkeypatch.setattr(CodeCollector, "collect", lambda self, **kwargs: behaviour(**kwargs))


def _fake_eurlex(monkeypatch, behaviour):
    monkeypatch.setattr(EurlexCollector, "collect", lambda self, **kwargs: behaviour(**kwargs))


def test_legi_job_fetches_verifies_and_ingests(tmp_path, monkeypatch, ingested):
    _freeze(tmp_path, "legi_consommation", "Article L221-18")

    def collect(*, code, output_dir, progress):
        assert code == "consommation"
        progress(1, 2)
        progress(2, 2)
        return _write_corpus(output_dir)

    _fake_legi(monkeypatch, collect)
    status = SourceJobs(_settings(tmp_path), repo_root=tmp_path).run("legi")

    assert status["state"] == "succeeded"
    assert status["corpus"] == "bench_legi_consommation_fr"
    assert status["stage"] is None
    assert status["progress"] == {"done": 2, "total": 2}
    assert status["error"] is None
    assert status["result"]["manifest"]["problems"] == 0
    assert status["result"]["ingestion"] == {"ingested": 1, "updated": 0, "skipped": 0}
    assert ingested == ["bench_legi_consommation_fr"]


def test_a_corpus_that_drifted_from_the_frozen_manifest_is_reported(tmp_path, monkeypatch, ingested):
    _freeze(tmp_path, "legi_consommation", "older text")
    _fake_legi(monkeypatch, lambda *, code, output_dir, progress: _write_corpus(output_dir))

    status = SourceJobs(_settings(tmp_path), repo_root=tmp_path).run("legi")

    assert status["state"] == "succeeded"
    assert status["result"]["manifest"]["problems"] == 1
    assert status["result"]["manifest"]["examples"] == ["changed:a.txt"]


def test_no_ingest_writes_the_files_only(tmp_path, monkeypatch, ingested):
    def collect(*, output_dir, delay, progress):
        assert delay == 1.0
        return _write_corpus(output_dir)

    _fake_eurlex(monkeypatch, collect)
    status = SourceJobs(_settings(tmp_path), repo_root=tmp_path).run("eurlex", ingest=False)

    assert status["state"] == "succeeded"
    assert status["corpus"] == "bench_eurlex_compliance"
    assert status["result"]["ingestion"] is None
    assert status["result"]["manifest"]["frozen"] is None
    assert ingested == []


def test_cellar_unreachable_fails_with_a_502(tmp_path, monkeypatch, ingested):
    def collect(**kwargs):
        raise requests.exceptions.ConnectionError("Max retries exceeded")

    _fake_eurlex(monkeypatch, collect)
    status = SourceJobs(_settings(tmp_path), repo_root=tmp_path).run("eurlex")

    assert status["state"] == "failed"
    assert status["stage"] == "fetch"
    assert status["error"]["status_code"] == 502
    assert status["error"]["error"] == "SourceFetchError"
    assert status["error"]["source"] == "eurlex"
    assert "Max retries" in status["error"]["cause"]
    assert ingested == []


def test_git_failure_keeps_its_stderr(tmp_path, monkeypatch, ingested):
    def collect(**kwargs):
        raise subprocess.CalledProcessError(128, ["git", "clone"], stderr=b"fatal: unable to access")

    _fake_legi(monkeypatch, collect)
    status = SourceJobs(_settings(tmp_path), repo_root=tmp_path).run("legi")

    assert status["error"]["status_code"] == 502
    assert status["error"]["cause"] == "fatal: unable to access"


def test_a_stalled_git_clone_is_a_fetch_timeout(tmp_path, monkeypatch, ingested):
    def collect(**kwargs):
        raise subprocess.TimeoutExpired(["git", "clone"], 5)

    _fake_legi(monkeypatch, collect)
    status = SourceJobs(_settings(tmp_path, legifrance_git_timeout_seconds=5), repo_root=tmp_path).run("legi")

    assert status["error"]["status_code"] == 504
    assert status["error"]["stage"] == "fetch"
    assert status["error"]["timeout_seconds"] == 5
    assert "RAGLAB_LEGIFRANCE_GIT_TIMEOUT_SECONDS" in status["error"]["detail"]


def test_the_job_budget_stops_a_slow_fetch(tmp_path, monkeypatch, ingested):
    def collect(*, output_dir, delay, progress):
        time.sleep(0.05)
        progress(1, 60)
        raise AssertionError("the budget should have stopped the job")

    _fake_eurlex(monkeypatch, collect)
    status = SourceJobs(_settings(tmp_path, source_fetch_timeout_seconds=0.01), repo_root=tmp_path).run("eurlex")

    assert status["state"] == "failed"
    assert status["progress"] == {"done": 1, "total": 60}
    assert status["error"]["status_code"] == 504
    assert "RAGLAB_SOURCE_FETCH_TIMEOUT_SECONDS" in status["error"]["detail"]


def test_one_job_per_source_at_a_time(tmp_path, monkeypatch, ingested):
    release = threading.Event()
    entered = threading.Event()

    def collect(*, code, output_dir, progress):
        entered.set()
        release.wait(5)
        return _write_corpus(output_dir)

    _fake_legi(monkeypatch, collect)
    jobs = SourceJobs(_settings(tmp_path), repo_root=tmp_path)

    first = jobs.start("legi")
    assert first["state"] == "running"
    assert first["stage"] == "fetch"
    assert entered.wait(5)
    with pytest.raises(SourceBusyError):
        jobs.start("legi")
    assert jobs.status("eurlex")["state"] == "idle"

    release.set()
    assert jobs.wait("legi", timeout=5)["state"] == "succeeded"
    # A finished job can be started again. Wait for it: a thread that
    # outlives the test would run the real ingestion once the fakes are gone.
    assert jobs.start("legi")["state"] == "running"
    assert jobs.wait("legi", timeout=5)["state"] == "succeeded"


def test_unknown_source(tmp_path):
    with pytest.raises(KeyError):
        SourceJobs(_settings(tmp_path), repo_root=tmp_path).status("civil")
