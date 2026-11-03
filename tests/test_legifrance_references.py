from __future__ import annotations

import pytest

from raglab.legifrance.codes import find_code_mentions
from raglab.legifrance.references import article_label, extract_references, normalize_article_number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("L. 221-18", "L221-18"),
        ("L221-18", "L221-18"),
        ("article R. 212-1", "R212-1"),
        ("R*112-1", "R112-1"),
        ("L. 121-21-1", "L121-21-1"),
        ("LO. 132-1", "LO132-1"),
        ("1240", "1240"),
        ("1er", "1"),
        ("liminaire", "liminaire"),
        ("L. 221‑18", "L221-18"),  # non-breaking hyphen
    ],
)
def test_normalize_article_number(raw, expected):
    assert normalize_article_number(raw) == expected


def test_article_label_is_citation_style():
    assert article_label("L221-18") == "L. 221-18"
    assert article_label("1240") == "1240"


def test_code_names_are_found_with_or_without_accents_and_abbreviated():
    text = "l'article L. 312-1 du code monetaire et financier, puis C. consom. et le Code rural et de la pêche maritime"
    assert [mention.slug for mention in find_code_mentions(text)] == ["monetaire_financier", "consommation", "rural"]
    # The longest alias wins: "code rural et de la pêche maritime", not "code rural".
    assert find_code_mentions("code rural et de la pêche maritime")[0].end == len("code rural et de la pêche maritime")


def _refs(text: str) -> list[tuple[str, str | None]]:
    return [(ref.article, ref.code) for ref in extract_references(text)]


def test_unqualified_references_point_into_the_citing_code():
    text = "sans supporter d'autres coûts que ceux prévus aux articles L. 221-23 à L. 221-25."
    assert _refs(text) == [("L221-23", None), ("L221-24", None), ("L221-25", None)]
    implied = [ref for ref in extract_references(text) if ref.from_range]
    assert [ref.article for ref in implied] == ["L221-24"]


def test_an_enumeration_shares_the_code_named_after_it():
    text = "Les articles L. 312-1, L. 312-2 et L. 312-3 du code monétaire et financier sont applicables."
    assert _refs(text) == [
        ("L312-1", "monetaire_financier"),
        ("L312-2", "monetaire_financier"),
        ("L312-3", "monetaire_financier"),
    ]


def test_present_code_same_code_and_unknown_codes():
    text = (
        "au 7° de l'article L. 221-5 du présent code ; l'article L. 1111-2 du code de la santé publique "
        "et l'article L. 1111-3 du même code ; l'article L. 111-8 du code des procédures civiles d'exécution."
    )
    assert _refs(text) == [
        ("L221-5", None),
        ("L1111-2", "sante_publique"),
        ("L1111-3", "sante_publique"),
        ("L111-8", "other"),
    ]


def test_numbers_without_part_letter_or_hyphen_are_not_references():
    text = "la loi n° 2014-344 du 17 mars 2014, le décret n° 2016-884 et l'article 4 du règlement (UE) 2016/679"
    assert _refs(text) == []


def test_ranges_are_expanded_only_between_close_numbers_of_one_stem():
    assert [r.article for r in extract_references("articles L. 221-1 à L. 223-2")] == ["L221-1", "L223-2"]
