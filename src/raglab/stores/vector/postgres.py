from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, ChunkEmbedding, Document, IndexRun
from raglab.domain.schemas import RetrievedChunk


class PostgresVectorStore:
    def search(
        self,
        session: Session,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        distance = ChunkEmbedding.embedding.cosine_distance(query_embedding)
        stmt = (
            select(Chunk, Document, distance.label("distance"))
            .join(Document, Document.id == Chunk.document_id)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .where(
                Chunk.index_run_id == index_run.id,
                ChunkEmbedding.embedding_space_id == index_run.embedding_space_id,
            )
            .order_by(distance)
            .limit(top_k)
        )

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
