from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.routing.schemas import RoutingDecision


class DocumentPayload(BaseModel):
    source_path: Path
    file_name: str
    extension: str
    mime_type: str
    checksum: str
    content: str
    char_count: int
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChunkDraft(BaseModel):
    strategy: ChunkingStrategy
    order: int
    text: str
    char_start: int
    char_end: int
    token_estimate: int
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    embedding_text: str | None = None
    embedding_span: tuple[int, int] | None = None


class ChunkVersion(BaseModel):
    """Version state of a retrieved chunk (phase 9.10, `versions` option).

    `source` "metadata": the chunk's document is one version of a code
    article (Légifrance sidecar: `etat`, dates, amending texts);
    "markers": a compiled law whose text marks repealed or rewritten
    provisions ("(Revogado pela Lei nº ...)", "(Redação dada pela ...)").
    """

    source: str
    etat: str | None = None
    # Applies on `reference_date` (the request's date, today by default).
    in_force: bool | None = None
    reference_date: str | None = None
    date_debut: str | None = None
    date_fin: str | None = None
    article: str | None = None
    legi_id: str | None = None
    # Title of the text that created this version / that ended it.
    amended_by: str | None = None
    ended_by: str | None = None
    # The version that followed this one ({legi_id, date_debut}), and the
    # version of the same article in force on `reference_date` when it is
    # another one.
    replaced_by: dict[str, Any] | None = None
    in_force_version: str | None = None
    version_count: int | None = None
    # Markers: provisions marked repealed / rewritten, and whether every
    # provision of the chunk is repealed (then moved after the others,
    # `demoted`, under `in_force`).
    revoked_lines: int = 0
    rewritten_lines: int = 0
    revoked_only: bool = False
    last_amended_year: int | None = None
    markers: list[str] = Field(default_factory=list)
    demoted: bool = False
    # False under `versions=all` (the naive baseline): the state is shown
    # in the UI but not told to the model.
    in_prompt: bool = True


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    file_name: str
    source_path: str
    chunk_text: str
    score: float
    rank: int
    # Offsets of the chunk in its document's normalised text. Optional
    # because the graph store does not return them.
    char_start: int | None = None
    char_end: int | None = None
    # Intermediate scores of hybrid retrieval. `score` / `rank` above are
    # those of the requested mode (cosine similarity, BM25 or fused RRF);
    # these keep each retriever's own view of the chunk. None when the
    # retriever did not run or did not return the chunk in its candidates.
    dense_score: float | None = None
    dense_rank: int | None = None
    lexical_score: float | None = None
    lexical_rank: int | None = None
    fused_score: float | None = None
    fused_rank: int | None = None
    # Cross-encoder re-ranking (rerank=true). `score` / `rank` above are then
    # these; the first-stage view stays in the fields above.
    rerank_score: float | None = None
    rerank_rank: int | None = None
    # True when the chunk was pinned because the question cites its law and
    # article (see raglab.retrieval.citations).
    citation_match: bool | None = None
    # Graph branch (phase 9.9b): the chunk belongs to an article cited by a
    # found one. `graph_via` names the citing article ("Art. 5º — Lei nº
    # 8.078/1990"), `graph_reason` says it in a sentence; `graph_pinned`
    # marks a cited passage kept right after the passage citing it.
    graph_score: float | None = None
    graph_rank: int | None = None
    graph_reason: str | None = None
    graph_via: str | None = None
    graph_pinned: bool | None = None
    # Version state (phase 9.10): set when the chunk's document carries
    # version metadata or its text carries repeal / rewrite markers.
    version: ChunkVersion | None = None


class RetrievalFilters(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    file_names: list[str] = Field(default_factory=list)
    source_path_contains: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_equals: dict[str, str] = Field(default_factory=dict)
    # ISO date: keep only the document versions in force that day
    # (documents without version metadata always pass). Set by the
    # `versions` option, see raglab.retrieval.versions.
    valid_at: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.document_ids
            or self.file_names
            or self.source_path_contains
            or self.tags
            or self.metadata_equals
            or self.valid_at
        )


class QueryResponse(BaseModel):
    question: str
    index_run_id: str
    strategy: ChunkingStrategy
    retrieved_chunks: list[RetrievedChunk]
    retrieval_mode: RetrievalMode = RetrievalMode.DENSE
    # Legal citation parsed from the question when the citations option is
    # on: label, law_number (None for a French code or an EU act), article,
    # code, celex (EU act), law_found, article_found.
    citation: dict[str, Any] | None = None
    # Lexemes the question was reduced to for BM25 (lexical / hybrid modes).
    query_lexemes: list[str] = Field(default_factory=list)
    rerank: bool = False
    # Re-ranking counters for this request: candidates, pairs actually
    # scored, score-cache hits and hit rates (this request / since start).
    rerank_stats: dict[str, float] = Field(default_factory=dict)
    # Set when re-ranking could not use a GPU: "skipped_no_gpu" or "cpu".
    rerank_notice: str | None = None
    # Graph branch: whether it ran, why it was skipped ("skipped_no_neo4j",
    # "skipped_no_graph", "failed") and its counters (seeds, articles, chunks).
    graph: bool = False
    graph_notice: str | None = None
    graph_stats: dict[str, int] = Field(default_factory=dict)
    # Version policy of the request (phase 9.10): mode (in_force, as_of,
    # all), reference date, its source (default, request, question) and the
    # question's words it was read from; `scope` says what it could act on
    # ("metadata", "markers", "none") and `demoted` how many chunks moved.
    versions: dict[str, Any] | None = None
    filters: RetrievalFilters | None = None
    answer: str | None = None
    elapsed_ms: float = 0.0
    # Wall-clock time per pipeline stage: embed, retrieval, generation.
    timings_ms: dict[str, float] = Field(default_factory=dict)
    # Generator counters when available (tokens, tokens per second).
    generation_stats: dict[str, float] = Field(default_factory=dict)
    # Router decisions (language, intent, corpus, abstention) when the
    # request enabled routing; None otherwise.
    routing: RoutingDecision | None = None


class ExperimentCase(BaseModel):
    id: str
    question: str
    expected_substrings: list[str] = Field(default_factory=list)
    ground_truth_answer: str | None = None
