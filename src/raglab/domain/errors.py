from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextvars import copy_context

# Stages of the query pipeline, as named in `QueryResponse.timings_ms`.
QUERY_STAGES = ("embed", "retrieval", "rerank", "generation")

# Shared pool for stages that cannot be cancelled natively (local embedding on
# CPU/GPU). A timed-out call keeps running in its worker until it returns; the
# pool size caps how many such orphans can pile up.
_STAGE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="raglab-stage")


class StageTimeoutError(Exception):
    """A query stage overran its budget (mapped to HTTP 504 by the API)."""

    def __init__(self, stage: str, timeout_seconds: float, message: str | None = None):
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        super().__init__(
            message
            or (
                f"Timeout a l'etape {stage} : pas de resultat apres {timeout_seconds:g} s. "
                f"Augmente RAGLAB_{stage.upper()}_TIMEOUT_SECONDS si la charge est normale."
            )
        )


def run_with_timeout[T](stage: str, timeout_seconds: float, fn: Callable[[], T]) -> T:
    """Run `fn` in a worker thread and raise `StageTimeoutError` past the budget.

    The context (request id) is copied into the worker so its logs stay
    correlated. A budget of 0 or less runs `fn` inline without a limit.
    """
    if timeout_seconds <= 0:
        return fn()
    future = _STAGE_POOL.submit(copy_context().run, fn)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise StageTimeoutError(stage, timeout_seconds) from exc
