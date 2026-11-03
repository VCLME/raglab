"""Rules of the laws profile, on snippets taken from the LexML corpus."""

from __future__ import annotations

from raglab.graph.legal import (
    LawMention,
    canonical_article,
    looks_like_law,
    parse_articles,
    parse_law,
    parse_sections,
    quoted_spans,
)

# Lei nº 9.307/1996 (arbitragem), abridged.
ARBITRAGEM = """LEI Nº 9.307, DE 23 DE SETEMBRO DE 1996.
Dispõe sobre a arbitragem.
Capítulo I
Disposições Gerais
Art. 1º As pessoas capazes de contratar poderão valer-se da arbitragem.
§ 1o A administração pública direta e indireta poderá utilizar-se da arbitragem. (Incluído pela Lei nº 13.129, de 2015) (Vigência)
Art. 2º A arbitragem poderá ser de direito ou de eqüidade, a critério das partes.
Capítulo II
Da Convenção de Arbitragem e seus Efeitos
Seção I
Da cláusula
Art. 6º Não havendo acordo prévio sobre a forma de instituir a arbitragem, a parte interessada manifestará à outra parte sua intenção.
Parágrafo único. Não comparecendo a parte convocada, poderá a outra parte propor a demanda de que trata o art. 7º desta Lei.
Art. 7º Existindo cláusula compromissória e havendo resistência, poderá a parte requerer a citação nos termos do artigo anterior.
Art. 7º-A. O árbitro observará o disposto nos arts. 1º e 2º. (Incluído pela Lei nº 13.129, de 2015)
Art. 8º A cláusula compromissória é autônoma, observado o art. 175 da Constituição Federal e o art. 10 da Lei nº 7.998, de 11 de janeiro de 1990.
Art. 9º (Revogado pela Lei nº 13.129, de 2015)
Art. 10. Aplicam-se os arts. 1º a 3º desta Lei. (Redação dada pela Medida Provisória nº 2.158-35, de 2001)
Brasília, 23 de setembro de 1996; 175º da Independência e 108º da República.
"""

# Lei nº 14.026/2020: an amending law quoting the amended law's articles.
SANEAMENTO = """LEI Nº 14.026, DE 15 DE JULHO DE 2020
Art. 1º Esta Lei atualiza o marco legal do saneamento básico e altera a Lei nº 9.984, de 17 de julho de 2000, e a Lei nº 10.768, de 19 de novembro de 2003.
Art. 2º A Lei nº 9.984, de 17 de julho de 2000 , passa a vigorar com as seguintes alterações:
“Art. 1º Esta Lei cria a Agência Nacional de Águas e Saneamento Básico (ANA).” (NR)
“Art. 4º ...............................................................................................................
§ 2º (Revogado).
§ 9º As regras a que se refere o inciso XXIV do caput deste artigo serão aplicadas nos termos do art. 3º.” (NR)
Art. 3º A Lei nº 9.984, de 17 de julho de 2000, passa a vigorar acrescida do seguinte art. 4º-A:
“ Art. 4º-A . A ANA instituirá normas de referência.” (NR)
Art. 4º O art. 39 da Lei nº 8.078, de 11 de setembro de 1990, passa a vigorar com a seguinte redação:
“Art. 39. ..........” (NR)
Art. 5º Ficam revogados:
I - a Lei nº 10.000, de 1º de janeiro de 2000;
II - os arts. 3º e 4º da Lei nº 11.445, de 5 de janeiro de 2007;
III - da Medida Provisória nº 2.158-35, de 24 de agosto de 2001:
a) os §§ 2º, 3º e 4º do art. 50;
IV - o art. 33 da Lei nº 6.385, de 1976, com a redação dada pela Lei nº 9.457, de 1997.
Art. 6º Esta Lei entra em vigor na data de sua publicação, observado o disposto no art. 2º.
"""


def test_article_numbers_are_canonical():
    assert canonical_article("1.228") == "1228"
    assert canonical_article("4", "a") == "4-A"
    assert canonical_article("07") == "7"


def test_articles_and_their_spans():
    articles, stats = parse_articles(ARBITRAGEM)
    assert [article.number for article in articles] == ["1", "2", "6", "7", "7-A", "8", "9", "10"]
    assert stats["article_starts"] == 8
    seventh = articles[3]
    assert ARBITRAGEM[seventh.start :].startswith("Art. 7º Existindo")
    assert ARBITRAGEM[seventh.end :].startswith("Art. 7º-A.")
    # The last article stops before the signature.
    assert "Brasília" not in ARBITRAGEM[articles[-1].start : articles[-1].end]
    assert articles[6].revoked is True


def test_hyphen_followed_by_a_word_is_not_a_lettered_article():
    text = "Art. 1º - O contribuinte poderá abater da renda bruta.\nArt. 2º - Os valores serão corrigidos.\n"
    assert [article.number for article in parse_articles(text)[0]] == ["1", "2"]


def test_quoted_articles_of_the_amended_law_are_not_this_laws_articles():
    articles, stats = parse_articles(SANEAMENTO)
    assert [article.number for article in articles] == ["1", "2", "3", "4", "5", "6"]
    assert stats["article_starts_quoted"] == 0  # the quoted ones open with a quotation mark


def test_unclosed_straight_quote_runs_until_this_laws_next_article():
    # Lei nº 8.420/1992: the quote around the amended articles is never closed.
    text = (
        "Art. 1° A Lei n° 4.886, de 9 de dezembro de 1965, passa a vigorar com as seguintes alterações:\n"
        '"Art. 24. As diretorias dos Conselhos Regionais prestarão contas.\n'
        "Art. 25.Os Conselhos Regionais prestarão contas ao Conselho Federal.\n"
        "Art. 27. Do contrato de representação comercial constarão:\n"
        "Art. 2° Esta lei entra em vigor na data de sua publicação.\n"
    )
    articles, stats = parse_articles(text)
    assert [article.number for article in articles] == ["1", "2"]
    assert stats["article_starts_quoted"] == 2
    assert len(quoted_spans(text)) == 1


def test_out_of_sequence_headings_are_dropped():
    text = "Art. 1º Primeiro.\nArt. 2º Segundo.\nArt. 1o .......................\nArt. 3º Terceiro.\n"
    articles, stats = parse_articles(text)
    assert [article.number for article in articles] == ["1", "2", "3"]


def test_sections_nest_and_carry_their_titles():
    sections = parse_sections(ARBITRAGEM)
    assert [(section.label, section.title) for section in sections] == [
        ("Capítulo I", "Disposições Gerais"),
        ("Capítulo II", "Da Convenção de Arbitragem e seus Efeitos"),
        ("Seção I", "Da cláusula"),
    ]
    assert sections[2].parent == "Capítulo II"
    assert sections[0].end == sections[1].start


def test_citations_within_the_law():
    structure = parse_law(ARBITRAGEM)
    pairs = {(c.source, c.target_article, c.law) for c in structure.citations}
    assert ("6", "7", None) in pairs  # "o art. 7º desta Lei"
    assert ("7", "6", None) in pairs  # "nos termos do artigo anterior"
    assert ("7-A", "1", None) in pairs and ("7-A", "2", None) in pairs  # "arts. 1º e 2º"
    assert {("10", "1", None), ("10", "2", None)} <= pairs  # "arts. 1º a 3º": 3 is not an article here
    relative = [c for c in structure.citations if c.relative]
    assert [(c.source, c.target_article) for c in relative] == [("7", "6")]


def test_citations_to_other_texts():
    structure = parse_law(ARBITRAGEM)
    from_eight = [c for c in structure.citations if c.source == "8"]
    # The Constitution has no article node; the other law is kept with its number.
    assert [(c.target_article, c.law) for c in from_eight] == [("10", LawMention("7998", 1990))]


def test_designation_before_the_article_number():
    text = (
        "Art. 1º A alíquota (Decreto-Lei nº 1.940, de 25 de maio de 1982, art. 1º, § 1º; "
        "Lei nº 7.738, de 9 de março de 1989, art. 28) é fixada em 1%.\n"
        "Art. 2º Revogam-se as disposições em contrário.\n"
    )
    structure = parse_law(text)
    assert [(c.target_article, c.law) for c in structure.citations] == [("28", LawMention("7738", 1989))]


def test_qualifier_after_connectors_and_inheritance():
    text = (
        "Art. 1º Aplica-se o disposto no art. 5º e no § 2º do art. 7º da Lei nº 8.666, de 21 de junho de 1993.\n"
        "Art. 2º Observado o art. 1º, inciso II, desta Lei.\n"
    )
    structure = parse_law(text)
    targets = {(c.source, c.target_article, c.law.number if c.law else None) for c in structure.citations}
    assert targets == {("1", "5", "8666"), ("1", "7", "8666"), ("2", "1", None)}


def test_amending_provisions_are_read_for_the_amended_law():
    structure = parse_law(SANEAMENTO)
    own = {(c.source, c.target_article) for c in structure.citations if c.law is None}
    # Article numbers inside quotes, list items under "da Medida Provisória
    # ...:" and "acrescida do seguinte art. 4º-A" do not belong to this law.
    assert own == {("6", "2")}
    amended = [c for c in structure.citations if c.law is not None and c.law.number == "9984"]
    assert [(c.source, c.target_article) for c in amended] == [("3", "4-A")]


def test_markers_of_the_compiled_text():
    structure = parse_law(ARBITRAGEM)
    markers = [(a.kind, a.target_article, a.scope, a.by.number) for a in structure.amendments if a.by is not None]
    assert ("inserted", "1", "paragraph", "13129") in markers
    assert ("inserted", "7-A", "article", "13129") in markers
    assert ("revoked", "9", "article", "13129") in markers
    # A provisional measure is not a law node.
    assert not [a for a in structure.amendments if a.target_article == "10"]


def test_amending_and_revoking_provisions():
    structure = parse_law(SANEAMENTO)
    own = {
        (a.relation, a.target_law.number, a.target_article, a.via_article)
        for a in structure.amendments
        if a.by is None and a.target_law is not None
    }
    assert ("AMENDS", "9984", None, "1") in own  # "altera a Lei nº 9.984"
    assert ("AMENDS", "10768", None, "1") in own
    assert ("AMENDS", "9984", None, "2") in own  # "A Lei nº 9.984 ... passa a vigorar"
    assert ("AMENDS", "8078", "39", "4") in own  # "O art. 39 da Lei nº 8.078 passa a vigorar"
    assert ("REVOKES", "10000", None, "5") in own
    assert ("REVOKES", "11445", "3", "5") in own and ("REVOKES", "11445", "4", "5") in own
    assert ("REVOKES", "6385", "33", "5") in own
    # "com a redação dada pela Lei nº 9.457": not revoked.
    assert not [a for a in structure.amendments if a.target_law and a.target_law.number == "9457"]
    # The amending article's own heading is not an article of the amended law.
    assert not [a for a in structure.amendments if a.target_article == "2" and a.via_article == "2"]


def test_markers_inside_quotes_belong_to_the_amended_law():
    structure = parse_law(SANEAMENTO)
    assert not [a for a in structure.amendments if a.kind == "revoked"]


def test_looks_like_law():
    assert looks_like_law(ARBITRAGEM)
    assert not looks_like_law("# Guide\n\nUn texte sans articles.\n")
