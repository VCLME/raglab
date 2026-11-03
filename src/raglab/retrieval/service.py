from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import get_index_run, resolve_latest_index_run
from raglab.db.models import IndexRun
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.domain.errors import StageTimeoutError, run_with_timeout
from raglab.domain.schemas import QueryResponse, RetrievalFilters, RetrievedChunk
from raglab.embeddings.factory import build_embedding_provider
from raglab.generation.prompts import build_prompt_bundle
from raglab.generation.service import AnswerGenerator, OllamaGenerator, OpenAICompatGenerator
from raglab.graph.structured import StructuredGraphStore, get_graph_store
from raglab.llm.providers import resolve_llm_provider
from raglab.llm.writer import WriterManager, get_writer
from raglab.logging_utils import log_event
from raglab.observability.metrics import observe_query
from raglab.retrieval.citations import (
    article_chunks,
    document_chunks,
    find_code_article,
    find_eu_unit,
    find_law_document,
    has_eu_act,
    merge_with_citation,
    parse_citation,
)
from raglab.retrieval.fusion import reciprocal_rank_fusion
from raglab.retrieval.graph_branch import (
    GraphBranchResult,
    graph_links,
    group_references,
    new_candidates,
    run_graph_branch,
    seed_chunks,
)
from raglab.retrieval.rerank import Reranker, get_reranker, rerank_gpu_available
from raglab.retrieval.stages import planned_stages, prompt_details, retrieval_stage_events, stage_end, stage_start
from raglab.retrieval.versions import VersionLookup, annotate, demote_revoked, is_outdated, resolve_policy
from raglab.stores.lexical.postgres import PostgresLexicalStore
from raglab.stores.vector.postgres import PostgresVectorStore

LOGGER = logging.getLogger(__name__)

# Scorer behind `RetrievedChunk.score` when re-ranking is off.
_SCORE_TYPES = {RetrievalMode.DENSE: "cosine", RetrievalMode.LEXICAL: "bm25", RetrievalMode.HYBRID: "rrf"}

# SQLSTATE raised by Postgres when statement_timeout cancels a query.
_QUERY_CANCELED = "57014"


@dataclass
class RetrievalOutcome:
    """Result of the embed + search stages, before any generation."""

    question: str
    corpus_name: str | None
    top_k: int
    filters: RetrievalFilters | None
    index_run: IndexRun
    retrieved: list[RetrievedChunk]
    started: float
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Question vector, kept for the educational mode's `stage` events.
    query_embedding: list[float] | None = None
    retrieval_mode: RetrievalMode = RetrievalMode.DENSE
    query_lexemes: list[str] = field(default_factory=list)
    lexical_weight: float | None = None
    rrf_k: int | None = None
    rerank: bool = False
    rerank_stats: dict[str, float] = field(default_factory=dict)
    # "skipped_no_gpu" (default re-rank skipped) or "cpu" (ran without GPU).
    rerank_notice: str | None = None
    # First-stage chunks the cross-encoder read (0 without re-ranking).
    rerank_candidates: int = 0
    # Parsed legal citation and whether it resolved (citations option).
    citation: dict[str, Any] | None = None
    # Graph branch (graph option): whether it ran, why not, its counters.
    graph: bool = False
    graph_notice: str | None = None
    graph_stats: dict[str, int] = field(default_factory=dict)
    # For the learning mode's `graph` stage: the references followed
    # (citing -> cited article, the sentence, passages added) and the
    # branch's own ranked list.
    graph_links: list[dict[str, Any]] = field(default_factory=list)
    graph_chunks: list[RetrievedChunk] = field(default_factory=list)
    # Version policy (versions option) and what it did; see QueryResponse.
    versions: dict[str, Any] | None = None

    def response(self, **extra: Any) -> QueryResponse:
        return QueryResponse(
            question=self.question,
            index_run_id=self.index_run.id,
            strategy=ChunkingStrategy(self.index_run.strategy),
            retrieved_chunks=self.retrieved,
            retrieval_mode=self.retrieval_mode,
            query_lexemes=self.query_lexemes,
            rerank=self.rerank,
            rerank_stats=dict(self.rerank_stats),
            rerank_notice=self.rerank_notice,
            filters=self.filters,
            timings_ms=dict(self.timings_ms),
            citation=self.citation,
            graph=self.graph,
            graph_notice=self.graph_notice,
            graph_stats=dict(self.graph_stats),
            versions=dict(self.versions) if self.versions is not None else None,
            **extra,
        )


class QueryService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.vector_store = PostgresVectorStore(
            search_mode=self.settings.vector_search_mode,
            iterative_scan=self.settings.hnsw_iterative_scan,
        )
        self.lexical_store = PostgresLexicalStore(k1=self.settings.bm25_k1, b=self.settings.bm25_b)
        # One generator per provider, built on first use.
        self._generators: dict[str, AnswerGenerator] = {}
        # Picks llama.cpp or its fallback for queries that name no provider.
        self.writer: WriterManager = get_writer()
        self._reranker: Reranker | None = None
        self._graph_store: StructuredGraphStore | None = None
        self.version_lookup = VersionLookup(session)

    @property
    def graph_store(self) -> StructuredGraphStore:
        # Shared driver per Neo4j target, opened on the first graph query.
        if self._graph_store is None:
            self._graph_store = get_graph_store(self.settings)
        return self._graph_store

    @graph_store.setter
    def graph_store(self, value: StructuredGraphStore) -> None:
        self._graph_store = value

    @property
    def generator(self) -> AnswerGenerator:
        """Generator of the default provider (RAGLAB_DEFAULT_LLM_PROVIDER)."""
        return self.generator_for(None)

    @generator.setter
    def generator(self, value: AnswerGenerator) -> None:
        self._generators[self.settings.default_llm_provider] = value

    def generator_for(self, llm_provider: str | None) -> AnswerGenerator:
        """Generator for `llm_provider` (None = default); raises
        UnknownLLMProviderError (HTTP 400) for a disabled or unknown name."""
        name = resolve_llm_provider(self.settings, llm_provider)
        if name not in self._generators:
            self._generators[name] = (
                OllamaGenerator(self.settings)
                if name == "ollama"
                else OpenAICompatGenerator(self.settings, provider=name)
            )
        return self._generators[name]

    def pick_generator(self, llm_provider: str | None, llm_model: str | None) -> tuple[str, str | None, str | None]:
        """(provider, model, generator_notice) for one answer.

        A named provider is used as asked (an unknown one raises
        UnknownLLMProviderError). Without one, the default writer answers, or
        its fallback when llama.cpp cannot serve it (see raglab.llm.writer);
        the notice says why, and `llm_model`, meant for the writer, is then
        dropped.
        """
        if llm_provider is not None and llm_provider.strip():
            return resolve_llm_provider(self.settings, llm_provider), llm_model, None
        choice = self.writer.choose(self.settings)
        if choice.notice:
            return choice.provider, choice.model, choice.notice
        return choice.provider, llm_model or choice.model, None

    @property
    def reranker(self) -> Reranker:
        # Shared per configuration and loaded on first use, so a service that
        # never reranks never touches torch or the GPU.
        if self._reranker is None:
            self._reranker = get_reranker(self.settings)
        return self._reranker

    @reranker.setter
    def reranker(self, value: Reranker) -> None:
        self._reranker = value

    def _resolve_index_run(
        self,
        *,
        corpus_name: str | None,
        strategy: ChunkingStrategy | None,
        index_run_id: str | None,
    ):
        if index_run_id:
            index_run = get_index_run(self.session, index_run_id)
        else:
            if not corpus_name:
                raise ValueError("corpus_name est obligatoire quand index_run_id n'est pas fourni")
            index_run = resolve_latest_index_run(
                self.session,
                corpus_name=corpus_name,
                strategy=strategy,
                backend="pgvector",
            )
        if index_run is None:
            raise ValueError("Aucun index_run compatible n'a ete trouve")
        config = index_run.config_json or {}
        run_backend = config.get("backend", "pgvector")
        if run_backend != "pgvector":
            raise ValueError(
                f"L'index_run {index_run.id} est un run graphe (backend={run_backend}) — "
                "utilise /api/graph/query pour l'interroger."
            )
        return index_run

    def _embed_question(self, index_run: IndexRun, question: str) -> list[float]:
        # Each index_run points to an embedding_space that carries the exact
        # provider, model and dimension used at indexing time. We use those to
        # build an embedder that matches the index, which is what lets multiple
        # embedding spaces with different dimensions coexist in the same DB.
        effective_settings = self.settings.model_copy(
            update={
                "embedding_provider": index_run.embedding_space.provider,
                "embedding_model_name": index_run.embedding_space.model_name,
                "embedding_dimension": index_run.embedding_space.dimension,
                "distance_metric": index_run.embedding_space.distance_metric,
                "query_prefix": index_run.embedding_space.query_prefix,
                "passage_prefix": index_run.embedding_space.passage_prefix,
            }
        )
        embedder = build_embedding_provider(effective_settings)
        return run_with_timeout(
            "embed",
            self.settings.embed_timeout_seconds,
            lambda: embedder.embed_query(question),
        )

    def retrieve(
        self,
        *,
        question: str,
        corpus_name: str | None = None,
        strategy: ChunkingStrategy | None = None,
        index_run_id: str | None = None,
        top_k: int | None = None,
        filters: RetrievalFilters | None = None,
        retrieval_mode: RetrievalMode | str | None = None,
        lexical_weight: float | None = None,
        rrf_k: int | None = None,
        rerank: bool | None = None,
        citations: bool | None = None,
        graph: bool | None = None,
        versions: str | None = None,
    ) -> RetrievalOutcome:
        """Search the index for the question, each stage under its budget.

        With `citations` on, a question citing a law ("art. 49 da Lei nº
        8.078") is restricted to that law and the cited article is pinned
        first; one citing an article of a French code ("article L. 221-18 du
        code de la consommation") pins that article's document and is
        restricted to the code (see `raglab.retrieval.citations`).

        With `graph` on, a third list joins the fusion: chunks of the
        articles that the cited article and the best first-stage hits cite
        (see `raglab.retrieval.graph_branch`); after re-ranking, a cited
        passage is kept right after the passage citing it.

        dense: embed + cosine KNN (as before). lexical: BM25, no embedder.
        hybrid: both, fused by Reciprocal Rank Fusion over deeper lists.
        rerank: the chosen mode returns `rerank_candidates` chunks, a
        cross-encoder re-scores them and the top_k best are kept.

        versions: which article versions may be used (see
        `raglab.retrieval.versions`): `in_force` (default) keeps the versions
        in force today, or on the date the question asks about ("avant
        2016"); `as_of=YYYY-MM-DD` on that date; `all` every version. On a
        corpus with version metadata the others are filtered out before
        ranking; on compiled laws, chunks that only hold repealed provisions
        are moved last. Every chunk carries its version state.
        """
        mode = RetrievalMode(retrieval_mode or self.settings.default_retrieval_mode)
        index_run = self._resolve_index_run(
            corpus_name=corpus_name,
            strategy=strategy,
            index_run_id=index_run_id,
        )
        effective_top_k = top_k or self.settings.default_top_k
        do_rerank = self.settings.default_rerank if rerank is None else rerank
        rerank_notice: str | None = None
        if do_rerank and not rerank_gpu_available(self.settings.rerank_device):
            if rerank is None and self.settings.rerank_without_gpu == "skip":
                do_rerank = False
                rerank_notice = "skipped_no_gpu"
            else:
                rerank_notice = "cpu"
            log_event(
                LOGGER, logging.WARNING, "rerank.no_gpu", device=self.settings.rerank_device, action=rerank_notice
            )
        # The first stage returns more than top_k when the cross-encoder
        # picks among its candidates.
        stage_top_k = max(effective_top_k, self.settings.rerank_candidates) if do_rerank else effective_top_k
        # Hybrid fuses deeper lists than it returns: a chunk ranked 30th by
        # one retriever and 3rd by the other must still be seen by RRF.
        candidate_k = max(stage_top_k, self.settings.hybrid_candidates) if mode == RetrievalMode.HYBRID else stage_top_k
        weight = self.settings.hybrid_lexical_weight if lexical_weight is None else lexical_weight
        fusion_k = self.settings.rrf_k if rrf_k is None else rrf_k

        use_graph = self.settings.graph_retrieval if graph is None else graph
        # The citation restricts the search to the cited law; the graph
        # branch follows references out of it, under the caller's filters only.
        user_filters = filters
        versions_started = perf_counter()
        policy = resolve_policy(versions, question, default_mode=self.settings.versions_default)
        has_history = self.version_lookup.has_history(index_run)
        if policy.filters and has_history and policy.on is not None:
            filters = (filters or RetrievalFilters()).model_copy(update={"valid_at": policy.on.isoformat()})
        versions_seconds = perf_counter() - versions_started
        citation_started = perf_counter()
        use_citations = self.settings.citation_resolver if citations is None else citations
        parsed = parse_citation(question) if use_citations or use_graph else None
        # Graph only (citations off): the cited article seeds the branch, the
        # search itself is not restricted to its law.
        citation = parsed if use_citations else None
        law_document_id: str | None = None
        pinned: list[RetrievedChunk] = []
        cited_code: str | None = None
        eu_act_found = False
        if parsed is not None and parsed.law_number is not None:
            law_document_id = find_law_document(self.session, index_run, parsed)
            if citation is not None and law_document_id is not None:
                if citation.article:
                    pinned = article_chunks(self.session, index_run, law_document_id, citation.article)
                filters = (filters or RetrievalFilters()).model_copy(update={"document_ids": [law_document_id]})
        elif parsed is not None and parsed.celex is not None:
            # A unit of an EU act is a document of its own (one per language):
            # pin it and search the rest of the cited act.
            eu_unit = find_eu_unit(self.session, index_run, parsed)
            law_document_id = eu_unit.document_id if eu_unit is not None else None
            eu_act_found = eu_unit is not None or has_eu_act(self.session, index_run, parsed.celex)
            if citation is not None and eu_act_found:
                if eu_unit is not None:
                    pinned = document_chunks(self.session, index_run, eu_unit.document_id)
                base = filters or RetrievalFilters()
                filters = base.model_copy(update={"metadata_equals": {**base.metadata_equals, "celex": parsed.celex}})
        elif citation is not None:
            # An article of a French code is a document of its own: pin it
            # and search the rest of the cited code.
            code_article = find_code_article(
                self.session, index_run, citation, on=policy.on if policy.mode == "as_of" else None
            )
            if code_article is not None:
                law_document_id = code_article.document_id
                cited_code = code_article.code
                pinned = document_chunks(self.session, index_run, code_article.document_id)
                if cited_code:
                    base = filters or RetrievalFilters()
                    filters = base.model_copy(update={"metadata_equals": {**base.metadata_equals, "code": cited_code}})
        # The graph holds laws (profile "laws") and EU acts (profile
        # "eu_acts"): a cited law's or EU act's article seeds it.
        seed_articles = (
            [{"document_id": law_document_id, "number": parsed.article, "rank": 0}]
            if use_graph
            and parsed is not None
            and (parsed.law_number is not None or parsed.unit == "article")
            and parsed.article
            and law_document_id is not None
            else []
        )
        citation_seconds = perf_counter() - citation_started if citation is not None else 0.0
        started = perf_counter()
        query_embedding: list[float] | None = None
        if mode != RetrievalMode.LEXICAL:
            query_embedding = self._embed_question(index_run, question)
        embedded = perf_counter()

        dense: list[RetrievedChunk] = []
        lexical: list[RetrievedChunk] = []
        query_lexemes: list[str] = []
        stage_ms: dict[str, float] = {}
        with self._statement_timeout(self.settings.retrieval_timeout_seconds):
            search_started = perf_counter()
            if query_embedding is not None:
                dense = self.vector_store.search(
                    self.session,
                    index_run=index_run,
                    query_embedding=query_embedding,
                    top_k=candidate_k,
                    filters=filters,
                )
                stage_ms["dense"] = perf_counter() - search_started
            if mode != RetrievalMode.DENSE:
                lexical_started = perf_counter()
                lexical, query_lexemes = self.lexical_store.search(
                    self.session,
                    index_run=index_run,
                    question=question,
                    top_k=candidate_k,
                    filters=filters,
                )
                stage_ms["lexical"] = perf_counter() - lexical_started
            branch = GraphBranchResult()
            if use_graph:
                graph_started = perf_counter()
                branch = run_graph_branch(
                    self.session,
                    self.graph_store,
                    index_run,
                    settings=self.settings,
                    seeds=seed_chunks(dense, lexical, limit=self.settings.graph_seed_chunks, pinned=pinned),
                    seed_articles=seed_articles,
                    filters=user_filters,
                )
                stage_ms["graph"] = perf_counter() - graph_started
            fusion_started = perf_counter()
            # The graph adds the cited passages the retrievers missed; it does
            # not re-score what they found (that cost Recall@1 on LexML).
            graph_list = new_candidates(branch.chunks, dense, lexical, pinned)
            if branch.stats:
                branch.stats["added"] = len(graph_list)
            if graph_list:
                # Three sources: the single-retriever modes keep their own
                # list at full weight (w = 0 or 1).
                three_way_weight = {RetrievalMode.DENSE: 0.0, RetrievalMode.LEXICAL: 1.0}.get(mode, weight)
                retrieved = reciprocal_rank_fusion(
                    dense,
                    lexical,
                    graph=graph_list,
                    k=fusion_k,
                    lexical_weight=three_way_weight,
                    graph_weight=self.settings.graph_weight,
                    top_k=stage_top_k,
                )
                stage_ms["fusion"] = perf_counter() - fusion_started
            elif mode == RetrievalMode.DENSE:
                retrieved = [
                    chunk.model_copy(update={"dense_score": chunk.score, "dense_rank": chunk.rank}) for chunk in dense
                ]
            elif mode == RetrievalMode.LEXICAL:
                retrieved = lexical
            else:
                retrieved = reciprocal_rank_fusion(
                    dense,
                    lexical,
                    k=fusion_k,
                    lexical_weight=weight,
                    top_k=stage_top_k,
                )
                stage_ms["fusion"] = perf_counter() - fusion_started
            if pinned:
                # Keep every candidate when the cross-encoder still has to
                # choose among them; the article is pinned again after it.
                retrieved = merge_with_citation(pinned, retrieved, stage_top_k if do_rerank else effective_top_k)
            searched = perf_counter()

        # `embed` + `retrieval` (+ `rerank` when on) are the stages the recall
        # benchmark sums into its query latency; lexical mode embeds nothing and has no
        # `embed` stage. Lexical and hybrid add dense / lexical / fusion as a
        # breakdown of retrieval (the Chat's `stage` events are derived from
        # these keys); dense keeps exactly the 9.1 baseline keys. The
        # statement_timeout round trips stay out of the stage timing so it
        # remains comparable with the baseline.
        timings_ms: dict[str, float] = {}
        if query_embedding is not None:
            timings_ms["embed"] = round((embedded - started) * 1000, 3)
        # Citation resolution is part of retrieval: counted in `retrieval`
        # (so the benchmark's query latency includes it) and shown apart.
        timings_ms["retrieval"] = round((searched - search_started + citation_seconds) * 1000, 3)
        if citation is not None:
            timings_ms["citation"] = round(citation_seconds * 1000, 3)
        if mode != RetrievalMode.DENSE or use_graph:
            timings_ms.update({stage: round(seconds * 1000, 3) for stage, seconds in stage_ms.items()})

        rerank_stats: dict[str, float] = {}
        first_stage_pool = list(retrieved)
        if do_rerank:
            first_stage = retrieved
            rerank_started = perf_counter()
            retrieved, rerank_stats = run_with_timeout(
                "rerank",
                self.settings.rerank_timeout_seconds,
                lambda: self.reranker.rerank(question, first_stage, top_k=effective_top_k),
            )
            timings_ms["rerank"] = round((perf_counter() - rerank_started) * 1000, 3)
            if pinned:
                # A cited article is the answer by construction: the
                # cross-encoder orders the rest, it does not demote the pin.
                retrieved = merge_with_citation(pinned, retrieved, effective_top_k)
        if branch.hits:
            # A passage found through a reference stays next to the one
            # citing it, whatever the cross-encoder made of it.
            pool = {chunk.chunk_id: chunk for chunk in [*branch.chunks, *first_stage_pool]}
            retrieved = group_references(
                retrieved, branch.hits, pool, top_k=effective_top_k, max_groups=self.settings.graph_group_max
            )
        versions_started = perf_counter()
        retrieved = annotate(
            retrieved, policy, self.version_lookup.metadata(sorted({chunk.document_id for chunk in retrieved}))
        )
        demoted = 0
        if policy.mode == "in_force":
            retrieved, demoted = demote_revoked(retrieved)
        has_markers = any(chunk.version is not None and chunk.version.source == "markers" for chunk in retrieved)
        versions_seconds += perf_counter() - versions_started
        # Part of retrieval (the benchmark's query latency includes it), shown apart.
        timings_ms["retrieval"] = round(timings_ms["retrieval"] + versions_seconds * 1000, 3)
        versions_info = {
            **policy.as_dict(),
            "scope": "metadata" if has_history else "markers" if has_markers else "none",
            "filtered": bool(policy.filters and has_history),
            "demoted": demoted,
            "outdated": sum(1 for chunk in retrieved if is_outdated(chunk)),
        }
        if versions_info["scope"] != "none":
            # The learning mode's `versions` stage; absent where no chunk
            # carries version information (PIAF, uploads).
            timings_ms["versions"] = round(versions_seconds * 1000, 3)
        if policy.mode == "as_of" and not has_history and has_markers:
            # Compiled laws keep only the wording in force: a past date
            # cannot be honoured there.
            versions_info["notice"] = "markers_no_history"
        hybrid = mode == RetrievalMode.HYBRID
        return RetrievalOutcome(
            question=question,
            corpus_name=corpus_name,
            top_k=effective_top_k,
            filters=filters,
            index_run=index_run,
            retrieved=retrieved,
            started=started,
            query_embedding=list(query_embedding) if query_embedding is not None else None,
            timings_ms=timings_ms,
            retrieval_mode=mode,
            query_lexemes=query_lexemes,
            lexical_weight=weight if hybrid else None,
            rrf_k=fusion_k if hybrid else None,
            rerank=do_rerank,
            rerank_notice=rerank_notice,
            rerank_stats=rerank_stats,
            rerank_candidates=int(rerank_stats.get("candidates", 0)),
            citation=(
                {
                    "label": citation.label(),
                    "law_number": citation.law_number,
                    "article": citation.article,
                    "code": cited_code or citation.code,
                    "celex": citation.celex,
                    "law_found": law_document_id is not None or eu_act_found,
                    "article_found": bool(pinned),
                }
                if citation is not None
                else None
            ),
            graph=use_graph,
            graph_notice=branch.notice,
            graph_stats=dict(branch.stats),
            graph_links=graph_links(branch, graph_list),
            graph_chunks=list(branch.chunks),
            versions=versions_info,
        )

    def query(
        self,
        *,
        question: str,
        corpus_name: str | None = None,
        strategy: ChunkingStrategy | None = None,
        index_run_id: str | None = None,
        top_k: int | None = None,
        generate_answer: bool = True,
        filters: RetrievalFilters | None = None,
        llm_model: str | None = None,
        generation_top_k: int | None = None,
        retrieval_mode: RetrievalMode | str | None = None,
        lexical_weight: float | None = None,
        rrf_k: int | None = None,
        rerank: bool | None = None,
        citations: bool | None = None,
        graph: bool | None = None,
        versions: str | None = None,
        llm_provider: str | None = None,
    ) -> QueryResponse:
        """`generation_top_k` sends only the first N retrieved chunks to the
        LLM; the benchmark retrieves 10 (for Recall@10) but must generate from
        the same top-k as production. `llm_provider` picks the generation
        provider (None = RAGLAB_DEFAULT_LLM_PROVIDER)."""
        # Resolved before retrieval: an unknown provider fails fast with a 400.
        if llm_provider is not None and generate_answer:
            resolve_llm_provider(self.settings, llm_provider)
        outcome = self.retrieve(
            question=question,
            corpus_name=corpus_name,
            strategy=strategy,
            index_run_id=index_run_id,
            top_k=top_k,
            filters=filters,
            retrieval_mode=retrieval_mode,
            lexical_weight=lexical_weight,
            rrf_k=rrf_k,
            rerank=rerank,
            citations=citations,
            graph=graph,
            versions=versions,
        )
        answer = None
        stats: dict[str, float] = {}
        provider: str | None = None
        notice: str | None = None
        if generate_answer:
            provider, model, notice = self.pick_generator(llm_provider, llm_model)
            generator = self.generator_for(provider)
            generation_started = perf_counter()
            context = outcome.retrieved[:generation_top_k] if generation_top_k else outcome.retrieved
            answer = generator.generate_answer(question, context, model=model)
            outcome.timings_ms["generation"] = round((perf_counter() - generation_started) * 1000, 3)
            stats = dict(generator.last_stats)
        elapsed_ms = (perf_counter() - outcome.started) * 1000
        self._log_completed(
            outcome,
            generate_answer=generate_answer,
            elapsed_ms=elapsed_ms,
            generation_stats=stats,
            llm_provider=provider,
        )
        return outcome.response(
            answer=answer,
            elapsed_ms=elapsed_ms,
            generation_stats=stats,
            llm_provider=provider,
            generator_notice=notice,
        )

    def stream_answer(
        self,
        outcome: RetrievalOutcome,
        *,
        llm_model: str | None = None,
        llm_provider: str | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Generate the answer for a finished retrieval as (event, data) pairs.

        `llm_model` overrides the configured generation model for this answer;
        `llm_provider` picks the provider (None = the default writer, or its
        fallback: see `pick_generator`).

        Yields `stage` events around the prompt and generation stages (see
        `raglab.retrieval.stages`), one `token` event per fragment produced by
        Ollama, then a `done` event carrying the full `QueryResponse` plus
        `first_token_ms` (time from the start of generation to the first
        fragment).
        """
        provider, llm_model, notice = self.pick_generator(llm_provider, llm_model)
        generator = self.generator_for(provider)
        prompt_started = perf_counter()
        yield "stage", stage_start("prompt", self._since_start(outcome, prompt_started))
        bundle = build_prompt_bundle(
            outcome.question,
            outcome.retrieved,
            no_context_answer=self.settings.generation_no_context_answer,
        )
        counts, data = prompt_details(bundle, len(outcome.retrieved))
        prompt_done = perf_counter()
        yield (
            "stage",
            stage_end(
                "prompt",
                self._since_start(outcome, prompt_done),
                (prompt_done - prompt_started) * 1000,
                counts=counts,
                data=data,
            ),
        )

        generation_started = perf_counter()
        yield "stage", stage_start("generation", self._since_start(outcome, generation_started))
        first_token_ms: float | None = None
        parts: list[str] = []
        for piece in generator.stream_answer(outcome.question, outcome.retrieved, model=llm_model):
            if first_token_ms is None:
                first_token_ms = round((perf_counter() - generation_started) * 1000, 3)
            parts.append(piece)
            yield "token", {"text": piece}
        generation_done = perf_counter()
        outcome.timings_ms["generation"] = round((generation_done - generation_started) * 1000, 3)
        stats = dict(generator.last_stats)
        generation_data: dict[str, Any] = {
            "provider": provider,
            "model": _model_label(provider, llm_model, self.settings),
        }
        if notice:
            generation_data["notice"] = notice
        yield (
            "stage",
            stage_end(
                "generation",
                self._since_start(outcome, generation_done),
                outcome.timings_ms["generation"],
                counts={**stats, "fragments": len(parts), "first_token_ms": first_token_ms},
                data=generation_data,
            ),
        )
        elapsed_ms = (generation_done - outcome.started) * 1000
        self._log_completed(
            outcome,
            generate_answer=True,
            elapsed_ms=elapsed_ms,
            streamed=True,
            generation_stats=stats,
            llm_provider=provider,
        )
        response = outcome.response(
            answer="".join(parts).strip(),
            elapsed_ms=elapsed_ms,
            generation_stats=stats,
            llm_provider=provider,
            generator_notice=notice,
        )
        yield "done", {**response.model_dump(mode="json"), "first_token_ms": first_token_ms}

    @staticmethod
    def pipeline_events(outcome: RetrievalOutcome, *, generate: bool) -> list[tuple[str, dict[str, Any]]]:
        """`pipeline` (stages this request runs) then the replayed retrieval stages."""
        events: list[tuple[str, dict[str, Any]]] = [
            ("pipeline", {"stages": planned_stages(outcome, generate=generate)})
        ]
        events.extend(("stage", event) for event in retrieval_stage_events(outcome))
        return events

    @staticmethod
    def _since_start(outcome: RetrievalOutcome, now: float) -> float:
        return (now - outcome.started) * 1000

    def _log_completed(
        self,
        outcome: RetrievalOutcome,
        *,
        generate_answer: bool,
        elapsed_ms: float,
        streamed: bool = False,
        generation_stats: dict[str, float] | None = None,
        llm_provider: str | None = None,
    ) -> None:
        log_event(
            LOGGER,
            logging.INFO,
            "query.completed",
            corpus_name=outcome.corpus_name,
            strategy=outcome.index_run.strategy,
            index_run_id=outcome.index_run.id,
            top_k=outcome.top_k,
            retrieval_mode=outcome.retrieval_mode.value,
            lexical_weight=outcome.lexical_weight,
            rrf_k=outcome.rrf_k,
            rerank=outcome.rerank,
            rerank_stats=outcome.rerank_stats,
            graph=outcome.graph,
            graph_notice=outcome.graph_notice,
            graph_stats=outcome.graph_stats,
            versions=outcome.versions,
            generate_answer=generate_answer,
            llm_provider=llm_provider,
            streamed=streamed,
            retrieved_chunks=len(outcome.retrieved),
            filters=outcome.filters.model_dump() if outcome.filters else {},
            question_length=len(outcome.question),
            elapsed_ms=round(elapsed_ms, 3),
            timings_ms=outcome.timings_ms,
        )
        observe_query(
            timings_ms=outcome.timings_ms,
            scores=(chunk.score for chunk in outcome.retrieved),
            strategy=str(outcome.index_run.strategy),
            generated=generate_answer,
            generation_stats=generation_stats if generate_answer else None,
            rerank_stats=outcome.rerank_stats,
            rerank_notice=outcome.rerank_notice,
            score_type=(
                "rerank"
                if outcome.rerank
                else "rrf"
                if outcome.graph_stats.get("chunks")
                else _SCORE_TYPES[outcome.retrieval_mode]
            ),
        )

    @contextmanager
    def _statement_timeout(self, timeout_seconds: float) -> Iterator[None]:
        """Let Postgres cancel the search past the budget (transaction-local).

        The previous value is restored afterwards so the rest of the caller's
        transaction (benchmarks write their results in the same session) keeps
        its own limit.
        """
        if timeout_seconds <= 0:
            yield
            return
        previous = self.session.execute(text("SELECT current_setting('statement_timeout')")).scalar()
        self.session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": f"{int(timeout_seconds * 1000)}ms"},
        )
        try:
            yield
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) == _QUERY_CANCELED:
                raise StageTimeoutError("retrieval", timeout_seconds) from exc
            raise
        self.session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": str(previous)},
        )


def _model_label(provider: str, llm_model: str | None, settings: Settings) -> str | None:
    """Model named in the generation stage: the requested one, else the
    configured Ollama model; None lets an OpenAI-compatible server pick."""
    if llm_model:
        return llm_model
    return settings.generation_model if provider == "ollama" else None
