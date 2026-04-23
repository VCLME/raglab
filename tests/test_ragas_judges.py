from __future__ import annotations

from unittest.mock import MagicMock

from raglab.experiments.ragas import (
    AnswerCorrectnessJudge,
    FaithfulnessJudge,
    RagasScore,
    _parse_score,
)


def test_parse_score_reads_valid_json():
    r = _parse_score('{"score": 0.7, "reason": "mostly grounded"}')
    assert r.score == 0.7
    assert r.reason == "mostly grounded"


def test_parse_score_handles_prose_around_json():
    r = _parse_score("Here is my verdict:\n{\"score\": 1, \"reason\": \"ok\"}\nDone.")
    assert r.score == 1.0


def test_parse_score_clamps_out_of_range():
    # LLMs sometimes hand 0-10 or 0-100 scales; we normalise.
    assert _parse_score('{"score": 7}').score == 0.7
    assert _parse_score('{"score": 85}').score == 0.85
    assert _parse_score('{"score": -0.3}').score == 0.0
    assert _parse_score('{"score": 1.8}').score == 0.18


def test_parse_score_returns_none_on_garbage():
    assert _parse_score("").score is None
    assert _parse_score("nothing json here").score is None
    assert _parse_score("{incomplete").score is None
    # non-numeric score must not slip through
    assert _parse_score('{"score": "high"}').score is None


def test_faithfulness_short_circuits_without_context():
    ollama = MagicMock()
    judge = FaithfulnessJudge(ollama=ollama)
    r = judge.score(question="q", answer="a", retrieved_texts=[])
    assert r.score is None
    ollama.chat.assert_not_called()


def test_faithfulness_short_circuits_on_empty_answer():
    ollama = MagicMock()
    judge = FaithfulnessJudge(ollama=ollama)
    r = judge.score(question="q", answer="   ", retrieved_texts=["context"])
    assert r.score is None
    ollama.chat.assert_not_called()


def test_faithfulness_passes_chunks_to_llm():
    ollama = MagicMock()
    ollama.chat.return_value = {"answer": '{"score": 0.8, "reason": "grounded"}'}
    judge = FaithfulnessJudge(ollama=ollama)
    r = judge.score(
        question="Where was Böhme born?",
        answer="Görlitz.",
        retrieved_texts=["Jakob Böhme was born in Görlitz in 1575."],
    )
    assert r.score == 0.8
    assert ollama.chat.call_count == 1
    # The chunk must appear in the user prompt
    user_prompt = ollama.chat.call_args.kwargs["messages"][0]["content"]
    assert "Görlitz" in user_prompt


def test_faithfulness_returns_none_on_chat_failure():
    ollama = MagicMock()
    ollama.chat.side_effect = RuntimeError("boom")
    judge = FaithfulnessJudge(ollama=ollama)
    r = judge.score(question="q", answer="a", retrieved_texts=["c"])
    assert r.score is None
    assert r.reason and "boom" in r.reason


def test_answer_correctness_requires_ground_truth():
    ollama = MagicMock()
    judge = AnswerCorrectnessJudge(ollama=ollama)
    r = judge.score(question="q", answer="hello", ground_truth="")
    assert r.score is None
    ollama.chat.assert_not_called()


def test_answer_correctness_returns_score():
    ollama = MagicMock()
    ollama.chat.return_value = {"answer": '{"score": 0.5, "reason": "partial"}'}
    judge = AnswerCorrectnessJudge(ollama=ollama)
    r = judge.score(question="q", answer="a", ground_truth="ref")
    assert r.score == 0.5


def test_ragas_score_dataclass_defaults():
    assert RagasScore(score=0.5).reason is None
    assert RagasScore(score=None, reason="x").details is None
