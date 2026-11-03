from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from raglab.cli import app


@contextmanager
def _fake_session_scope():
    yield MagicMock()


def test_query_stream_prints_tokens_on_stderr_and_json_on_stdout():
    with patch("raglab.cli.session_scope", _fake_session_scope), patch("raglab.cli.QueryService") as cls:
        service = cls.return_value
        service.stream_answer.return_value = iter(
            [
                ("token", {"text": "Le contrat "}),
                ("token", {"text": "dure un an."}),
                ("done", {"answer": "Le contrat dure un an.", "first_token_ms": 12.0}),
            ]
        )
        result = CliRunner().invoke(app, ["query", "Durée ?", "--corpus", "c", "--stream"])

    assert result.exit_code == 0, result.output
    assert "Le contrat dure un an." in result.stderr
    assert json.loads(result.stdout)["first_token_ms"] == 12.0
    service.query.assert_not_called()


def test_query_without_stream_keeps_the_single_json_answer():
    with patch("raglab.cli.session_scope", _fake_session_scope), patch("raglab.cli.QueryService") as cls:
        cls.return_value.query.return_value.model_dump_json.return_value = '{"answer": "ok"}'
        result = CliRunner().invoke(app, ["query", "?", "--corpus", "c"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"answer": "ok"}
    cls.return_value.stream_answer.assert_not_called()


def test_query_llm_model_option_is_forwarded():
    with patch("raglab.cli.session_scope", _fake_session_scope), patch("raglab.cli.QueryService") as cls:
        service = cls.return_value
        service.query.return_value.model_dump_json.return_value = '{"answer": "ok"}'
        service.stream_answer.return_value = iter([("done", {"answer": "ok"})])
        plain = CliRunner().invoke(app, ["query", "?", "--corpus", "c", "--llm-model", "mistral:7b"])
        streamed = CliRunner().invoke(app, ["query", "?", "--corpus", "c", "--llm-model", "mistral:7b", "--stream"])

    assert plain.exit_code == 0, plain.output
    assert streamed.exit_code == 0, streamed.output
    assert service.query.call_args.kwargs["llm_model"] == "mistral:7b"
    assert service.stream_answer.call_args.kwargs["llm_model"] == "mistral:7b"


def test_query_provider_and_model_alias_are_forwarded():
    with patch("raglab.cli.session_scope", _fake_session_scope), patch("raglab.cli.QueryService") as cls:
        service = cls.return_value
        service.query.return_value.model_dump_json.return_value = '{"answer": "ok"}'
        service.stream_answer.return_value = iter([("done", {"answer": "ok"})])
        plain = CliRunner().invoke(app, ["query", "?", "--corpus", "c", "--provider", "llamacpp", "--model", "gguf"])
        streamed = CliRunner().invoke(
            app, ["query", "?", "--corpus", "c", "--provider", "vllm", "--model", "qwen", "--stream"]
        )

    assert plain.exit_code == 0, plain.output
    assert streamed.exit_code == 0, streamed.output
    assert service.query.call_args.kwargs["llm_provider"] == "llamacpp"
    assert service.query.call_args.kwargs["llm_model"] == "gguf"
    assert service.stream_answer.call_args.kwargs["llm_provider"] == "vllm"
    assert service.stream_answer.call_args.kwargs["llm_model"] == "qwen"


def test_query_without_provider_passes_none():
    with patch("raglab.cli.session_scope", _fake_session_scope), patch("raglab.cli.QueryService") as cls:
        cls.return_value.query.return_value.model_dump_json.return_value = '{"answer": "ok"}'
        result = CliRunner().invoke(app, ["query", "?", "--corpus", "c"])
    assert result.exit_code == 0, result.output
    assert cls.return_value.query.call_args.kwargs["llm_provider"] is None
