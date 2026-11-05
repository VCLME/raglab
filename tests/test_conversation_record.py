"""What one turn leaves in the conversation history, built without a database."""

from __future__ import annotations

from raglab.config import Settings
from raglab.conversations.record import (
    cited_ranks,
    failed_turn,
    resolved_options,
    retrieved_sources,
    turn_from_response,
)
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.domain.schemas import QueryResponse, RetrievedChunk


def _chunk(rank: int, file_name: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{rank}",
        document_id=f"d{rank}",
        file_name=file_name,
        source_path=f"data/{file_name}",
        chunk_text=f"Article {rank}. Texte.",
        score=1.0 / rank,
        rank=rank,
        char_start=rank * 100,
        char_end=rank * 100 + 20,
    )


def _response(**extra) -> QueryResponse:
    fields = {
        "question": "Quelle est la durée du mandat ?",
        "index_run_id": "11111111-1111-1111-1111-111111111111",
        "strategy": ChunkingStrategy.TRADITIONAL,
        "retrieved_chunks": [_chunk(1, "titre_II.txt"), _chunk(2, "titre_IV.txt")],
        "retrieval_mode": RetrievalMode.HYBRID,
        "answer": "Le Président est élu pour cinq ans [Rank 1].\n\nSources : [Rank 2]",
        "llm_provider": "ollama",
        "timings_ms": {"embed": 10.0, "retrieval": 5.0, "generation": 900.0},
        "elapsed_ms": 920.0,
    }
    fields.update(extra)
    return QueryResponse(**fields)


def test_cited_ranks_reads_the_rank_markers_but_not_a_trailing_sources_list():
    assert cited_ranks("A [Rank 1], B [rank 3] et [Source rank=4].\n\nSources : [Rank 2]") == {1, 3, 4}
    assert cited_ranks(None) == set()


def test_retrieved_sources_keep_offsets_and_flag_cited_passages():
    sources = retrieved_sources([_chunk(1, "a.txt"), _chunk(2, "b.txt")], "Réponse [Rank 2].")
    assert sources[0] == {
        "chunk_id": "c1",
        "document_id": "d1",
        "file_name": "a.txt",
        "source_path": "data/a.txt",
        "char_start": 100,
        "char_end": 120,
        "rank": 1,
        "score": 1.0,
        "cited": False,
    }
    assert sources[1]["cited"] is True


def test_resolved_options_fill_server_defaults_and_keep_what_ran():
    settings = Settings(default_top_k=5, rrf_k=60, hybrid_lexical_weight=0.5, versions_default="in_force")
    options = resolved_options(settings, {"top_k": 8, "rerank": None, "routing": True}, _response(rerank=True))
    assert options["top_k"] == 8
    assert options["rrf_k"] == 60
    assert options["versions"] == "in_force"
    assert options["routing"] is True
    # The response wins: it says what the pipeline did.
    assert options["retrieval_mode"] == "hybrid"
    assert options["rerank"] is True
    assert options["index_run_id"] == "11111111-1111-1111-1111-111111111111"


def test_turn_from_response_records_the_presented_context_and_the_model():
    settings = Settings(generation_model="qwen2.5:7b")
    turn = turn_from_response(_response(), settings=settings, requested={}, corpus_name="constitution")
    assert turn.status == "completed"
    assert turn.corpus_name == "constitution"
    assert turn.llm_model == "qwen2.5:7b"
    assert turn.language == "fr"
    assert len(turn.presented_context) == 2
    assert turn.presented_context[0].startswith("[Source rank=1]\nFichier: titre_II.txt")
    assert [source["cited"] for source in turn.retrieved] == [True, False]


def test_no_presented_context_when_nothing_was_generated():
    settings = Settings()
    turn = turn_from_response(_response(answer=None), settings=settings, requested={"generate": False}, corpus_name="c")
    assert turn.presented_context == []
    assert len(turn.retrieved) == 2


def test_failed_turn_keeps_the_question_and_the_error():
    turn = failed_turn(
        "Qual é o prazo?",
        settings=Settings(),
        requested={"llm_provider": "ollama"},
        corpus_name="lexml",
        error="Ollama indisponible",
    )
    assert (turn.status, turn.error, turn.language) == ("failed", "Ollama indisponible", "pt")
    assert turn.retrieved == []
