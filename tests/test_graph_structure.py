"""Structured graph payload (nodes and relationships) built from rows."""

from __future__ import annotations

from raglab.graph.evaluation import article_coverage, draw_sample, precision_report
from raglab.graph.structure import ChunkRow, DocumentRow, build_payload, resolve_profile

LAW_A = """LEI Nº 9.307, DE 23 DE SETEMBRO DE 1996.
Capítulo I
Disposições Gerais
Art. 1º As partes poderão valer-se da arbitragem.
Art. 2º A arbitragem observará o art. 1º desta Lei e o art. 10 da Lei nº 7.998, de 1990.
Art. 3º Aplica-se o art. 4º da Lei nº 7.998, de 11 de janeiro de 1990, e o art. 99 da Lei nº 7.998, de 1990.
Art. 4º O disposto no art. 2º da Lei nº 8.078, de 1990, não se aplica. (Redação dada pela Lei nº 13.129, de 2015)
"""

LAW_B = """LEI Nº 7.998, DE 11 DE JANEIRO DE 1990.
Art. 1º Esta Lei regula o Programa do Seguro-Desemprego.
Art. 4º O benefício será concedido por um período máximo de quatro meses.
Art. 10. É instituído o Fundo de Amparo ao Trabalhador (FAT). (Incluído pela Lei nº 9.307, de 1996)
"""


def _documents() -> list[DocumentRow]:
    return [
        DocumentRow("doc-a", "lei_9307_1996.txt", LAW_A, {"number": "9307", "year": 1996, "title": "Lei nº 9.307"}),
        DocumentRow("doc-b", "lei_7998_1990.txt", LAW_B, {"number": "7998", "year": 1990, "title": "Lei nº 7.998"}),
    ]


def _chunks(document: DocumentRow, size: int = 120) -> list[ChunkRow]:
    text = document.content
    return [
        ChunkRow(f"{document.id}-c{order}", document.id, order, start, min(len(text), start + size))
        for order, start in enumerate(range(0, len(text), size))
    ]


def _payload():
    documents = _documents()
    chunks = [chunk for document in documents for chunk in _chunks(document)]
    return build_payload(index_run_id="run", corpus="laws", documents=documents, chunks=chunks), documents


def test_profile_detection():
    documents = _documents()
    assert resolve_profile("auto", documents) == "laws"
    assert resolve_profile("auto", [DocumentRow("d", "x.md", "# Titre\n\nTexte.", {})]) == "generic"
    assert resolve_profile("generic", documents) == "generic"


def test_common_base_and_law_nodes():
    payload, _ = _payload()
    assert payload.profile == "laws"
    documents = {row["uid"]: row for row in payload.nodes["Document"]}
    assert documents["run:doc-a"]["is_law"] and documents["run:doc-a"]["key"] == "9307"
    assert {row["number"] for row in payload.nodes["Article"] if row["document_id"] == "doc-b"} == {"1", "4", "10"}
    next_edges = payload.relationships[("NEXT", "Chunk", "Chunk")]
    assert {"source": "doc-a-c0", "target": "doc-a-c1", "props": {}} in next_edges
    sections = payload.relationships[("PART_OF", "Section", "Document")]
    assert sections == [{"source": "run:doc-a:sec:1", "target": "run:doc-a", "props": {}}]
    # Every chunk hangs on a section or on its document.
    attached = {
        row["source"]
        for key, rows in payload.relationships.items()
        if key[0] == "PART_OF" and key[1] == "Chunk" and key[2] != "Article"
        for row in rows
    }
    assert attached == {row["uid"] for row in payload.nodes["Chunk"]}


def test_chunks_are_part_of_the_articles_they_overlap():
    payload, documents = _payload()
    article = next(row for row in payload.nodes["Article"] if row["uid"] == "run:doc-a:art:2")
    edges = [row for row in payload.relationships[("PART_OF", "Chunk", "Article")] if row["target"] == article["uid"]]
    assert edges and any(edge["props"]["first"] for edge in edges)
    for edge in edges:
        chunk = next(row for row in payload.nodes["Chunk"] if row["uid"] == edge["source"])
        assert chunk["char_start"] < article["char_end"] and article["char_start"] < chunk["char_end"]


def test_cites_same_law_cross_law_and_outside_the_corpus():
    payload, _ = _payload()
    cites = {
        (row["source"], row["target"]): row["props"] for row in payload.relationships[("CITES", "Article", "Article")]
    }
    assert cites[("run:doc-a:art:2", "run:doc-a:art:1")]["scope"] == "same_law"
    assert cites[("run:doc-a:art:2", "run:doc-b:art:10")]["scope"] == "cross_law"
    assert cites[("run:doc-a:art:3", "run:doc-b:art:4")]["scope"] == "cross_law"
    # Lei nº 8.078 is not in the corpus: an external stub, with the article number.
    external = payload.relationships[("CITES", "Article", "Law")]
    assert external == [
        {
            "source": "run:doc-a:art:4",
            "target": "run:law:8078",
            "props": external[0]["props"],
        }
    ]
    assert external[0]["props"]["articles"] == ["2"]
    assert {row["uid"]: row["external"] for row in payload.nodes["Law"]}["run:law:8078"] is True
    # art. 99 does not exist in Lei nº 7.998: the edge points to the law.
    missing = payload.relationships[("CITES", "Article", "Document")]
    assert [(row["source"], row["target"], row["props"]["articles"]) for row in missing] == [
        ("run:doc-a:art:3", "run:doc-b", ["99"])
    ]


def test_amendments_point_from_the_amending_law():
    payload, _ = _payload()
    by_external = payload.relationships[("AMENDS", "Law", "Article")]
    assert [(row["source"], row["target"], row["props"]["kind"]) for row in by_external] == [
        ("run:law:13129", "run:doc-a:art:4", "rewritten")
    ]
    by_corpus = payload.relationships[("AMENDS", "Document", "Article")]
    assert [(row["source"], row["target"], row["props"]["kind"]) for row in by_corpus] == [
        ("run:doc-a", "run:doc-b:art:10", "inserted")
    ]


def test_generic_profile_reads_markdown_sections():
    document = DocumentRow("doc", "guide.md", "# Guide\n\n## Installer\n\nTexte.\n\n## Lancer\n\nTexte.\n", {})
    chunks = [ChunkRow("c0", "doc", 0, 0, 20), ChunkRow("c1", "doc", 1, 20, len(document.content))]
    payload = build_payload(index_run_id="run", corpus="docs", documents=[document], chunks=chunks)
    assert payload.profile == "generic"
    assert [row["label"] for row in payload.nodes["Section"]] == ["Guide", "Installer", "Lancer"]
    assert "Article" not in payload.nodes
    assert payload.relationships[("PART_OF", "Section", "Section")]


def test_sample_is_seeded_and_report_counts_verdicts():
    payload, documents = _payload()
    first = draw_sample(payload, documents, seed=3, cites=2, amendments=1)
    again = draw_sample(payload, documents, seed=3, cites=2, amendments=1)
    assert first == again
    assert [item["group"] for item in first["items"]] == ["CITES", "CITES", "AMENDS_REVOKES"]
    first["items"][0]["verdict"] = "correct"
    first["items"][1]["verdict"] = "incorrect"
    report = precision_report(first)
    assert report["groups"]["CITES"]["precision"] == 0.5
    assert report["groups"]["AMENDS_REVOKES"]["reviewed"] == 0


def test_article_coverage_checks_the_answer_span():
    payload, documents = _payload()
    start = LAW_B.index("É instituído")
    cases = [
        {
            "id": "q1",
            "question": "O que dispõe o art. 10 da Lei nº 7.998?",
            "expected_spans": [{"file_name": "lei_7998_1990.txt", "start": start, "end": start + 20}],
        },
        {
            "id": "q2",
            "question": "O que dispõe o art. 4 da Lei nº 7.998?",
            "expected_spans": [{"file_name": "lei_7998_1990.txt", "start": start, "end": start + 20}],
        },
        {"id": "q3", "question": "Quem paga o seguro?"},
    ]
    coverage = article_coverage(payload, cases, documents)
    assert {key: coverage[key] for key in ("cite_article", "article_node", "span_in_article")} == {
        "cite_article": 2,
        "article_node": 2,
        "span_in_article": 1,
    }
    assert coverage["misses"] == [{"id": "q2", "reason": "answer_outside_article", "question": cases[1]["question"]}]
