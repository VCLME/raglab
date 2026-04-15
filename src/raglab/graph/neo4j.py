class Neo4jGraphStore:
    def upsert_document_graph(self, document_id: str, text: str) -> None:
        raise NotImplementedError("Le branchement Neo4j est prepare mais non implemente dans ce MVP.")

    def expand_context(self, seed_ids: list[str]) -> list[str]:
        raise NotImplementedError("Le branchement Neo4j est prepare mais non implemente dans ce MVP.")
