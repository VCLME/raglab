from raglab.chunking.base import Chunker, ChunkingConfig
from raglab.chunking.late import LateChunker
from raglab.chunking.slide import SlideChunker
from raglab.chunking.traditional import TraditionalChunker
from raglab.domain.enums import ChunkingStrategy


def build_chunker(config: ChunkingConfig) -> Chunker:
    if config.strategy == ChunkingStrategy.TRADITIONAL:
        return TraditionalChunker(config)
    if config.strategy == ChunkingStrategy.SLIDE:
        return SlideChunker(config)
    if config.strategy == ChunkingStrategy.LATE:
        return LateChunker(config)
    raise ValueError(f"Strategie de chunking inconnue: {config.strategy}")
