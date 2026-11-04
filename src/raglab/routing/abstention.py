"""Post-retrieval abstention: refuse when the best passage scores too low."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from raglab.routing.schemas import AbstentionDecision, Intent

ABSTENTION_ANSWERS = {
    "fr": "Je ne trouve pas cela dans les documents.",
    "pt": "Não encontrei isso nos documentos.",
    "en": "I cannot find this in the documents.",
}
CONVERSATIONAL_ANSWERS = {
    "fr": "Je réponds aux questions sur les documents indexés. Posez-moi une question sur leur contenu.",
    "pt": "Respondo a perguntas sobre os documentos indexados. Faça uma pergunta sobre o conteúdo deles.",
    "en": "I answer questions about the indexed documents. Ask me about their content.",
}

SCORE_SOURCES = ("dense", "rerank")
# Set on chunks whose `score` is not a cosine similarity.
_NON_COSINE_FIELDS = ("lexical_score", "fused_score", "rerank_score", "citation_match")


def chunk_score(chunk: Any, source: str) -> float | None:
    """Score of one retrieved chunk for the abstention test.

    - dense: cosine similarity. Hybrid retrieval (9.2) keeps it in
      `dense_score` while `score` holds the fused RRF value, which has no
      absolute meaning; a chunk found only by BM25 (or pinned by the
      citation resolver) has no cosine and is skipped. A plain chunk without
      those fields carries the cosine in `score`.
    - rerank: cross-encoder score (9.3), read from `rerank_score` when the
      reranker ran, None otherwise.
    """
    if source == "dense":
        dense = getattr(chunk, "dense_score", None)
        if dense is not None:
            return float(dense)
        if any(getattr(chunk, name, None) is not None for name in _NON_COSINE_FIELDS):
            return None
        return float(chunk.score)
    if source == "rerank":
        value = getattr(chunk, "rerank_score", None)
        return float(value) if value is not None else None
    raise ValueError(f"Source de score inconnue: {source} (attendu: {', '.join(SCORE_SOURCES)})")


def best_score(chunks: Sequence[Any], source: str) -> float | None:
    values = [value for value in (chunk_score(chunk, source) for chunk in chunks) if value is not None]
    return max(values) if values else None


def threshold_for(settings: Any, corpus_name: str | None, source: str = "dense") -> float | None:
    """Threshold of the queried corpus for this score source.

    Dense scores do not share a scale across corpora (short legal passages
    score higher than encyclopedic paragraphs), hence per-corpus values,
    calibrated by `raglab experiment routing`. A dense corpus without its own
    value falls back to the global one. Re-ranker scores are calibrated
    separately and never borrow a dense value: a corpus without a re-ranker
    threshold gets None (no abstention on score, only on intent).
    """
    if source == "rerank":
        value = settings.routing_rerank_abstention_thresholds.get(corpus_name or "")
        return float(value) if value is not None else None
    return float(settings.routing_abstention_thresholds.get(corpus_name or "", settings.routing_abstention_threshold))


def decide_abstention(
    *,
    intent: Intent,
    score: float | None,
    threshold: float | None,
    score_source: str,
    legal_citation: bool = False,
) -> AbstentionDecision:
    """`legal_citation`: the question cites a text the queried index holds
    ("art. 49 da Lei nº 8.078", "article L. 221-18 du code de la
    consommation", "Article 32 GDPR"). It is never declined: it names a
    document, so it is documentary by construction, and its passages come
    from the citation resolver rather than from similarity (identifiers
    embed poorly, so the dense score is low on exactly these questions)."""
    if legal_citation:
        reason: str | None = None
    elif intent != Intent.DOCUMENTARY:
        reason = f"intent:{intent.value}"
    elif score is None:
        reason = "no_passage"
    elif threshold is not None and score < threshold:
        reason = "low_score"
    else:
        reason = None
    return AbstentionDecision(
        abstain=reason is not None,
        reason=reason,
        score_source=score_source,
        best_score=round(score, 4) if score is not None else None,
        threshold=threshold,
        override="legal_citation" if legal_citation else None,
    )


def fallback_answer(intent: Intent, language: str) -> str:
    answers = CONVERSATIONAL_ANSWERS if intent == Intent.CONVERSATIONAL else ABSTENTION_ANSWERS
    return answers.get(language, answers["fr"])
