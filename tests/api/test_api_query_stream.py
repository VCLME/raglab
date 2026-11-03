from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from raglab.domain.enums import ChunkingStrategy
from raglab.domain.errors import StageTimeoutError
from raglab.domain.schemas import RetrievedChunk
from raglab.ollama.errors import OllamaOutOfMemoryError
from raglab.retrieval.service import QueryService, RetrievalOutcome


def _outcome(question: str = "Que dit la loi ?") -> RetrievalOutcome:
    return RetrievalOutcome(
        question=question,
        corpus_name="lexml",
        top_k=3,
        filters=None,
        index_run=SimpleNamespace(id="11111111-1111-1111-1111-111111111111", strategy="traditional"),
        retrieved=[
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                file_name="loi.txt",
                source_path="data/loi.txt",
                chunk_text="extrait",
                score=0.91,
                rank=1,
            )
        ],
        started=0.0,
        timings_ms={"embed": 12.0, "retrieval": 3.0},
    )


# Educational-mode events, additive to the 9.5 sequence (see test_api_query_stages.py).
STAGE_EVENTS = {"pipeline", "stage"}


def parse_sse(text: str, *, with_stages: bool = False) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if with_stages or name not in STAGE_EVENTS:
            events.append((name, data))
    return events


class FakeGenerator:
    """Stands in for OllamaGenerator: yields fragments, may fail midway."""

    def __init__(self, pieces, *, fail_with: Exception | None = None):
        self.pieces = pieces
        self.fail_with = fail_with
        self.last_stats: dict[str, float] = {}
        self.models: list[str | None] = []

    def stream_answer(self, question, chunks, *, model=None):
        self.models.append(model)
        yield from self.pieces
        if self.fail_with is not None:
            raise self.fail_with
        self.last_stats = {"output_tokens": 3.0, "tokens_per_second": 42.0}


@pytest.fixture
def stream_service():
    """Patch retrieval and generation, keep the real event sequencing."""

    def _install(generator: FakeGenerator, outcome: RetrievalOutcome | Exception | None = None):
        retrieve = patch.object(
            QueryService,
            "retrieve",
            side_effect=outcome if isinstance(outcome, Exception) else None,
            return_value=outcome or _outcome(),
        )
        gen = patch("raglab.retrieval.service.OllamaGenerator", return_value=generator)
        return retrieve, gen

    return _install


def _post(client, **body):
    payload = {"question": "Que dit la loi ?", "corpus": "lexml", "top_k": 3, **body}
    return client.post("/api/query/stream", json=payload)


def test_stream_sends_retrieval_then_tokens_then_done(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator(["La loi ", "dispose ", "que…"]))
    with retrieve, gen:
        response = _post(client)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["X-Request-ID"]
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == ["retrieval", "token", "token", "token", "done"]

    retrieval = events[0][1]
    assert retrieval["retrieved_chunks"][0]["score"] == 0.91
    assert retrieval["timings_ms"] == {"embed": 12.0, "retrieval": 3.0}
    assert retrieval["answer"] is None
    assert retrieval["strategy"] == ChunkingStrategy.TRADITIONAL.value

    assert [data["text"] for name, data in events if name == "token"] == ["La loi ", "dispose ", "que…"]

    done = events[-1][1]
    assert done["answer"] == "La loi dispose que…"
    assert set(done["timings_ms"]) == {"embed", "retrieval", "generation"}
    assert done["generation_stats"] == {"output_tokens": 3.0, "tokens_per_second": 42.0}
    assert done["first_token_ms"] is not None
    assert done["retrieved_chunks"] == retrieval["retrieved_chunks"]


def test_stream_forwards_llm_model_to_the_generator(client, stream_service):
    generator = FakeGenerator(["ok"])
    retrieve, gen = stream_service(generator)
    with retrieve, gen:
        _post(client, llm_model="mistral:7b")
        _post(client)
    assert generator.models == ["mistral:7b", None]


def test_stream_without_generation_ends_after_retrieval(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator(["never"]))
    with retrieve, gen:
        events = parse_sse(_post(client, generate=False).text)
    assert [name for name, _ in events] == ["retrieval", "done"]
    assert events[-1][1]["answer"] is None
    assert events[-1][1]["first_token_ms"] is None


def test_stream_reports_generation_failure_as_error_event(client, stream_service):
    retrieve, gen = stream_service(
        FakeGenerator(["Début "], fail_with=OllamaOutOfMemoryError("qwen2.5:7b", retry_after=30))
    )
    with retrieve, gen:
        response = _post(client)

    assert response.status_code == 200  # already sent when generation fails
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["retrieval", "token", "error"]
    error = events[-1][1]
    assert error["status"] == 503
    assert error["retry_after"] == 30
    assert error["error"] == "OllamaOutOfMemoryError"


def test_stream_reports_unexpected_failure_without_leaking_it(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator([], fail_with=KeyError("secret internals")))
    with retrieve, gen:
        events = parse_sse(_post(client).text)
    assert events[-1] == ("error", {"status": 500, "detail": "Erreur interne pendant la generation."})


def test_stream_retrieval_errors_keep_their_http_status(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator([]), ValueError("Aucun index_run compatible n'a ete trouve"))
    with retrieve, gen:
        response = _post(client)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")


def test_stream_embed_timeout_is_a_504_before_streaming(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator([]), StageTimeoutError("embed", 30))
    with retrieve, gen:
        response = _post(client)
    assert response.status_code == 504
    assert response.json()["stage"] == "embed"


def test_plain_query_endpoint_is_unchanged(client):
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.return_value = _outcome().response(answer="ok", elapsed_ms=1.0)
        response = client.post("/api/query", json={"question": "?", "corpus": "lexml"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json()["answer"] == "ok"


# Educational mode: `pipeline` and `stage` events (additive).


def _stage_events(events):
    return [(data["stage"], data["status"]) for name, data in events if name == "stage"]


def test_stream_emits_pipeline_then_stage_events_around_each_stage(client, stream_service):
    outcome = _outcome()
    outcome.query_embedding = [0.5, -0.25, 0.125] + [0.0] * 381
    retrieve, gen = stream_service(FakeGenerator(["La loi ", "dispose."]), outcome)
    with retrieve, gen:
        events = parse_sse(_post(client).text, with_stages=True)

    names = [name for name, _ in events]
    assert names[0] == "pipeline"
    assert events[0][1] == {"stages": ["embed", "retrieval", "prompt", "generation"]}
    # Retrieval-side stages are replayed before the `retrieval` event, the
    # generation stage wraps the tokens, `done` stays last.
    assert names == [
        "pipeline",
        "stage", "stage", "stage", "stage",
        "retrieval",
        "stage", "stage", "stage",
        "token", "token",
        "stage",
        "done",
    ]  # fmt: skip
    assert _stage_events(events) == [
        ("embed", "start"),
        ("embed", "end"),
        ("retrieval", "start"),
        ("retrieval", "end"),
        ("prompt", "start"),
        ("prompt", "end"),
        ("generation", "start"),
        ("generation", "end"),
    ]

    stages = {(d["stage"], d["status"]): d for name, d in events if name == "stage"}
    embed = stages[("embed", "end")]
    assert embed["live"] is False
    assert embed["duration_ms"] == 12.0
    assert embed["counts"] == {"dimension": 384}
    assert embed["data"]["head"][:3] == [0.5, -0.25, 0.125]
    assert len(embed["data"]["head"]) == 8

    retrieval = stages[("retrieval", "end")]
    assert retrieval["t_ms"] == 15.0  # replayed: embed 12 ms + search 3 ms
    assert retrieval["duration_ms"] == 3.0
    assert retrieval["counts"] == {"chunks_out": 1, "top_k": 3}
    assert retrieval["data"]["top_chunks"] == [{"rank": 1, "file_name": "loi.txt", "excerpt": "extrait", "score": 0.91}]

    prompt = stages[("prompt", "end")]
    assert prompt["live"] is True
    assert prompt["counts"]["chunks_in"] == 1
    assert "Que dit la loi ?" in prompt["data"]["user_prompt"]

    generation = stages[("generation", "end")]
    assert generation["counts"]["output_tokens"] == 3.0
    assert generation["counts"]["tokens_per_second"] == 42.0
    assert generation["counts"]["fragments"] == 2
    assert generation["counts"]["first_token_ms"] is not None
    assert generation["data"]["model"]
    assert generation["data"]["provider"] == "ollama"


def test_stream_without_generation_has_no_generation_stages(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator(["never"]))
    with retrieve, gen:
        events = parse_sse(_post(client, generate=False).text, with_stages=True)
    assert events[0][1] == {"stages": ["embed", "retrieval"]}
    assert [stage for stage, status in _stage_events(events) if status == "end"] == ["embed", "retrieval"]
    assert [name for name, _ in events][-2:] == ["retrieval", "done"]


def test_generation_failure_leaves_the_generation_stage_open(client, stream_service):
    retrieve, gen = stream_service(FakeGenerator(["Début "], fail_with=KeyError("boom")))
    with retrieve, gen:
        events = parse_sse(_post(client).text, with_stages=True)
    assert _stage_events(events)[-1] == ("generation", "start")
    assert events[-1][0] == "error"
