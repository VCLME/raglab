from __future__ import annotations

from raglab.domain.schemas import RetrievedChunk
from raglab.domain.versions import ChunkVersion
from raglab.retrieval.dedup import redundant, select_distinct

DOC = "Da Alíquota\nArt. 22. A alíquota do IOF é de vinte e cinco por cento."


def _chunk(
    chunk_id: str, start: int, end: int, *, document: str = "d1", text: str | None = None, **extra
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document,
        file_name=f"{document}.txt",
        source_path=f"{document}.txt",
        chunk_text=text if text is not None else DOC[start:end],
        score=1.0,
        rank=1,
        char_start=start,
        char_end=end,
        **extra,
    )


def test_a_cut_inside_a_kept_passage_is_redundant():
    """Brazil expat Q28: the same sentence cut twice from one document."""
    whole = _chunk("a", 0, len(DOC))
    tail = _chunk("b", 12, len(DOC))
    assert redundant(tail, whole)


def test_what_a_passage_adds_beyond_the_overlap_is_protected():
    long_text = "1º, incisos II e III). " + DOC
    longer = _chunk("c", 0, len(long_text), text=long_text)
    kept = _chunk("a", 23, len(long_text), text=DOC)
    # 84 % overlap, but the extra part carries numbers: kept apart.
    assert not redundant(longer, kept)
    plain_text = "Seção única. " + DOC
    plain = _chunk("d", 0, len(plain_text), text=plain_text)
    assert redundant(plain, _chunk("a", 13, len(plain_text), text=DOC))


def test_negations_and_exceptions_are_protected():
    for extra in ("Não se aplica. ", "Salvo disposição. ", "Sauf exception. ", "Except where noted. "):
        text = extra + DOC
        assert not redundant(_chunk("x", 0, len(text), text=text), _chunk("a", len(extra), len(text), text=DOC))


def test_other_documents_and_other_versions_never_merge_on_overlap():
    whole = _chunk("a", 0, len(DOC))
    assert not redundant(_chunk("b", 12, len(DOC), document="d2"), whole)
    old = ChunkVersion(source="metadata", etat="ABROGE", in_force=False)
    new = ChunkVersion(source="metadata", etat="VIGUEUR", in_force=True)
    assert not redundant(_chunk("b", 12, len(DOC), version=old), _chunk("a", 0, len(DOC), version=new))


def test_identical_wording_at_another_place_is_kept():
    """Another article or law with the same words is another provision
    (audit lot 3, v1 merged them and lost 4 questions)."""
    assert not redundant(_chunk("b", 0, len(DOC), document="d2"), _chunk("a", 0, len(DOC)))
    # Same document, a repeated paragraph elsewhere: no overlap, kept.
    assert not redundant(_chunk("b", 500, 500 + len(DOC), text=DOC), _chunk("a", 0, len(DOC)))


def test_freed_places_are_refilled_from_the_pool_with_provenance_kept():
    pool = [
        _chunk("a", 0, len(DOC)),
        _chunk("b", 12, len(DOC)),  # repeats a
        _chunk("c", 0, 10, document="d2", text="autre"),
        _chunk("d", 0, 10, document="d3", text="encore"),
    ]
    kept, stats = select_distinct(pool, 3)
    assert [chunk.chunk_id for chunk in kept] == ["a", "c", "d"]
    assert [chunk.rank for chunk in kept] == [1, 2, 3]
    assert (kept[1].char_start, kept[1].char_end, kept[1].document_id) == (0, 10, "d2")
    assert stats == {"pool": 4, "dropped": [{"chunk_id": "b", "duplicate_of": "a", "position": "2"}], "refilled": 1}


def test_pinned_citation_passages_are_never_dropped():
    pool = [_chunk("a", 0, len(DOC)), _chunk("b", 12, len(DOC), citation_match=True)]
    kept, stats = select_distinct(pool, 2)
    assert [chunk.chunk_id for chunk in kept] == ["a", "b"]
    assert stats["dropped"] == []


def test_a_pool_without_duplicates_is_unchanged():
    pool = [_chunk(c, 0, 5, document=c, text=c * 5) for c in "abcdef"]
    kept, stats = select_distinct(pool, 5)
    assert [chunk.chunk_id for chunk in kept] == list("abcde")
    assert stats["dropped"] == [] and stats["refilled"] == 0


def _service(chunks, **overrides):
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from raglab.config import Settings
    from raglab.retrieval.service import QueryService

    settings = Settings(**overrides)
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(
            id="run",
            strategy="traditional",
            corpus=SimpleNamespace(language="pt"),
            embedding_space=SimpleNamespace(
                dimension=5,
                provider=settings.embedding_provider,
                model_name=settings.embedding_model_name,
                distance_metric=settings.distance_metric,
                query_prefix=settings.query_prefix,
                passage_prefix=settings.passage_prefix,
            ),
        )
    )
    service.vector_store = Mock()
    service.vector_store.search.return_value = chunks
    embedder = Mock()
    embedder.embed_query.return_value = [0.1] * 5
    return service, patch("raglab.retrieval.service.build_embedding_provider", return_value=embedder)


def test_the_service_searches_a_deeper_pool_and_refills_with_dedup_on():
    pool = [
        _chunk("a", 0, len(DOC)),
        _chunk("b", 12, len(DOC)),
        *(_chunk(c, 0, 5, document=c, text=c * 5) for c in "cdefgh"),
    ]
    service, embedder = _service(pool, dedup_pool=8)
    with embedder:
        on = service.query(question="Qual a alíquota?", retrieval_mode="dense", rerank=False, dedup=True, top_k=5, generate_answer=False)
    assert service.vector_store.search.call_args.kwargs["top_k"] == 8
    assert [chunk.chunk_id for chunk in on.retrieved_chunks] == ["a", "c", "d", "e", "f"]
    assert on.dedup_stats["dropped"][0]["chunk_id"] == "b" and on.dedup_stats["refilled"] == 1
    assert "dedup" in on.timings_ms

    service, embedder = _service(pool[:5], dedup_pool=8)
    with embedder:
        off = service.query(question="Qual a alíquota?", retrieval_mode="dense", rerank=False, top_k=5, generate_answer=False)
    assert service.vector_store.search.call_args.kwargs["top_k"] == 5
    assert off.dedup_stats is None
    assert [chunk.chunk_id for chunk in off.retrieved_chunks] == ["a", "b", "c", "d", "e"]
