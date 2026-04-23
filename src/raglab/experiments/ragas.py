"""LLM-as-judge metrics for generation quality.

Two judges, both driven by an Ollama chat model (same one the pipeline
uses to generate answers — deliberately, so users can compare pipelines
without introducing a second model dependency):

* `FaithfulnessJudge` — does the answer only make claims supported by
  the retrieved chunks? Returns a score in [0, 1].
* `AnswerCorrectnessJudge` — does the answer match the ground-truth
  answer? Returns a score in [0, 1].

Both are robust to LLM noise: the prompts ask for strict JSON, the
parser accepts extra prose around the JSON blob, and any malformed
response degrades gracefully to `None` (caller decides how to
aggregate).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from raglab.config import Settings, get_settings
from raglab.ollama.service import OllamaService

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


@dataclass(slots=True)
class RagasScore:
    """Single judge verdict plus raw payload for later audit."""

    score: float | None
    reason: str | None = None
    details: dict[str, Any] | None = None


_FAITHFULNESS_PROMPT = """You grade ANSWERS for faithfulness. A faithful \
answer makes only claims that are supported by the provided CONTEXT. Any \
claim that cannot be checked against the context is unfaithful, even if \
it happens to be true in the real world.

Return a strict JSON object:
{"score": <float in [0, 1]>, "reason": "<one-sentence rationale>"}

Scoring rubric:
* 1.0 — every claim in the answer is explicitly grounded in the context.
* 0.5 — half the claims can be grounded; the other half is unsupported.
* 0.0 — the answer is mostly ungrounded speculation.

Reply with JSON only. No preamble."""


_ANSWER_CORRECTNESS_PROMPT = """You grade ANSWERS against a GROUND TRUTH \
answer. Score how well the answer captures the same facts, even if the \
wording differs.

Return a strict JSON object:
{"score": <float in [0, 1]>, "reason": "<one-sentence rationale>"}

Scoring rubric:
* 1.0 — semantically equivalent to the ground truth, all key facts match.
* 0.5 — partially correct: core fact matches but with missing details or minor errors.
* 0.0 — wrong, contradictory, or unrelated.

Reply with JSON only. No preamble."""


def _parse_score(answer: str) -> RagasScore:
    if not answer:
        return RagasScore(score=None, reason="empty response")
    match = _JSON_BLOCK_RE.search(answer)
    if match is None:
        return RagasScore(score=None, reason="no JSON in response")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return RagasScore(score=None, reason="invalid JSON")
    if not isinstance(payload, dict):
        return RagasScore(score=None, reason="payload is not an object")
    raw = payload.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return RagasScore(score=None, reason="no numeric score", details=payload)
    score = float(raw)
    if not 0.0 <= score <= 1.0:
        # Still accept, but clamp — LLMs sometimes return 0-10 or 0-100.
        if score > 1.0 and score <= 10.0:
            score /= 10.0
        elif score > 10.0 and score <= 100.0:
            score /= 100.0
        score = max(0.0, min(1.0, score))
    reason = payload.get("reason")
    return RagasScore(
        score=score,
        reason=reason if isinstance(reason, str) else None,
        details=payload,
    )


class _BaseJudge:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        ollama: OllamaService | None = None,
        model: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.ollama = ollama or OllamaService(self.settings)
        self.model = model or self.settings.generation_model

    def _chat(self, *, system: str, user: str) -> RagasScore:
        try:
            result = self.ollama.chat(
                messages=[{"role": "user", "content": user}],
                model=self.model,
                system=system,
                options={"temperature": 0.0, "num_predict": 256},
            )
        except Exception as exc:
            logger.warning("ragas.chat_failed: %s", exc)
            return RagasScore(score=None, reason=f"chat failed: {exc}")
        return _parse_score(result.get("answer", ""))


class FaithfulnessJudge(_BaseJudge):
    """Rate how well the answer stays grounded in the retrieved context."""

    def score(
        self, *, question: str, answer: str, retrieved_texts: list[str]
    ) -> RagasScore:
        if not answer or not answer.strip():
            return RagasScore(score=None, reason="empty answer")
        if not retrieved_texts:
            return RagasScore(score=None, reason="no context")
        # Trim context so the whole prompt fits in most context windows.
        # Each chunk capped at ~600 chars preserves enough signal for
        # grounding checks without blowing past num_ctx on small models.
        joined = "\n---\n".join(t.strip()[:600] for t in retrieved_texts if t.strip())
        user = (
            f"QUESTION:\n{question}\n\n"
            f"CONTEXT:\n{joined}\n\n"
            f"ANSWER:\n{answer}\n\n"
            "Return JSON only."
        )
        return self._chat(system=_FAITHFULNESS_PROMPT, user=user)


class AnswerCorrectnessJudge(_BaseJudge):
    """Rate how well the answer matches the ground-truth answer."""

    def score(
        self, *, question: str, answer: str, ground_truth: str
    ) -> RagasScore:
        if not answer or not answer.strip():
            return RagasScore(score=None, reason="empty answer")
        if not ground_truth or not ground_truth.strip():
            return RagasScore(score=None, reason="no ground truth")
        user = (
            f"QUESTION:\n{question}\n\n"
            f"GROUND TRUTH:\n{ground_truth}\n\n"
            f"ANSWER:\n{answer}\n\n"
            "Return JSON only."
        )
        return self._chat(system=_ANSWER_CORRECTNESS_PROMPT, user=user)
