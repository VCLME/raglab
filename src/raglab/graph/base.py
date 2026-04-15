from __future__ import annotations

from typing import Protocol


class GraphStore(Protocol):
    def upsert_document_graph(self, document_id: str, text: str) -> None:
        raise NotImplementedError

    def expand_context(self, seed_ids: list[str]) -> list[str]:
        raise NotImplementedError
