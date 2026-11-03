from __future__ import annotations

import json
import time
from unittest.mock import Mock, patch

import pytest
import requests

from raglab.config import Settings
from raglab.domain.errors import StageTimeoutError
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.service import OllamaGenerator
from raglab.ollama.errors import (
    OllamaError,
    OllamaModelNotFoundError,
    OllamaOutOfMemoryError,
    OllamaTimeoutError,
    OllamaUnreachableError,
    classify_error,
    translate_transport_errors,
)
from raglab.ollama.service import OllamaService


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        file_name="law.txt",
        source_path="data/documents/law.txt",
        chunk_text="Article 1. Le contrat est valable un an.",
        score=0.9,
        rank=1,
    )


def _http_error_response(status: int, body: str) -> Mock:
    response = Mock()
    response.status_code = status
    response.text = body
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


# --- classification -------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "model requires more system memory (12.3 GiB) than is available (7.1 GiB)",
        "llama runner process has terminated: cudaMalloc failed: out of memory",
        "CUDA error: out of memory",
        "unable to allocate CUDA0 buffer",
    ],
)
def test_out_of_memory_messages_are_recognised(message):
    error = classify_error(message, status_code=500, model="qwen2.5:7b", retry_after=30)
    assert isinstance(error, OllamaOutOfMemoryError)
    assert error.status_code == 503
    assert error.retry_after == 30
    assert error.cause == message


def test_missing_model_is_recognised_from_404_and_from_stream():
    from_http = classify_error("model 'x' not found, try pulling it first", status_code=404, model="x", retry_after=1)
    in_stream = classify_error('model "x" not found', status_code=None, model="x", retry_after=1)
    assert isinstance(from_http, OllamaModelNotFoundError)
    assert isinstance(in_stream, OllamaModelNotFoundError)
    assert from_http.status_code == 424
    assert "raglab ollama pull --model x" in str(from_http)


def test_other_errors_stay_generic():
    error = classify_error("something broke", status_code=500, model="x", retry_after=1)
    assert type(error) is OllamaError
    assert error.status_code == 502
    assert "HTTP 500" in str(error)


def test_typed_errors_are_still_runtime_errors():
    # Callers that caught RuntimeError for a missing model keep working.
    assert issubclass(OllamaModelNotFoundError, RuntimeError)
    assert issubclass(OllamaTimeoutError, StageTimeoutError)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (requests.exceptions.ConnectTimeout("connect timed out"), OllamaUnreachableError),
        (requests.exceptions.ReadTimeout("read timed out"), OllamaTimeoutError),
        (requests.exceptions.ConnectionError("Connection refused"), OllamaUnreachableError),
        # requests turns a read timeout during iter_lines into a ConnectionError.
        (requests.exceptions.ConnectionError("HTTPConnectionPool: Read timed out."), OllamaTimeoutError),
    ],
)
def test_transport_errors_are_typed(raised, expected):
    with pytest.raises(expected):
        with translate_transport_errors(base_url="http://ollama:11434", model="m", timeout_seconds=5):
            raise raised


# --- generator, non-streaming ---------------------------------------------


def test_generate_answer_raises_typed_oom_error():
    generator = OllamaGenerator(Settings(ollama_retry_after_seconds=17))
    response = _http_error_response(500, json.dumps({"error": "model requires more system memory"}))
    with patch("raglab.generation.service.requests.post", return_value=response):
        with pytest.raises(OllamaOutOfMemoryError) as excinfo:
            generator.generate_answer("?", [_chunk()])
    assert excinfo.value.retry_after == 17


def test_generate_answer_turns_connection_refused_into_unreachable():
    generator = OllamaGenerator(Settings(ollama_base_url="http://nowhere:1"))
    with patch(
        "raglab.generation.service.requests.post",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        with pytest.raises(OllamaUnreachableError) as excinfo:
            generator.generate_answer("?", [_chunk()])
    assert "http://nowhere:1" in str(excinfo.value)


def test_generate_answer_timeout_names_generation_stage():
    generator = OllamaGenerator(Settings(generation_timeout_seconds=7))
    with patch("raglab.generation.service.requests.post", side_effect=requests.exceptions.ReadTimeout("slow")):
        with pytest.raises(OllamaTimeoutError) as excinfo:
            generator.generate_answer("?", [_chunk()])
    assert excinfo.value.stage == "generation"
    assert excinfo.value.timeout_seconds == 7


# --- generator, streaming (mocked Ollama NDJSON stream) ---------------------


def _stream_response(lines: list[dict], *, delay: float = 0.0) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None

    def iter_lines():
        for line in lines:
            if delay:
                time.sleep(delay)
            yield json.dumps(line).encode()
            yield b""  # keep-alive blank lines are ignored

    response.iter_lines.side_effect = iter_lines
    return response


def test_stream_answer_yields_fragments_and_final_stats():
    generator = OllamaGenerator(Settings(generation_model="qwen2.5:7b"))
    response = _stream_response(
        [
            {"message": {"content": "Le contrat "}, "done": False},
            {"message": {"content": "dure un an."}, "done": False},
            {
                "message": {"content": ""},
                "done": True,
                "eval_count": 6,
                "eval_duration": 200_000_000,
                "prompt_eval_count": 120,
                "prompt_eval_duration": 100_000_000,
            },
        ]
    )
    with patch("raglab.generation.service.requests.post", return_value=response) as post:
        pieces = list(generator.stream_answer("Durée ?", [_chunk()]))

    assert pieces == ["Le contrat ", "dure un an."]
    assert post.call_args.kwargs["stream"] is True
    assert post.call_args.kwargs["json"]["stream"] is True
    assert generator.last_stats == {
        "output_tokens": 6.0,
        "prompt_tokens": 120.0,
        "tokens_per_second": 30.0,
        "prompt_tokens_per_second": 1200.0,
    }
    response.close.assert_called_once()


def test_stream_answer_without_chunks_yields_fallback_without_calling_ollama():
    generator = OllamaGenerator(Settings(generation_no_context_answer="Contexte insuffisant."))
    with patch("raglab.generation.service.requests.post") as post:
        assert list(generator.stream_answer("?", [])) == ["Contexte insuffisant."]
    post.assert_not_called()


def test_stream_answer_raises_on_in_stream_error():
    generator = OllamaGenerator(Settings())
    response = _stream_response(
        [
            {"message": {"content": "Début"}, "done": False},
            {"error": "llama runner process has terminated: CUDA error: out of memory"},
        ]
    )
    with patch("raglab.generation.service.requests.post", return_value=response):
        stream = generator.stream_answer("?", [_chunk()])
        assert next(stream) == "Début"
        with pytest.raises(OllamaOutOfMemoryError):
            next(stream)
    response.close.assert_called_once()


def test_stream_answer_missing_model_before_first_token():
    generator = OllamaGenerator(Settings(generation_model="ghost:1b"))
    response = _http_error_response(404, json.dumps({"error": "model 'ghost:1b' not found"}))
    with patch("raglab.generation.service.requests.post", return_value=response):
        with pytest.raises(OllamaModelNotFoundError) as excinfo:
            list(generator.stream_answer("?", [_chunk()]))
    assert "ghost:1b" in str(excinfo.value)


def test_stream_answer_enforces_the_total_generation_budget():
    # Each token arrives well within the per-read timeout, but the whole
    # answer overruns the budget.
    generator = OllamaGenerator(Settings(generation_timeout_seconds=0))
    generator.settings = generator.settings.model_copy(update={"generation_timeout_seconds": 0.05})
    response = _stream_response(
        [{"message": {"content": f"t{i} "}, "done": False} for i in range(20)],
        delay=0.02,
    )
    with patch("raglab.generation.service.requests.post", return_value=response):
        with pytest.raises(OllamaTimeoutError) as excinfo:
            list(generator.stream_answer("?", [_chunk()]))
    assert excinfo.value.stage == "generation"


# --- OllamaService ----------------------------------------------------------


def test_service_status_uses_the_given_timeout():
    service = OllamaService(Settings(generation_timeout_seconds=120))
    response = Mock()
    response.json.return_value = {"models": []}
    response.raise_for_status.return_value = None
    with patch("raglab.ollama.service.requests.get", return_value=response) as get:
        service.status(timeout=2.5)
    assert get.call_args.kwargs["timeout"] == 2.5


def test_service_status_unreachable_is_typed():
    service = OllamaService(Settings())
    with patch("raglab.ollama.service.requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
        with pytest.raises(OllamaUnreachableError):
            service.status()
