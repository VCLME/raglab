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
from raglab.retrieval.translation import LANGUAGE_NAMES
from raglab.routing.abstention import best_score, decide_abstention, fallback_answer, threshold_for
from raglab.routing.citation import cited_text_in_run
from raglab.routing.corpus import embedding_identity, index_run_centroid, list_candidate_runs, score_corpora
from raglab.routing.intent import get_intent_classifier, normalize
from raglab.routing.language import detect_language
from raglab.routing.schemas import CorpusCandidate, CorpusDecision, RoutingDecision


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
        translator: Any = None,
    ) -> RoutingDecision:
        """`translator` (a `QueryTranslator`) turns on cross-language corpus
        choice: see `_rescore_other_languages`."""
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
            question=question,
            language=language.language,
            translator=translator,
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
        question: str = "",
        language: str | None = None,
        translator: Any = None,
    ) -> CorpusDecision:
        runs = list_candidate_runs(
            self.session,
            **embedding_identity(self.settings),
            strategy=strategy,
            corpus_names=candidate_corpora,
        )
        candidates, margin = score_corpora(self.session, runs, embedding)
        if translator is not None and not index_run_id and not corpus_name and candidates:
            candidates, margin = self._rescore_other_languages(candidates, runs, question, language, translator)
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

    def _rescore_other_languages(
        self,
        candidates: list[CorpusCandidate],
        runs: Sequence[Any],
        question: str,
        language: str | None,
        translator: Any,
    ) -> tuple[list[CorpusCandidate], float]:
        """Cross-language corpus choice.

        With multilingual-e5-small a French question is closer to a French
        corpus's centroid than to the Portuguese corpus holding its answer:
        the centroid score mixes topic and language. A candidate in another
        language than the question, within `routing_translation_margin` of
        the best score, is rescored on the question translated into its
        language (one writer call per language, cached and reused by BM25),
        so every corpus is compared in its own language. A failed
        translation leaves the score as it was.
        """
        languages = {run.id: getattr(run.corpus, "language", None) for run in runs}
        best = candidates[0].score
        rescored: list[CorpusCandidate] = []
        embeddings: dict[str, Any] = {}
        for candidate in candidates:
            target = languages.get(candidate.index_run_id)
            if (
                target in LANGUAGE_NAMES
                and language in LANGUAGE_NAMES
                and target != language
                and candidate.score >= best - self.settings.routing_translation_margin
            ):
                if target not in embeddings:
                    translation = translator.translate(question, target)
                    embeddings[target] = (
                        normalize(self.embedder.embed_query(translation.text)) if translation.translated else None
                    )
                vector = embeddings[target]
                centroid = index_run_centroid(self.session, next(r for r in runs if r.id == candidate.index_run_id))
                if vector is not None and centroid is not None:
                    translated = round(float(centroid @ vector), 4)
                    candidate = candidate.model_copy(
                        update={
                            "score": max(candidate.score, translated),
                            "original_score": candidate.score,
                            "translated_score": translated,
                        }
                    )
            rescored.append(candidate)
        rescored.sort(key=lambda candidate: candidate.score, reverse=True)
        margin = rescored[0].score - rescored[1].score if len(rescored) > 1 else 0.0
        return rescored, round(margin, 4)

    def finish(
        self, decision: RoutingDecision, retrieved: Sequence[Any], *, translated_score: float | None = None
    ) -> RoutingDecision:
        """Add the abstention decision once the passages are known.

        `translated_score` (cross-language routing): dense score of the
        question translated into the corpus language, on the same passages;
        the threshold, calibrated on questions in that language, is compared
        to the better of the two."""
        source = self.settings.routing_score_source
        score = best_score(retrieved, source)
        if translated_score is not None and source == "dense":
            score = translated_score if score is None else max(score, translated_score)
        abstention = decide_abstention(
            intent=decision.intent.intent,
            score=score,
            threshold=threshold_for(self.settings, decision.corpus.corpus_name, source),
            score_source=source,
            legal_citation=decision.legal_citation_found,
        )
        if translated_score is not None and source == "dense":
            abstention = abstention.model_copy(update={"translated_score": round(translated_score, 4)})
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
