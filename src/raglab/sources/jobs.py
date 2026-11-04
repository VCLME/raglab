"""Fetch and ingest the official-source corpora as a background job.

`raglab legifrance fetch` (a bare git clone, then the history walk) and
`raglab eurlex fetch` (about 60 CELLAR requests at one per second) take from
one to a few minutes: too long for a request. The API starts the job in a
thread and the Atelier polls its status. Jobs live in the API process, one per
source at a time, and their state is lost on restart; the files they write and
the ingested corpus are not.

A job never indexes: embedding is the Vectorisation step of the Atelier, so a
fetch never touches the GPU.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from contextvars import copy_context
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from raglab.benchmarks.suite import Suite, default_suites, verify_manifest
from raglab.config import Settings, get_settings
from raglab.domain.errors import SourceBusyError, SourceFetchError, StageTimeoutError
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

# Source name in the API -> benchmark suite that holds its corpus name,
# folder, language and frozen manifest.
SOURCE_SUITES = {"legi": "legi_consommation", "eurlex": "eurlex_compliance", "br_expat": "br_expat"}
SOURCE_COMMANDS = {
    "legi": "raglab legifrance fetch --code consommation",
    "eurlex": "raglab eurlex fetch",
    "br_expat": "raglab lexml br-expat",
}
STAGES = ("fetch", "verify", "ingest")

Progress = Callable[[int, int], None]


@dataclass(slots=True)
class SourceJob:
    source: str
    corpus: str
    state: str = "idle"  # idle | running | succeeded | failed
    stage: str | None = None  # fetch | verify | ingest
    done: int = 0
    total: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "corpus": self.corpus,
            "state": self.state,
            "stage": self.stage,
            "progress": {"done": self.done, "total": self.total},
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


def official_sources(settings: Settings, repo_root: Path | None = None) -> dict[str, Suite]:
    suites = {suite.name: suite for suite in default_suites(settings, repo_root or Path.cwd())}
    return {name: suites[suite] for name, suite in SOURCE_SUITES.items()}


def error_payload(exc: Exception, settings: Settings) -> dict[str, Any]:
    """The body the API would answer for `exc`, with its status code."""
    # Imported here: the `raglab.api` package loads the app, whose router
    # imports this module.
    from raglab.api.errors import describe_error

    info = describe_error(exc, settings)
    if info is None:
        return {"status_code": 500, "detail": str(exc), "error": type(exc).__name__}
    return {"status_code": info.status_code, **info.body}


class SourceJobs:
    """One fetch job per official source, run in a thread (`start`) or inline (`run`)."""

    def __init__(self, settings: Settings | None = None, *, repo_root: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.sources = official_sources(self.settings, repo_root)
        self._lock = threading.Lock()
        self._jobs = {name: SourceJob(name, suite.corpus_name) for name, suite in self.sources.items()}
        self._threads: dict[str, threading.Thread] = {}

    def _job(self, name: str) -> SourceJob:
        if name not in self._jobs:
            raise KeyError(name)
        return self._jobs[name]

    def status(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self._job(name).snapshot()

    def statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.snapshot() for job in self._jobs.values()]

    def _begin(self, name: str) -> SourceJob:
        with self._lock:
            job = self._job(name)
            if job.state == "running":
                raise SourceBusyError(f"La collecte {name} tourne deja (etape {job.stage}).")
            job.state, job.stage, job.done, job.total = "running", STAGES[0], 0, None
            job.started_at, job.finished_at, job.error, job.result = datetime.now(UTC), None, None, None
            return job

    def start(self, name: str, *, ingest: bool = True) -> dict[str, Any]:
        """Start the job in a daemon thread and return its first status."""
        job = self._begin(name)
        # The copied context keeps the request id on the job's log lines.
        thread = threading.Thread(
            target=copy_context().run,
            args=(self._execute, job, ingest),
            name=f"raglab-source-{name}",
            daemon=True,
        )
        self._threads[name] = thread
        thread.start()
        return self.status(name)

    def wait(self, name: str, timeout: float | None = None) -> dict[str, Any]:
        """Wait for the thread of the last `start(name)` and return the status."""
        thread = self._threads.get(name)
        if thread is not None:
            thread.join(timeout)
        return self.status(name)

    def run(self, name: str, *, ingest: bool = True) -> dict[str, Any]:
        """Run the job inline (CLI) and return its final status."""
        self._execute(self._begin(name), ingest)
        return self.status(name)

    def _set(self, job: SourceJob, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(job, key, value)

    def _execute(self, job: SourceJob, ingest: bool) -> None:
        started = time.monotonic()
        log_event(LOGGER, logging.INFO, "sources.fetch.started", source=job.source, corpus=job.corpus, ingest=ingest)
        try:
            result = self._pipeline(job, ingest, started)
        except Exception as exc:
            error = error_payload(exc, self.settings)
            self._set(job, state="failed", error=error, finished_at=datetime.now(UTC))
            log_event(
                LOGGER,
                logging.ERROR,
                "sources.fetch.failed",
                source=job.source,
                stage=job.stage,
                error=error.get("error"),
                detail=error.get("detail"),
                duration_s=round(time.monotonic() - started, 1),
            )
            return
        self._set(job, state="succeeded", stage=None, result=result, finished_at=datetime.now(UTC))
        log_event(
            LOGGER,
            logging.INFO,
            "sources.fetch.completed",
            source=job.source,
            corpus=job.corpus,
            documents=result["documents"],
            manifest_problems=result["manifest"]["problems"],
            duration_s=round(time.monotonic() - started, 1),
        )

    def _pipeline(self, job: SourceJob, ingest: bool, started: float) -> dict[str, Any]:
        budget = self.settings.source_fetch_timeout_seconds
        suite = self.sources[job.source]

        def check_budget() -> None:
            if budget > 0 and time.monotonic() - started > budget:
                raise StageTimeoutError(
                    job.stage or "fetch",
                    budget,
                    f"Collecte {job.source} interrompue a l'etape {job.stage} apres {budget:g} s. "
                    "Augmente RAGLAB_SOURCE_FETCH_TIMEOUT_SECONDS si la source est lente.",
                )

        def progress(done: int, total: int) -> None:
            self._set(job, done=done, total=total)
            check_budget()

        collected = self._fetch(job.source, suite, progress)

        self._set(job, stage="verify")
        check_budget()
        frozen = suite.manifest_path if suite.manifest_path and suite.manifest_path.exists() else None
        problems = verify_manifest(suite.corpus_dir, frozen) if frozen else []
        manifest = {
            "frozen": str(frozen) if frozen else None,
            "problems": len(problems),
            "examples": problems[:5],
        }

        ingestion: dict[str, Any] | None = None
        if ingest:
            self._set(job, stage="ingest")
            check_budget()
            ingestion = self._ingest(job.source, suite)
        return {
            "corpus_dir": collected["corpus_dir"],
            "documents": collected["documents"],
            "manifest": manifest,
            "ingestion": ingestion,
        }

    def _fetch(self, source: str, suite: Suite, progress: Progress) -> dict[str, Any]:
        output_dir = suite.corpus_dir.parent
        try:
            if source == "legi":
                from raglab.legifrance.collector import CodeCollector

                return CodeCollector(self.settings).collect(
                    code="consommation", output_dir=output_dir, progress=progress
                )
            if source == "br_expat":
                from raglab.lexml.br_expat import BrExpatCollector

                return BrExpatCollector(self.settings).collect(output_dir=output_dir, progress=progress)
            from raglab.eurlex.collector import EurlexCollector

            return EurlexCollector(self.settings).collect(
                output_dir=output_dir, delay=self.settings.eurlex_request_delay_seconds, progress=progress
            )
        except subprocess.TimeoutExpired as exc:
            timeout = self.settings.legifrance_git_timeout_seconds
            raise StageTimeoutError(
                "fetch",
                timeout,
                f"Le depot git de {source} n'a pas repondu en {timeout:g} s. "
                "Augmente RAGLAB_LEGIFRANCE_GIT_TIMEOUT_SECONDS si le reseau est lent.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr
            raise SourceFetchError(
                source, f"git a echoue pour {source} (code {exc.returncode}).", cause=(stderr or "").strip() or None
            ) from exc
        except requests.RequestException as exc:
            raise SourceFetchError(source, f"CELLAR injoignable pour {source}.", cause=str(exc)) from exc

    def _ingest(self, source: str, suite: Suite) -> dict[str, Any]:
        # Documents only (text and metadata in Postgres), no embedding.
        from raglab.db import session_scope
        from raglab.ingestion.service import IngestionService

        with session_scope() as session:
            return IngestionService(session).ingest_folder(
                suite.corpus_dir,
                corpus_name=suite.corpus_name,
                description=f"Benchmark {suite.name} (fige)",
                language=suite.language,
            )


@lru_cache(maxsize=1)
def get_source_jobs() -> SourceJobs:
    return SourceJobs()
