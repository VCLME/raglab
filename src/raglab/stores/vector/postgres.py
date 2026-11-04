from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Float, and_, bindparam, cast, func, not_, or_, select, text
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, ChunkEmbedding, Document, IndexRun
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk

# Ranked rows per result that may be checked by the versions filter (see
# `ranked_in_force`); PostgreSQL stops once top_k rows pass. Measured on the
# Code de la consommation (300 questions, top_k 5, ~30% of the chunks in
# force, older versions of an article ranking side by side), questions
# that ran out of rows and fell back to the filtered query: 8x, 6 (BM25) and
# 19 (dense); 16x, 0 and 1; 32x, none, at the same p50.
VALID_AT_DEPTH = 32


class QueryVector(VECTOR):
    """`VECTOR` for the query embedding, sent as the shortest text of each
    float32. pgvector writes the float64 form of the same float32 values
    (`0.03319903463125229` for `0.033199035`): 7.7 kB for 384 dimensions
    instead of 4.4 kB. PostgreSQL reads both as the same float4 vector, but
    on Docker Desktop for Windows every request over 8 kB waits ~55 ms
    (measured), and the 384-d search sat just under that limit.
    """

    cache_ok = True

    def bind_processor(self, dialect):
        dim = self.dim

        def process(value):
            if value is None:
                return None
            values = np.asarray(value, dtype=np.float32)
            if values.ndim != 1 or (dim is not None and len(values) != dim):
                raise ValueError(f"expected a {dim or 'flat'}-dimension vector, got shape {values.shape}")
            return "[" + ",".join(map(str, values)) + "]"

        return process


def valid_at_condition(day: str):
    """Document versions in force on `day` (ISO), by their metadata.

    Same rule as `raglab.retrieval.versions.valid_at`: started on or before
    the day, not ended yet, not annulled. Documents without version metadata
    (no `etat`: PIAF, LexML, uploads) always pass. ISO dates compare as
    strings; a JSON null reads as SQL NULL.
    """
    meta = Document.metadata_json
    start = meta["date_debut"].astext
    end = meta["date_fin"].astext
    return or_(
        not_(meta.has_key("etat")),
        and_(
            meta["etat"].astext != "ANNULE",
            or_(start.is_(None), start <= day),
            or_(end.is_(None), end > day),
        ),
    )


def ranked_in_force(session: Session, ranked, sort_keys, *, day: str, top_k: int, full: Callable[[], Any]):
    """The top_k rows of `ranked` (ordered, with a `document_id` column)
    whose document is in force on `day`.

    Filtering every candidate reads each document's metadata (a ~1.2 kB
    JSONB) five times: on the Code de la consommation that cost the dense
    search 35 -> 220 ms and BM25 40 -> 100 ms. The filter is the same for
    every row, so the ranking does not depend on it: the first
    `VALID_AT_DEPTH * top_k` rows are ranked unfiltered and only those are
    checked. When fewer than top_k survive, `full()` (the filtered query)
    runs instead, so the result is the same as filtering first.
    """
    inner = ranked.limit(VALID_AT_DEPTH * top_k).subquery("ranked")
    rows = session.execute(
        select(*inner.c)
        .join(Document, Document.id == inner.c.document_id)
        .where(valid_at_condition(day))
        .order_by(*sort_keys(inner))
        .limit(top_k)
    ).all()
    if len(rows) < top_k:
        rows = session.execute(full()).all()
    return rows


def without_valid_at(filters: RetrievalFilters) -> RetrievalFilters:
    """The same filters, the versions one left to `ranked_in_force`."""
    return filters.model_copy(update={"valid_at": None})


class PostgresVectorStore:
    def __init__(self, *, search_mode: str = "exact", iterative_scan: bool = True):
        """`search_mode="exact"` scans the run's vectors (always the true
        nearest neighbours); `"hnsw"` uses the shared partial HNSW index.

        The HNSW index is shared by every index run of a dimension. Measured
        on PIAF: once the same corpus has been indexed several times, the
        graph holds identical copies of each vector and the filter on the run
        is applied after the approximate search, so recall depends on what
        else is in the database (0.09 to 0.63 Recall@5 for two runs of the
        same corpus, 0.91 with an exact scan). Exact search costs ~10-15 ms
        for a few thousand chunks, so it is the default; HNSW pays off with
        hundreds of thousands of vectors and one index per run.
        `iterative_scan=False` reproduces the pre-9.1b HNSW behaviour.
        """
        if search_mode not in ("exact", "hnsw"):
            raise ValueError(f"Mode de recherche vectorielle inconnu: {search_mode}")
        self.search_mode = search_mode
        self.iterative_scan = iterative_scan

    @staticmethod
    def _apply_filters(stmt, filters: RetrievalFilters | None):
        if filters is None or filters.is_empty():
            return stmt

        if filters.document_ids:
            stmt = stmt.where(Chunk.document_id.in_(filters.document_ids))
        if filters.file_names:
            stmt = stmt.where(Document.file_name.in_(filters.file_names))
        if filters.source_path_contains:
            stmt = stmt.where(Document.source_path.contains(filters.source_path_contains, autoescape=True))
        for tag in filters.tags:
            stmt = stmt.where(Document.metadata_json.contains({"tags": [tag]}))
        for key, value in filters.metadata_equals.items():
            stmt = stmt.where(Document.metadata_json.contains({key: value}))
        if filters.valid_at:
            stmt = stmt.where(valid_at_condition(filters.valid_at))

        return stmt

    def search(
        self,
        session: Session,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        # The chunk_embeddings.embedding column is stored as a variable-dim
        # `vector`. To let the Postgres planner reach the partial HNSW index
        # built for this dimension, we cast both the column and the bound query
        # vector to `vector(dim)`, and we add the `vector_dims` predicate that
        # matches the partial index WHERE clause.
        dim = index_run.embedding_space.dimension
        if self.search_mode == "exact":
            # No cast: the expression no longer matches the partial HNSW
            # index, so Postgres computes the exact distance for the run's rows.
            typed_embedding: Any = ChunkEmbedding.embedding
            query_param = bindparam("query_vec", query_embedding, type_=QueryVector())
        else:
            typed_embedding = cast(ChunkEmbedding.embedding, VECTOR(dim))
            query_param = bindparam("query_vec", query_embedding, type_=QueryVector(dim))
        # `<=>` returns a scalar float (cosine distance). We pin the
        # return_type so SQLAlchemy doesn't try to parse the result as a
        # Vector (the operator itself takes two Vector operands).
        distance = typed_embedding.op("<=>", return_type=Float())(query_param)

        stmt = (
            # Only the columns a result needs: selecting the Document entity
            # loaded each candidate's full text (whole laws for LexML), which
            # cost ~13 ms per query at 50 candidates.
            select(
                Chunk.id,
                Chunk.text,
                Chunk.char_start,
                Chunk.char_end,
                Document.id.label("document_id"),
                Document.file_name,
                Document.source_path,
                distance.label("distance"),
            )
            .join(Document, Document.id == Chunk.document_id)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .where(
                Chunk.index_run_id == index_run.id,
                ChunkEmbedding.embedding_space_id == index_run.embedding_space_id,
            )
        )
        if self.search_mode == "hnsw":
            # Matches the partial index predicate so the planner can use it.
            # Exact mode leaves it out: it would force evaluating every
            # embedding of the table instead of starting from the run's chunks.
            stmt = stmt.where(func.vector_dims(ChunkEmbedding.embedding) == dim)
        # The versions filter goes after the ranking (`ranked_in_force`).
        # HNSW keeps it in the scan: its iterative scan needs the full
        # filter to know when it has enough rows.
        day = filters.valid_at if filters is not None and self.search_mode == "exact" else None

        def full():
            return self._apply_filters(stmt, filters).order_by(distance).limit(top_k)

        # The HNSW index is shared by every index run of the same dimension,
        # and pgvector applies the WHERE clause (this run, filters) after the
        # ANN scan, which stops at hnsw.ef_search (40) candidates. With
        # several runs in the base, a query could get fewer than top_k chunks,
        # even none. Iterative scans (pgvector >= 0.8) keep scanning until
        # enough rows pass the filter; strict_order keeps exact distance order.
        if self.search_mode == "hnsw" and self.iterative_scan:
            session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
            session.execute(text(f"SET LOCAL hnsw.ef_search = {max(40, int(top_k))}"))
        if day:
            rows = ranked_in_force(
                session,
                self._apply_filters(stmt, without_valid_at(filters)).order_by(distance),
                lambda inner: [inner.c.distance],
                day=day,
                top_k=top_k,
                full=full,
            )
        else:
            rows = session.execute(full()).all()
        results: list[RetrievedChunk] = []
        for rank, row in enumerate(rows, start=1):
            distance_value = float(row.distance or 0.0)
            results.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    file_name=row.file_name,
                    source_path=row.source_path,
                    chunk_text=row.text,
                    score=max(0.0, 1.0 - distance_value),
                    rank=rank,
                    char_start=row.char_start,
                    char_end=row.char_end,
                )
            )
        return results
