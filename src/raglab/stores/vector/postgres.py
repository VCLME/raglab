from __future__ import annotations

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Float, bindparam, cast, func, select, text
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, ChunkEmbedding, Document, IndexRun
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk


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
            typed_embedding = ChunkEmbedding.embedding
            query_param = bindparam("query_vec", query_embedding, type_=VECTOR())
        else:
            typed_embedding = cast(ChunkEmbedding.embedding, VECTOR(dim))
            query_param = bindparam("query_vec", query_embedding, type_=VECTOR(dim))
        # `<=>` returns a scalar float (cosine distance). We pin the
        # return_type so SQLAlchemy doesn't try to parse the result as a
        # Vector (the operator itself takes two Vector operands).
        distance = typed_embedding.op("<=>", return_type=Float())(query_param)

        stmt = (
            select(Chunk, Document, distance.label("distance"))
            .join(Document, Document.id == Chunk.document_id)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .where(
                Chunk.index_run_id == index_run.id,
                ChunkEmbedding.embedding_space_id == index_run.embedding_space_id,
                func.vector_dims(ChunkEmbedding.embedding) == dim,
            )
        )
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(distance).limit(top_k)

        # The HNSW index is shared by every index run of the same dimension,
        # and pgvector applies the WHERE clause (this run, filters) after the
        # ANN scan, which stops at hnsw.ef_search (40) candidates. With
        # several runs in the base, a query could get fewer than top_k chunks,
        # even none. Iterative scans (pgvector >= 0.8) keep scanning until
        # enough rows pass the filter; strict_order keeps exact distance order.
        if self.search_mode == "hnsw" and self.iterative_scan:
            session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
            session.execute(text(f"SET LOCAL hnsw.ef_search = {max(40, int(top_k))}"))
        rows = session.execute(stmt).all()
        results: list[RetrievedChunk] = []
        for rank, (chunk, document, raw_distance) in enumerate(rows, start=1):
            distance_value = float(raw_distance or 0.0)
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    file_name=document.file_name,
                    source_path=document.source_path,
                    chunk_text=chunk.text,
                    score=max(0.0, 1.0 - distance_value),
                    rank=rank,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                )
            )
        return results
