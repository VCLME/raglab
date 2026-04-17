from __future__ import annotations

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Float, bindparam, cast, func, select
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, ChunkEmbedding, Document, IndexRun
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk


class PostgresVectorStore:
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
                )
            )
        return results
