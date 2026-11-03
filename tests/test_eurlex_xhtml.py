from __future__ import annotations

from eurlex_fixtures import (
    consolidated_act,
    consolidated_paragraph,
    consolidated_point,
    oj_act,
    oj_paragraph,
)
from raglab.eurlex.xhtml import paragraph_structure, parse_act


def _gdpr_like() -> str:
    return oj_act(
        title="REGULATION (EU) 2016/679 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL",
        date="4.5.2016",
        citations=[
            "Having regard to the Treaty on the Functioning of the European Union, and in particular Article 16"
        ],
        recitals=['Any processing of personal data should be lawful and fair<span class="oj-note-tag">(1)</span>.'],
        articles=[
            (
                "6",
                "Article 6",
                "Lawfulness of processing",
                oj_paragraph(
                    "1",
                    "Processing shall be lawful only if:",
                    [("(a)", "the data subject has given consent;"), ("(b)", "processing is necessary;")],
                )
                + oj_paragraph("2", "Member States may maintain more specific provisions."),
            )
        ],
        annexes=[
            ("III", "ANNEX III", '<p class="oj-doc-ti">High-risk AI systems</p><p class="oj-normal">1. Biometrics</p>')
        ],
    )


def test_official_journal_units_are_split_and_rendered():
    act = parse_act(_gdpr_like())
    assert act.oj_date == "2016-05-04"
    assert act.title.startswith("REGULATION (EU) 2016/679")
    kinds = [(unit.kind, unit.number) for unit in act.units]
    assert kinds == [("citation", "1"), ("recital", "1"), ("article", "6"), ("annex", "III")]
    article = act.of_kind("article")[0]
    assert (article.heading, article.title) == ("Article 6", "Lawfulness of processing")
    assert article.body.splitlines() == [
        "1. Processing shall be lawful only if:",
        "(a) the data subject has given consent;",
        "(b) processing is necessary;",
        "2. Member States may maintain more specific provisions.",
    ]
    assert article.paragraphs == [{"number": "1", "points": ["a", "b"]}, {"number": "2", "points": []}]
    # The footnote call is dropped, the recital label kept in front of its text.
    assert act.of_kind("recital")[0].body == "(1) Any processing of personal data should be lawful and fair."
    annex = act.of_kind("annex")[0]
    assert (annex.heading, annex.title, annex.body) == ("ANNEX III", "High-risk AI systems", "1. Biometrics")


def test_consolidated_units_carry_their_amendment_markers():
    markup = consolidated_act(
        [
            ("4", "Article 4", "AI literacy", consolidated_paragraph("1", "Providers shall take measures."), None),
            (
                "4a",
                "Article 4a",
                "Processing of special categories",
                consolidated_paragraph("1", "Providers may exceptionally process:")
                + consolidated_point("(a)", "only where strictly necessary;"),
                "32026R1744: INSERTED",
            ),
        ]
    )
    act = parse_act(markup)
    units = {unit.number: unit for unit in act.of_kind("article")}
    assert units["4"].markers == {}
    assert units["4a"].markers == {"32026R1744": ["inserted"]}
    assert units["4a"].body == "1. Providers may exceptionally process:\n(a) only where strictly necessary;"


def test_portuguese_ordinals_and_consolidated_footnotes():
    markup = consolidated_act(
        [
            (
                "9",
                'Artigo 9.<span class="superscript">o</span>',
                "Tratamento",
                consolidated_paragraph(
                    "1",
                    'Nos termos do artigo 6.<span class="superscript">o</span>, n.<span class="superscript">o</span> 1 '
                    '(<a href="#E0001"><span class="superscript">1</span></a>).',
                ),
                None,
            )
        ]
    )
    article = parse_act(markup).of_kind("article")[0]
    assert article.heading == "Artigo 9.º"
    assert article.body == "1. Nos termos do artigo 6.º, n.º 1."


def test_quoted_provisions_of_an_amending_act_are_not_units():
    body = (
        '<p class="oj-normal">Article 4 is replaced by the following:</p>'
        '<div class="eli-subdivision" id="art_4"><p class="oj-ti-art">Article 4</p></div>'
    )
    act = parse_act(
        oj_act(
            title="REGULATION (EU) 2026/1744",
            date="20.7.2026",
            citations=[],
            recitals=[],
            articles=[("1", "Article 1", "Amendments", body)],
        )
    )
    assert [(unit.kind, unit.number) for unit in act.units] == [("article", "1")]


def test_paragraph_structure_skips_roman_sub_points():
    lines = ["1. Text", "(a) one", "(i) sub", "(ii) sub", "(b) two", "(h) eight", "(i) nine"]
    assert paragraph_structure(lines) == [{"number": "1", "points": ["a", "b", "h", "i"]}]
