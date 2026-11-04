from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import get_index_run
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.errors import run_with_timeout
from raglab.embeddings.factory import build_embedding_provider
from raglab.retrieval.citations import Citation, parse_citation
from raglab.routing.abstention import best_score, decide_abstention, fallback_answer, threshold_for
from raglab.routing.citation import cited_text_in_run
from raglab.routing.corpus import embedding_identity, list_candidate_runs, score_corpora
from raglab.routing.intent import get_intent_classifier, normalize
from raglab.routing.language import detect_language
from raglab.routing.schemas import CorpusDecision, RoutingDecision


def _ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 3)


class QueryRouter:
    """Language, intent and corpus before retrieval; abstention after.

    Everything rests on the default embedder (multilingual-e5-small, cached
    by the factory): one question embedding, dot products with a few
    centroids, no LLM call. Every decision carries the scores it was made on.
    """

    def __init__(self, session: Session, settings: Settings | None = None, *, embedder: Any = None):
        self.session = session
        self.settings = settings or get_settings()
        self.embedder = embedder or build_embedding_provider(self.settings)

    def route(
        self,
        question: str,
        *,
        corpus_name: str | None = None,
        index_run_id: str | None = None,
        strategy: ChunkingStrategy | None = None,
        candidate_corpora: list[str] | None = None,
    ) -> RoutingDecision:
        started = perf_counter()
        raw_embedding = run_with_timeout(
            "embed", self.settings.embed_timeout_seconds, lambda: self.embedder.embed_query(question)
        )
        embedding = normalize(raw_embedding)
        embedded = perf_counter()
        classifier = get_intent_classifier(self.embedder)
        language = detect_language(question, fallback=classifier.language_similarities(embedding))
        detected = perf_counter()
        intent = classifier.classify(embedding, margin=self.settings.routing_intent_margin)
        classified = perf_counter()
        citation = parse_citation(question)
        corpus = self._choose_corpus(
            embedding,
            corpus_name=corpus_name,
            index_run_id=index_run_id,
            strategy=strategy,
            candidate_corpora=candidate_corpora,
            citation=citation,
        )
        routed = perf_counter()
        decision = RoutingDecision(
            language=language,
            intent=intent,
            corpus=corpus,
            legal_citation=citation.label() if citation else None,
            timings_ms={
                "embed": _ms(started, embedded),
                "language": _ms(embedded, detected),
                "intent": _ms(detected, classified),
                "corpus": _ms(classified, routed),
                "total": _ms(started, routed),
            },
        )
        decision._query_embedding = list(raw_embedding)
        decision._citation = citation
        return decision

    def _choose_corpus(
        self,
        embedding,
        *,
        corpus_name: str | None,
        index_run_id: str | None,
        strategy: ChunkingStrategy | None,
        candidate_corpora: list[str] | None,
        citation: Citation | None = None,
    ) -> CorpusDecision:
        runs = list_candidate_runs(
            self.session,
            **embedding_identity(self.settings),
            strategy=strategy,
            corpus_names=candidate_corpora,
        )
        candidates, margin = score_corpora(self.session, runs, embedding)
        suggested = candidates[0] if candidates else None
        if index_run_id:
            run = get_index_run(self.session, index_run_id)
            return CorpusDecision(
                corpus_name=run.corpus.name if run else corpus_name,
                index_run_id=index_run_id,
                suggested_corpus=suggested.corpus_name if suggested else None,
                candidates=candidates,
                margin=margin,
                source="requested",
            )
        if corpus_name:
            return CorpusDecision(
                corpus_name=corpus_name,
                index_run_id=None,
                suggested_corpus=suggested.corpus_name if suggested else None,
                candidates=candidates,
                margin=margin,
                source="requested",
            )
        if citation is not None:
            # A cited text decides: the best-scored corpus that holds it (the
            # French code, the EU acts and the Brazilian laws are all legal
            # text, their centroids alone may not separate them).
            runs_by_id = {run.id: run for run in runs}
            for candidate in candidates:
                if cited_text_in_run(self.session, runs_by_id[candidate.index_run_id], citation):
                    return CorpusDecision(
                        corpus_name=candidate.corpus_name,
                        index_run_id=candidate.index_run_id,
                        suggested_corpus=candidate.corpus_name,
                        candidates=candidates,
                        margin=margin,
                        source="citation",
                    )
        return CorpusDecision(
            corpus_name=suggested.corpus_name if suggested else None,
            index_run_id=suggested.index_run_id if suggested else None,
            suggested_corpus=suggested.corpus_name if suggested else None,
            candidates=candidates,
            margin=margin,
            source="routed" if suggested else "none",
        )

    def finish(self, decision: RoutingDecision, retrieved: Sequence[Any]) -> RoutingDecision:
        """Add the abstention decision once the passages are known."""
        source = self.settings.routing_score_source
        abstention = decide_abstention(
            intent=decision.intent.intent,
            score=best_score(retrieved, source),
            threshold=threshold_for(self.settings, decision.corpus.corpus_name, source),
            score_source=source,
            legal_citation=decision.legal_citation_found,
        )
        declined = abstention.abstain
        return decision.model_copy(
            update={
                "abstention": abstention,
                "answer_from_documents": not declined,
                "fallback_answer": (
                    fallback_answer(decision.intent.intent, decision.language.language) if declined else None
                ),
            }
        )
