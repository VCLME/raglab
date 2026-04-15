from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from raglab.db.models import IndexRun
from raglab.domain.schemas import RetrievedChunk


class VectorStore(Protocol):
    def search(
        self,
        session: Session,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError
