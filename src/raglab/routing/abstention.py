"""Post-retrieval abstention: refuse when the best passage scores too low."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from raglab.routing.schemas import AbstentionDecision, Intent

ABSTENTION_ANSWERS = {
    "fr": "Je ne trouve pas cela dans les documents.",
    "pt": "Não encontrei isso nos documentos.",
}
CONVERSATIONAL_ANSWERS = {
    "fr": "Je réponds aux questions sur les documents indexés. Posez-moi une question sur leur contenu.",
    "pt": "Respondo a perguntas sobre os documentos indexados. Faça uma pergunta sobre o conteúdo deles.",
}

SCORE_SOURCES = ("dense", "rerank")


def chunk_score(chunk: Any, source: str) -> float | None:
    """Score of one retrieved chunk for the abstention test.

    - dense: cosine similarity. Hybrid retrieval (9.2) keeps it in
      `dense_score` while `score` holds the fused RRF value, which has no
      absolute meaning; without hybrid, `score` is the cosine similarity.
    - rerank: cross-encoder score (9.3), read from `rerank_score` when the
      reranker ran, None otherwise.
    """
    if source == "dense":
        dense = getattr(chunk, "dense_score", None)
        return float(dense) if dense is not None else float(chunk.score)
    if source == "rerank":
        value = getattr(chunk, "rerank_score", None)
        return float(value) if value is not None else None
    raise ValueError(f"Source de score inconnue: {source} (attendu: {', '.join(SCORE_SOURCES)})")


def best_score(chunks: Sequence[Any], source: str) -> float | None:
    values = [value for value in (chunk_score(chunk, source) for chunk in chunks) if value is not None]
    return max(values) if values else None


def threshold_for(settings: Any, corpus_name: str | None) -> float:
    """Per-corpus threshold when one is set, the global one otherwise.

    Dense scores do not share a scale across corpora (short legal passages
    score higher than encyclopedic paragraphs), hence per-corpus values,
    calibrated by `raglab experiment routing`.
    """
    return float(settings.routing_abstention_thresholds.get(corpus_name or "", settings.routing_abstention_threshold))


def decide_abstention(
    *,
    intent: Intent,
    score: float | None,
    threshold: float,
    score_source: str,
) -> AbstentionDecision:
    if intent != Intent.DOCUMENTARY:
        reason: str | None = f"intent:{intent.value}"
    elif score is None:
        reason = "no_passage"
    elif score < threshold:
        reason = "low_score"
    else:
        reason = None
    return AbstentionDecision(
        abstain=reason is not None,
        reason=reason,
        score_source=score_source,
        best_score=round(score, 4) if score is not None else None,
        threshold=threshold,
    )


def fallback_answer(intent: Intent, language: str) -> str:
    answers = CONVERSATIONAL_ANSWERS if intent == Intent.CONVERSATIONAL else ABSTENTION_ANSWERS
    return answers.get(language, answers["fr"])
