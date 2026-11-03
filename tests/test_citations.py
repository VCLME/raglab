from __future__ import annotations

import pytest

from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.citations import Citation, article_start_pattern, merge_with_citation, parse_citation


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("O que dispõe o art. 2 da Lei nº 7.689 de 15/12/1988?", Citation("7689", "2", 1988)),
        ("O que estabelece o § 2o do art. 54 da Lei nº 11.697 de 13/06/2008?", Citation("11697", "54", 2008)),
        ("O que dispõe o art. 19 da Lei nº 7.998?", Citation("7998", "19", None)),
        ("Segundo o artigo 49 da Lei 8078/90, qual o prazo?", Citation("8078", "49", 1990)),
        ("Qual é a regra do art. 11-A da Lei nº 12.704?", Citation("12704", "11-A", None)),
        ("A Lei Complementar nº 101 trata de quê?", Citation("101", None, None)),
    ],
)
def test_parse_citation(question, expected):
    assert parse_citation(question) == expected


def test_questions_without_a_law_number_are_left_alone():
    assert parse_citation("Qual é o prazo para desistir de uma compra?") is None
    assert parse_citation("Quem fiscaliza o FGTS segundo a lei?") is None


@pytest.mark.parametrize(
    ("article", "text", "matches"),
    [
        ("2", "TÍTULO I\nArt. 2º A base de cálculo", True),
        ("2", "Art. 2o A alíquota", True),
        ("49", "Art. 49. O consumidor pode desistir", True),
        ("2", "Art. 20. Outra regra", False),
        ("2", "conforme o art. 2º da Lei 9.000", False),  # a reference, not the article itself
        ("11-A", "Art. 11-A. Ter menos de 29 anos", True),
        ("11", "Art. 11-A. Ter menos de 29 anos", False),
    ],
)
def test_article_start_pattern(article, text, matches):
    assert bool(article_start_pattern(article).search(text)) is matches


def _chunk(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="d",
        file_name="lei.txt",
        source_path="lei.txt",
        chunk_text="t",
        score=0.5,
        rank=rank,
    )


def test_pinned_article_chunks_come_first_without_duplicates():
    pinned = [_chunk("art", 1).model_copy(update={"citation_match": True, "score": 1.0})]
    ranked = [_chunk("a", 1), _chunk("art", 2), _chunk("b", 3)]
    merged = merge_with_citation(pinned, ranked, top_k=3)
    assert [c.chunk_id for c in merged] == ["art", "a", "b"]
    assert [c.rank for c in merged] == [1, 2, 3]
    assert merged[0].citation_match


def test_long_article_chunks_are_ordered_by_retrieval_rank():
    pinned = [_chunk(f"art{i}", i) for i in range(1, 5)]
    ranked = [_chunk("art3", 1), _chunk("other", 2), _chunk("art1", 3)]
    merged = merge_with_citation(pinned, ranked, top_k=5)
    assert [c.chunk_id for c in merged] == ["art3", "art1", "art2", "art4", "other"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Que prévoit l'article L. 221-18 du Code de la consommation ?",
            Citation(None, "L221-18", code="consommation"),
        ),
        ("Que dit l'art. R. 212-1 sur l'étiquetage ?", Citation(None, "R212-1")),
        ("Que dispose l'article 1240 du code civil ?", Citation(None, "1240", code="civil")),
        (
            "Selon le code de la consommation, que prévoit l'article L221-18 ?",
            Citation(None, "L221-18", code="consommation"),
        ),
        (
            "Quelles obligations fixe l'article L. 312-1 du code monétaire et financier ?",
            Citation(None, "L312-1", code="monetaire_financier"),
        ),
    ],
)
def test_parse_french_code_citations(question, expected):
    assert parse_citation(question) == expected


def test_french_questions_without_an_identifiable_article_are_left_alone():
    assert parse_citation("Quel est le délai de rétractation pour un achat en ligne ?") is None
    # A plain number is an article only when a code is named right after it.
    assert parse_citation("Que dit l'article 4 de la loi n° 89-462 ?") is None
    assert parse_citation("Que dit l'article 1240 ?") is None


def test_brazilian_citations_still_win_and_portuguese_articles_are_not_french():
    assert parse_citation("O que dispõe o art. 49 da Lei nº 8.078?") == Citation("8078", "49")
    assert parse_citation("Qual é a regra do art. 11-A?") is None


def test_french_citation_label():
    assert Citation(None, "L221-18", code="consommation").label() == "art. L. 221-18 — Code de la consommation"
    assert Citation(None, "R212-1").label() == "art. R. 212-1"
    assert Citation("8078", "49", 1990).label() == "art. 49 — Lei nº 8078 (1990)"
