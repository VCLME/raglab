from raglab.chunking.base import ChunkingConfig
from raglab.chunking.factory import build_chunker
from raglab.domain.enums import ChunkingStrategy

TEXT = (
    "Alpha présente le contexte. "
    "Beta ajoute un détail utile. "
    "Gamma introduit une contrainte. "
    "Delta conclut avec une synthèse."
)


def test_traditional_chunker_returns_chunks():
    chunker = build_chunker(
        ChunkingConfig(
            strategy=ChunkingStrategy.TRADITIONAL,
            chunk_size=45,
            chunk_overlap=10,
        )
    )
    chunks = chunker.chunk_text(TEXT)
    assert len(chunks) >= 2
    assert chunks[0].strategy == ChunkingStrategy.TRADITIONAL


def test_slide_chunker_overlaps_windows():
    chunker = build_chunker(
        ChunkingConfig(
            strategy=ChunkingStrategy.SLIDE,
            chunk_size=60,
            chunk_overlap=0,
            slide_stride=25,
        )
    )
    chunks = chunker.chunk_text(TEXT)
    assert len(chunks) >= 2
    assert chunks[0].char_start < chunks[1].char_start
    assert chunks[0].char_end > chunks[1].char_start


def test_late_chunker_populates_contextual_embedding_fields():
    chunker = build_chunker(
        ChunkingConfig(
            strategy=ChunkingStrategy.LATE,
            chunk_size=55,
            chunk_overlap=5,
            late_context_chars=20,
        )
    )
    chunks = chunker.chunk_text(TEXT)
    assert chunks
    assert chunks[0].embedding_text is not None
    assert chunks[0].embedding_span is not None
