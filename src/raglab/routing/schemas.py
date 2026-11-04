from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, PrivateAttr

if TYPE_CHECKING:
    from raglab.retrieval.citations import Citation


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
    # "centroids" (default) or "knn" (`routing_intent_knn`, docs/intentions.md):
    # with knn, `scores` are the mean similarities of the k nearest
    # neighbours of each intent, and `documentary_margin` the documentary
    # neighbours' minus the others' (declined below -margin).
    method: str = "centroids"
    documentary_margin: float | None = None
    # kNN method with a logistic model in the calibration file: probability
    # that the question is not documentary (declined above its threshold).
    not_documentary_probability: float | None = None


class CorpusCandidate(BaseModel):
    corpus_name: str
    index_run_id: str
    score: float
    # Cross-language routing: score of the question translated into this
    # corpus's language, when it was rescored (`score` is then the best of both).
    original_score: float | None = None
    translated_score: float | None = None


class CorpusDecision(BaseModel):
    # Corpus actually queried (the requested one when the caller named it).
    corpus_name: str | None
    index_run_id: str | None
    # Corpus the centroids point to, even when the caller forced another.
    suggested_corpus: str | None
    candidates: list[CorpusCandidate] = Field(default_factory=list)
    # Best score minus second best (0 with a single candidate).
    margin: float = 0.0
    # "routed" (chosen by centroids), "citation" (best-scored corpus holding
    # the text the question cites), "requested" (caller's choice kept) or
    # "none" (no compatible index).
    source: str = "routed"
    # What the candidates were scored on: "chunks" (centroid of the corpus's
    # passages) or "examples" (centroids of example questions per language).
    scoring: str = "chunks"


class AbstentionDecision(BaseModel):
    abstain: bool
    reason: str | None = None
    # Score compared to the threshold: dense cosine or cross-encoder score.
    score_source: str
    best_score: float | None = None
    # Cross-language routing: dense score of the question translated into the
    # corpus language (`best_score` is then the best of both).
    translated_score: float | None = None
    # None: no calibrated threshold for this corpus and score source.
    threshold: float | None = None
    # "legal_citation" when the question cites a law: never declined.
    override: str | None = None
    # Joint rule (`routing_intent_knn`): sum of the log ranks of the kNN
    # documentary margin and of the dense score among the calibration
    # questions of this (corpus, language), and the value it must reach.
    # Set only when that pair is calibrated; it then replaces `threshold`.
    joint_score: float | None = None
    joint_threshold: float | None = None


class RoutingDecision(BaseModel):
    language: LanguageDecision
    intent: IntentDecision
    corpus: CorpusDecision
    # Label of the text cited by the question ("art. 49 — Lei nº 8078",
    # "art. L. 221-18 — Code de la consommation", "Article 32 — GDPR").
    legal_citation: str | None = None
    # Whether the queried index holds the cited text: only then is the
    # question never declined.
    legal_citation_found: bool = False
    abstention: AbstentionDecision | None = None
    # True when the answer comes from the documents (generation runs).
    answer_from_documents: bool = True
    # Canned answer used instead of generation when the router declines.
    fallback_answer: str | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    # Question vector, reused by retrieval on the routed index run; kept out
    # of the API payload.
    _query_embedding: list[float] | None = PrivateAttr(default=None)
    # Parsed citation (`raglab.retrieval.citations.Citation`); typed Any to
    # keep this module free of the retrieval imports.
    _citation: Any = PrivateAttr(default=None)

    @property
    def query_embedding(self) -> list[float] | None:
        return self._query_embedding

    @property
    def citation(self) -> Citation | None:
        return self._citation
