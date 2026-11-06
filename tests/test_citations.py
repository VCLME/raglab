from __future__ import annotations

import pytest

from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.citations import (
    Citation,
    CitationResolution,
    article_start_pattern,
    code_version,
    law_article_version,
    merge_with_citation,
    parse_citation,
)


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


def test_article_chunks_ranked_beyond_the_window_keep_reading_order():
    # With de-duplication the re-ranker returns its whole pool; the article
    # must be ordered as from the top-k alone, or the option changes
    # passages it does not drop.
    pinned = [_chunk(f"art{i}", i) for i in range(1, 5)]
    ranked = [_chunk("art3", 1), _chunk("other", 2), _chunk("art4", 3), _chunk("art2", 4)]
    window = merge_with_citation(pinned, ranked, top_k=4, order_within=2)
    alone = merge_with_citation(pinned, ranked[:2], top_k=4)
    assert [c.chunk_id for c in window] == ["art3", "art1", "art2", "art4"]
    assert [c.chunk_id for c in window] == [c.chunk_id for c in alone]


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


GDPR = "32016R0679"


@pytest.mark.parametrize(
    ("question", "celex", "unit", "number", "paragraph", "point", "language"),
    [
        ("Que dit l'article 32 du RGPD ?", GDPR, "article", "32", None, None, "fr"),
        ("What does Article 6(1)(a) GDPR require?", GDPR, "article", "6", "1", "a", "en"),
        ("O que prevê o artigo 5.º do Regulamento (UE) 2016/679?", GDPR, "article", "5", None, None, "pt"),
        ("Que dit le considérant 39 du RGPD ?", GDPR, "recital", "39", None, None, "fr"),
        ("What does Annex III of the AI Act list?", "32024R1689", "annex", "III", None, None, "en"),
        (
            "Under Article 4a of the AI Act, may providers process special data?",
            "32024R1689",
            "article",
            "4a",
            None,
            None,
            "en",
        ),
        (
            "Quelles obligations impose l'article 28, paragraphe 2, du règlement (UE) 2022/2554 ?",
            "32022R2554",
            "article",
            "28",
            "2",
            None,
            "fr",
        ),
        ("Que dit l'article 21 de la directive NIS 2 ?", "32022L2555", "article", "21", None, None, "fr"),
    ],
)
def test_parse_eu_citations(question, celex, unit, number, paragraph, point, language):
    citation = parse_citation(question)
    assert citation is not None and citation.law_number is None and citation.code is None
    assert (citation.celex, citation.unit, citation.article, citation.paragraph, citation.point, citation.language) == (
        celex,
        unit,
        number,
        paragraph,
        point,
        language,
    )


def test_eu_act_named_without_a_unit_and_labels():
    citation = parse_citation("What does the GDPR say about consent?")
    assert citation is not None and (citation.celex, citation.unit, citation.article) == (GDPR, None, None)
    assert citation.label() == "GDPR"
    assert parse_citation("What does Article 6(1)(a) GDPR require?").label() == "Article 6(1)(a) — GDPR"
    assert parse_citation("Que dit le considérant 39 du RGPD ?").label() == "Considérant 39 — RGPD"
    # The act named right after the unit wins.
    assert parse_citation("Que dit l'article 5 de DORA, et l'article 6 du RGPD ?").celex == "32022R2554"


def test_eu_profile_leaves_the_other_profiles_alone():
    assert parse_citation("O que dispõe o art. 49 da Lei nº 8.078?") == Citation("8078", "49")
    assert parse_citation("Que dispose l'article 1240 du code civil ?") == Citation(None, "1240", code="civil")
    assert parse_citation("Que prévoit l'article L. 221-18 du Code de la consommation ?") == Citation(
        None, "L221-18", code="consommation"
    )
    # An article number without an act or a recital is not an EU citation.
    assert parse_citation("What does Article 6 say about lawfulness?") is None


# Audit 2026-11-04, lot 1: act, unit and version are checked apart.


@pytest.mark.parametrize(
    ("question", "article"),
    [
        ("O que diz o art. 1.723 da Lei nº 10.406?", "1723"),
        ("Segundo o artigo 1.723 da Lei 10.406/2002, o que é união estável?", "1723"),
        ("O que diz o art. 49 da Lei nº 8.078?", "49"),
    ],
)
def test_article_numbers_with_a_thousands_dot_are_read_whole(question, article):
    citation = parse_citation(question)
    assert citation is not None
    assert citation.article == article


@pytest.mark.parametrize(
    ("text", "matches"),
    [
        ("Art. 1.723. É reconhecida como entidade familiar", True),
        ("Art. 1723. É reconhecida", True),
        ("Art. 1º Toda pessoa é capaz", False),
        ("Art. 1.724. As relações pessoais", False),
    ],
)
def test_article_start_pattern_reads_thousands_dots(text, matches):
    assert bool(article_start_pattern("1723").search(text)) is matches


@pytest.mark.parametrize(
    ("resolution", "status", "exempt"),
    [
        (CitationResolution(act_found=True, unit_requested=True, unit_found=True), "found", True),
        (CitationResolution(act_found=True, unit_requested=False, unit_found=False), "act_only", True),
        (CitationResolution(act_found=True, unit_requested=True, unit_found=False), "unit_not_found", False),
        (CitationResolution(act_found=False, unit_requested=True, unit_found=False), "act_not_found", False),
        (CitationResolution(act_found=False, unit_requested=False, unit_found=False), "act_not_found", False),
    ],
)
def test_citation_status_separates_the_act_from_the_unit(resolution, status, exempt):
    assert resolution.status == status
    assert resolution.exempt is exempt


@pytest.mark.parametrize(
    ("etat", "version"),
    [
        ("VIGUEUR", "in_force"),
        ("ABROGE_DIFF", "in_force"),
        ("VIGUEUR_DIFF", "not_yet_in_force"),
        ("ABROGE", "historical"),
        ("MODIFIE", "historical"),
        (None, None),
    ],
)
def test_code_article_version(etat, version):
    assert code_version(etat) == version


def _text_chunk(text: str) -> RetrievedChunk:
    return _chunk("c1", 1).model_copy(update={"chunk_text": text})


def test_a_repealed_brazilian_article_is_historical():
    assert law_article_version([_text_chunk("Art. 5º (Revogado pela Lei nº 9.000, de 1995)")], "5") == "historical"
    assert law_article_version([_text_chunk("Art. 5º O visto será concedido")], "5") == "in_force"
    # "(Revogado)" further down belongs to a paragraph, not to the article.
    text = "Art. 5º O visto será concedido.\n§ 1º (Revogado)."
    assert law_article_version([_text_chunk(text)], "5") == "in_force"
    assert law_article_version([], "5") is None


@pytest.mark.parametrize(
    "question",
    [
        "Que dit l'article 412 du RGPD ?",
        "What does Article 140 of DORA require?",
        "O que diz o artigo 999.º do Regulamento (UE) 2016/679?",
    ],
)
def test_eu_citations_of_any_number_still_parse(question):
    """Parsing does not judge the number: whether the unit exists is the
    index's call (status unit_not_found)."""
    citation = parse_citation(question)
    assert citation is not None and citation.celex is not None and citation.unit == "article"


@pytest.mark.parametrize(
    ("question", "unit", "number"),
    [
        ("Que dit l'art 32 du RGPD ?", "article", "32"),
        ("Que dit l'art 999 du RGPD ?", "article", "999"),
        ("Que dit l'art.32 du RGPD ?", "article", "32"),
    ],
)
def test_abbreviated_eu_units_are_not_read_as_a_bare_act(question, unit, number):
    """A bare act is never declined: an unread abbreviation must keep its unit."""
    citation = parse_citation(question)
    assert citation is not None and citation.unit == unit and citation.article == number


def test_an_eu_act_named_without_a_unit_stays_a_bare_act():
    citation = parse_citation("Que prévoit le RGPD pour les sous-traitants ?")
    assert citation is not None and citation.celex == "32016R0679" and citation.unit is None


def test_an_article_split_from_its_number_by_a_chunk_boundary_is_found():
    """lexml-0257: one chunk ends with "Art.", the next opens with "5º A lei…"."""
    from types import SimpleNamespace

    from raglab.retrieval.citations import _split_article_start

    rows = [
        SimpleNamespace(text="Art. 4º O orçamento…\nArt."),
        SimpleNamespace(text="5º A lei orçamentária observará…"),
        SimpleNamespace(text="Art. 6º Outra regra"),
    ]
    assert _split_article_start(rows, "5") == 1
    assert _split_article_start(rows, "6") is None  # found the usual way, not here
    assert _split_article_start(rows, "50") is None
