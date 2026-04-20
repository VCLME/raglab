from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CHUNK_LABEL = "Chunk"
"""Neo4j label for chunk nodes."""


def embedding_property(dim: int) -> str:
    """Return the chunk property name that stores embeddings of `dim`.

    One property per dimension lets multiple embedding spaces coexist on
    the same Chunk label while keeping each Neo4j vector index attached
    to a single, fixed-dimension property (the planner constraint).
    """
    if dim <= 0:
        raise ValueError(f"Invalid embedding dimension: {dim}")
    return f"embedding_d{dim}"


def vector_index_name(dim: int) -> str:
    return f"chunk_embedding_d{dim}"


def ensure_vector_index(driver, dim: int, *, similarity: str = "cosine") -> str:
    """Create (if needed) a Neo4j 5 vector index on :Chunk for the given dim.

    Mirrors `ensure_partial_hnsw_index` on the pgvector side — one index
    per embedding dimension. Returns the index name.
    """
    if dim <= 0:
        raise ValueError(f"Invalid embedding dimension: {dim}")
    prop = embedding_property(dim)
    name = vector_index_name(dim)
    cypher = (
        f"CREATE VECTOR INDEX {name} IF NOT EXISTS "
        f"FOR (c:{CHUNK_LABEL}) ON (c.{prop}) "
        "OPTIONS {indexConfig: {"
        f" `vector.dimensions`: {dim},"
        f" `vector.similarity_function`: '{similarity}'"
        " }}"
    )
    with driver.session() as session:
        session.run(cypher)
    logger.debug("neo4j.vector_index_ensured", extra={"name": name, "dim": dim})
    return name
