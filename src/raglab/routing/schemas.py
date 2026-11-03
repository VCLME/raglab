from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, PrivateAttr


class Intent(StrEnum):
    DOCUMENTARY = "documentary"
    CONVERSATIONAL = "conversational"
    OUT_OF_SCOPE = "out_of_scope"


class LanguageDecision(BaseModel):
    # fr, pt or other.
    language: str
    # Marker counts per language (lexical method) or similarity to the nearest
    # example of each language (embedding fallback).
    scores: dict[str, float] = Field(default_factory=dict)
    # "lexical" when function words / diacritics decided, "embedding" when the
    # text had no marker and the nearest labelled example decided.
    method: str


class IntentDecision(BaseModel):
    intent: Intent
    # Cosine similarity of the question to each intent's nearest centroid.
    scores: dict[str, float] = Field(default_factory=dict)
    # How much the best non-documentary intent must beat `documentary`.
    margin: float
    nearest_example: str | None = None


class CorpusCandidate(BaseModel):
    corpus_name: str
    index_run_id: str
    score: float


class CorpusDecision(BaseModel):
    # Corpus actually queried (the requested one when the caller named it).
    corpus_name: str | None
    index_run_id: str | None
    # Corpus the centroids point to, even when the caller forced another.
    suggested_corpus: str | None
    candidates: list[CorpusCandidate] = Field(default_factory=list)
    # Best score minus second best (0 with a single candidate).
    margin: float = 0.0
    # "routed" (chosen by centroids), "requested" (caller's choice kept) or
    # "none" (no compatible index).
    source: str = "routed"


class AbstentionDecision(BaseModel):
    abstain: bool
    reason: str | None = None
    # Score compared to the threshold: dense cosine now, reranker later.
    score_source: str
    best_score: float | None = None
    threshold: float
    # "legal_citation" when the question cites a law: never declined.
    override: str | None = None


class RoutingDecision(BaseModel):
    language: LanguageDecision
    intent: IntentDecision
    corpus: CorpusDecision
    # Label of the law cited by the question ("art. 49 — Lei nº 8078"), if any.
    legal_citation: str | None = None
    abstention: AbstentionDecision | None = None
    # True when the answer comes from the documents (generation runs).
    answer_from_documents: bool = True
    # Canned answer used instead of generation when the router declines.
    fallback_answer: str | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    # Question vector, reused by retrieval on the routed index run; kept out
    # of the API payload.
    _query_embedding: list[float] | None = PrivateAttr(default=None)

    @property
    def query_embedding(self) -> list[float] | None:
        return self._query_embedding
