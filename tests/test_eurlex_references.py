from __future__ import annotations

import pytest

from raglab.eurlex.acts import celex_label
from raglab.eurlex.references import (
    amended_act,
    citation_act,
    extract_references,
    find_act_names,
    find_acts,
    normalize_number,
)

AI_ACT = "32024R1689"
GDPR = "32016R0679"


def _refs(text: str, language: str, own: str = AI_ACT, context: str | None = None):
    return [
        (ref.unit, ref.number, ref.paragraph, ref.point, ref.celex, ref.scope)
        for ref in extract_references(text, language, own_celex=own, context_celex=context)
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Regulation (EU) 2016/679", "32016R0679"),
        ("règlement (UE) no 1093/2010", "32010R1093"),
        ("Regulamento (UE) n.º 600/2014", "32014R0600"),
        ("Directive 95/46/EC", "31995L0046"),
        ("Diretiva (UE) 2022/2555", "32022L2555"),
        ("Commission Delegated Regulation (EU) 2024/1774", "32024R1774"),
        ("Décision d'exécution (UE) 2021/914", "32021D0914"),
        ("recommandation 2003/361/CE", "32003H0361"),
    ],
)
def test_numbered_acts_get_their_celex(text: str, expected: str):
    assert [mention.celex for mention in find_acts(text)] == [expected]


def test_plural_acts_and_treaties():
    mentions = find_acts("Regulations (EU) 2016/679 and (EU) 2018/1725 and the TFEU")
    assert [mention.celex for mention in mentions] == ["32016R0679", "32018R1725", None]


def test_short_names_in_three_languages():
    names = find_act_names("l'article 32 du RGPD, the AI Act, la directive NIS 2, DORA, o Regulamento IA, dora")
    assert [mention.celex for mention in names] == [GDPR, AI_ACT, "32022L2555", "32022R2554", AI_ACT]


def test_english_references():
    text = (
        "Irrespective of point (a) of Article 6(1), in accordance with Article 10(2), points (f) and (g), of this "
        "Regulation. Article 9(1) of Regulation (EU) 2016/679 applies. Articles 12 to 14 apply. See Annex III, "
        "Annexes I and II and recital 39. Article 16 TFEU. Articles 13 and 14 of that Regulation."
    )
    assert _refs(text, "en") == [
        ("article", "6", "1", "a", AI_ACT, "same_act"),
        ("article", "10", "2", "f", AI_ACT, "same_act"),
        ("article", "9", "1", None, GDPR, "other_act"),
        ("article", "12", None, None, AI_ACT, "same_act"),
        ("article", "13", None, None, AI_ACT, "same_act"),
        ("article", "14", None, None, AI_ACT, "same_act"),
        ("annex", "III", None, None, AI_ACT, "same_act"),
        ("annex", "I", None, None, AI_ACT, "same_act"),
        ("annex", "II", None, None, AI_ACT, "same_act"),
        ("recital", "39", None, None, AI_ACT, "same_act"),
        ("article", "16", None, None, None, "treaty"),
        ("article", "13", None, None, GDPR, "anaphora"),
        ("article", "14", None, None, GDPR, "anaphora"),
    ]


def test_french_references():
    text = (
        "conformément à l'article 6, paragraphe 1, point a), du présent règlement, à l'article 9, paragraphe 2, du "
        "règlement (UE) 2016/679, aux articles 12 à 14 et au considérant 39; articles 13 et 14 dudit règlement."
    )
    assert _refs(text, "fr") == [
        ("article", "6", "1", "a", AI_ACT, "same_act"),
        ("article", "9", "2", None, GDPR, "other_act"),
        ("article", "12", None, None, AI_ACT, "same_act"),
        ("article", "13", None, None, AI_ACT, "same_act"),
        ("article", "14", None, None, AI_ACT, "same_act"),
        ("recital", "39", None, None, AI_ACT, "same_act"),
        ("article", "13", None, None, GDPR, "anaphora"),
        ("article", "14", None, None, GDPR, "anaphora"),
    ]


def test_portuguese_references():
    text = (
        "nos termos do artigo 6.º, n.º 1, alínea a), do presente regulamento e do artigo 3.º, alínea b), da "
        "Diretiva (UE) 2022/2555, dos artigos 25.º a 27.º e 42.º, do anexo III e do artigo 4.º-A."
    )
    assert _refs(text, "pt") == [
        ("article", "6", "1", "a", AI_ACT, "same_act"),
        ("article", "3", None, "b", "32022L2555", "other_act"),
        ("article", "25", None, None, AI_ACT, "same_act"),
        ("article", "26", None, None, AI_ACT, "same_act"),
        ("article", "27", None, None, AI_ACT, "same_act"),
        ("article", "42", None, None, AI_ACT, "same_act"),
        ("annex", "III", None, None, AI_ACT, "same_act"),
        ("article", "4a", None, None, AI_ACT, "same_act"),
    ]


def test_a_point_range_is_not_an_article_range():
    # DORA recital 40: points 4) to 23) of Article 2(5) of Directive 2013/36/EU.
    text = "les entités visées à l’article 2, paragraphe 5, points 4) à 23), de la directive 2013/36/UE"
    assert _refs(text, "fr", own="32022R2554") == [("article", "2", "5", "4", "32013L0036", "other_act")]


def test_the_act_named_after_a_pair_applies_to_both():
    text = "pursuant to Article 46(1) and Article 46(2)(c) of Regulation (EU) 2016/679"
    assert [ref[4] for ref in _refs(text, "en", own="32021D0914")] == [GDPR, GDPR]
    text = "à l'article 9 et à l'article 10 du règlement (UE) 2016/679"
    assert [ref[4] for ref in _refs(text, "fr", own="32021D0914")] == [GDPR, GDPR]


def test_possessives_point_to_the_act_named_before():
    text = "A Diretiva 2000/31/CE ... previstas nos seus artigos 12.º a 13.º."
    assert [(ref[1], ref[4]) for ref in _refs(text, "pt", own=GDPR)] == [("12", "32000L0031"), ("13", "32000L0031")]
    text = "règlement (UE) 2016/679 (en vertu de son article 3, paragraphe 2)"
    assert [(ref[1], ref[4]) for ref in _refs(text, "fr", own="32021D0914")] == [("3", GDPR)]


def test_recommendation_articles_are_not_articles_of_the_act():
    text = "en vertu de l’article 2 de l’annexe de la recommandation 2003/361/CE"
    assert _refs(text, "fr", own="32022L2555")[0][4] == "32003H0361"


def test_preamble_citation_is_about_the_act_it_names():
    text = (
        "vu le règlement (UE) 2022/2554 du Parlement européen et du Conseil modifiant les règlements (CE) nº 1060/2009 "
        "et (UE) 2016/1011, et notamment son article 15, quatrième alinéa, et son article 16, paragraphe 3,"
    )
    context = citation_act(text)
    assert context == "32022R2554"
    assert [(ref[1], ref[4], ref[5]) for ref in _refs(text, "fr", own="32024R1774", context=context)] == [
        ("15", "32022R2554", "context"),
        ("16", "32022R2554", "context"),
    ]
    assert citation_act("Having regard to the Treaty on the Functioning of the European Union") is None


def test_amending_articles_speak_about_the_amended_act():
    text = "Regulation (EU) 2024/1689 is amended as follows: (1) in Article 2, paragraph 3 is replaced"
    assert amended_act(text) == AI_ACT
    assert amended_act("O Regulamento (UE) 2024/1689 é alterado do seguinte modo:") == AI_ACT
    assert amended_act("This Regulation shall enter into force") is None


@pytest.mark.parametrize(
    ("raw", "expected"), [("6", "6"), ("4a", "4a"), ("4 bis", "4a"), ("4.º-A", "4a"), ("6.º", "6"), ("25.º a", "25")]
)
def test_normalize_number(raw: str, expected: str):
    assert normalize_number(raw) == expected


def test_celex_labels_follow_the_numbering_of_their_time():
    assert celex_label("32016R0679") == "Regulation (EU) 2016/679"
    assert celex_label("32010R1093") == "Regulation (EU) No 1093/2010"
    assert celex_label("32013L0036") == "Directive 2013/36/EU"
    assert celex_label("31995L0046", "fr") == "directive 95/46/CE"


def test_respectively_does_not_hide_the_qualifier():
    # DORA recital 34: GDPR Article 6, not DORA Article 6.
    for language, text in (
        ("en", "Regulation (EU) 2016/679. Article 6(1), points (c) and (e), respectively, of that Regulation."),
        ("fr", "règlement (UE) 2016/679. l’article 6, paragraphe 1, points c) et e), respectivement, dudit règlement."),
        ("pt", "Regulamento (UE) 2016/679. o artigo 6.º, n.º 1, alíneas c) e e), respetivamente, desse regulamento."),
    ):
        assert [(ref[1], ref[4]) for ref in _refs(text, language, own="32022R2554")] == [("6", GDPR)]


@pytest.mark.parametrize(
    ("language", "text", "own", "expected"),
    [
        # "of that Annex" / "do referido anexo": the annex of the recommendation named before.
        (
            "en",
            "Recommendation 2003/361/EC. as defined in Article 2(2) and (3) of that Annex",
            "32022L2555",
            "32003H0361",
        ),
        (
            "fr",
            "recommandation 2003/361/CE. au sens de l’article 2, paragraphes 2 et 3, de ladite annexe",
            "32022L2555",
            "32003H0361",
        ),
        (
            "pt",
            "Recomendação 2003/361/CE. na aceção do artigo 2.º, n.ºs 2 e 3, do referido anexo",
            "32022L2555",
            "32003H0361",
        ),
        # A reference in brackets right after the act it belongs to.
        ("pt", "sujeito ao Regulamento (UE) 2016/679 (nos termos do artigo 3.º, n.º 2), por", "32021D0914", GDPR),
        # Sub-points and points without brackets before the qualifier.
        ("fr", "définies à l’article 2, point 1) c), du règlement (UE) nº 1025/2012", AI_ACT, "32012R1025"),
        (
            "fr",
            "figurant à l’article 2, paragraphe 1, point 35, de la directive 2014/59/UE",
            "32022R2554",
            "32014L0059",
        ),
        # Case of the kind word does not matter in an anaphora.
        (
            "pt",
            "Regulamento (UE) 2019/1020. Em consonância com o artigo 33.º do referido Regulamento",
            AI_ACT,
            "32019R1020",
        ),
    ],
)
def test_qualifiers_read_in_rules_v5(language, text, own, expected):
    refs = _refs(text, language, own=own)
    assert refs[0][4] == expected


def test_pairs_joined_by_pelo_share_their_act_and_implicit_is_recorded():
    text = "pelo artigo 6.º, n.º 1, alínea c), e pelo artigo 6.º, n.º 3, do Regulamento (UE) 2016/679."
    assert [ref[4] for ref in _refs(text, "pt", own="32022L2555")] == [GDPR, GDPR]
    (explicit, implicit) = extract_references(
        "Article 26(10) of this Regulation and Article 5(1)", "en", own_celex=AI_ACT
    )
    assert (explicit.implicit, implicit.implicit) == (False, True)
    assert implicit.as_metadata()["implicit"] is True and "implicit" not in explicit.as_metadata()
