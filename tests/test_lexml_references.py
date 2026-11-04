"""References question set (9.9b): pairs from the graph rules, checks on the
generated questions (scenarios that name no law and copy no wording), the mix
of question types, seeded dev / held-out split. No LLM: a fake client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from raglab.benchmarks.compare import compare_runs, render
from raglab.benchmarks.lexml_references import (
    PERSONAS,
    LexMLReferenceQuestionGenerator,
    assign_splits,
    copied_run,
    load_corpus,
    names_law,
    next_type,
    parse_mix,
    reference_pairs,
    rejection_reason,
    type_quotas,
)
from raglab.config import Settings

MIX = {"via_topic": 0.5, "scenario": 0.3, "via_article": 0.2}

LAW = """LEI Nº 9.307, DE 23 DE SETEMBRO DE 1996.
Dispõe sobre a arbitragem.
Art. 1º As pessoas capazes de contratar poderão valer-se da arbitragem, observadas as penalidades previstas no art. 3º desta Lei.
Art. 2º A arbitragem poderá ser de direito ou de equidade, a critério das partes, nos termos do art. 1º.
Art. 3º O descumprimento sujeita o infrator a multa de dez mil reais, aplicada em dobro na reincidência, sem prejuízo das demais sanções cabíveis.
Art. 4º Esta Lei entra em vigor na data de sua publicação, observado o art. 3º.
"""


class FakeChat:
    def __init__(self, answers: list[dict]):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def chat(self, *, messages, **_):
        self.prompts.append(messages[0]["content"])
        return {"answer": json.dumps(self.answers.pop(0))}


def _corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "lei_9307_1996.txt").write_text(LAW, encoding="utf-8")
    sidecar = {
        "number": "9307",
        "year": 1996,
        "title": "Lei nº 9.307",
        "ementa": "Dispõe sobre a arbitragem.",
        "urn": "urn:x",
    }
    (corpus / "lei_9307_1996.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return corpus


def test_pairs_come_from_the_graph_rules(tmp_path):
    documents, texts = load_corpus(_corpus(tmp_path))
    pairs = reference_pairs(documents)
    assert {(pair.source_article, pair.target_article) for pair in pairs} == {("1", "3"), ("2", "1"), ("4", "3")}
    pair = next(p for p in pairs if p.source_article == "1")
    assert texts[pair.target_file][pair.target_start :].startswith("Art. 3º O descumprimento")


def test_checks_on_generated_questions(tmp_path):
    documents, texts = load_corpus(_corpus(tmp_path))
    pair = next(p for p in reference_pairs(documents) if p.source_article == "1")
    ok = {
        "question": "Qual multa se aplica a quem descumpre o art. 1º da Lei nº 9.307?",
        "answer": "multa de dez mil reais",
    }
    assert rejection_reason(ok, pair, "via_article", texts) is None
    leaks = {"question": "O que diz o art. 3º da Lei nº 9.307 sobre multas?", "answer": "multa de dez mil reais"}
    assert rejection_reason(leaks, pair, "via_article", texts) == "leaks_target"
    no_ref = {"question": "Qual multa se aplica na lei de arbitragem?", "answer": "multa de dez mil reais"}
    assert rejection_reason(no_ref, pair, "via_article", texts) == "reference_missing"
    assert rejection_reason(no_ref, pair, "via_topic", texts) is None
    assert rejection_reason(ok, pair, "via_topic", texts) == "leaks_reference"
    not_in_target = {
        "question": "Quem pode usar a arbitragem na lei de arbitragem?",
        "answer": "As pessoas capazes de contratar",
    }
    assert rejection_reason(not_in_target, pair, "via_topic", texts) == "quote_not_found"
    assert rejection_reason(None, pair, "via_topic", texts) == "invalid_json"


def test_a_scenario_names_no_law_and_copies_no_wording(tmp_path):
    documents, texts = load_corpus(_corpus(tmp_path))
    pair = next(p for p in reference_pairs(documents) if p.source_article == "1")
    answer = "multa de dez mil reais"
    situation = "Fechei um acordo para resolver uma briga fora da Justiça e não cumpri o combinado. O que posso pagar?"
    assert rejection_reason({"question": situation, "answer": answer}, pair, "scenario", texts) is None
    # Generic "a lei" is fine; naming the law, the article or its number is not.
    generic = "Segundo a lei, o que pago se não cumprir o que combinei numa arbitragem?"
    assert rejection_reason({"question": generic, "answer": answer}, pair, "scenario", texts) is None
    for named in (
        "Pela Lei de Arbitragem, o que pago se não cumprir o combinado?",
        "Não cumpri o que prevê o art. 1º sobre arbitragem. O que pago?",
        "Minha empresa usou a lei 9307 e não cumpriu o acordo. O que paga?",
        "Meu cliente descumpriu um acordo; o parágrafo único prevê o quê?",
        "Pelo CDC, o que pago se não cumprir o combinado?",
        "A Constituição me protege se eu não cumprir o combinado?",
        "Um decreto muda o que pago se não cumprir o combinado?",
    ):
        assert rejection_reason({"question": named, "answer": answer}, pair, "scenario", texts) == "names_law", named
    # Everyday words that share a stem with a law's name are fine.
    for everyday in (
        "O juiz decretou a falência da minha empresa e não cumprimos o combinado. O que pagamos?",
        "Na constituição da empresa combinamos resolver brigas fora da Justiça. O que pago se não cumprir?",
        "O estatuto social prevê arbitragem e não cumpri o combinado. O que pago?",
        "Vendi com código de barras errado e não cumpri o combinado. O que pago?",
    ):
        assert not names_law(everyday, pair), everyday
    # Five words in a row from the cited (or the citing) article: a Ctrl+F finds it.
    copied = "Numa arbitragem, o descumprimento sujeita o infrator a qual punição?"
    for question_type in ("scenario", "via_topic"):
        assert rejection_reason({"question": copied, "answer": answer}, pair, question_type, texts) == "copies_wording"
    assert copied_run(copied, LAW) == "o descumprimento sujeita o infrator a"
    # The identifiers minority may quote the law it cites.
    cites = {"question": "Qual multa se aplica a quem descumpre o art. 1º da Lei nº 9.307?", "answer": answer}
    assert rejection_reason(cites, pair, "via_article", texts) is None


def test_the_mix_favours_questions_without_identifiers():
    assert type_quotas(100, MIX) == {"via_topic": 50, "scenario": 30, "via_article": 20}
    assert sum(type_quotas(7, MIX).values()) == 7
    quotas = type_quotas(10, MIX)
    kept = dict.fromkeys(quotas, 0)
    asked = []
    kind = next_type(kept, quotas)
    while kind is not None:
        kept[kind] += 1
        asked.append(kind)
        kind = next_type(kept, quotas)
    assert kept == {"via_topic": 5, "scenario": 3, "via_article": 2}
    assert asked[:3] == ["via_topic", "scenario", "via_article"]
    assert parse_mix("via_topic=0.6, scenario=0.4") == {"via_topic": 0.6, "scenario": 0.4}
    with pytest.raises(ValueError):
        parse_mix("via_topic=0.6,paraphrase=0.4")


def test_generation_writes_spans_on_the_cited_article(tmp_path):
    corpus = _corpus(tmp_path)
    client = FakeChat(
        [
            {
                "question": "Qual multa se aplica a quem descumpre o art. 1º da Lei nº 9.307?",
                "answer": "multa de dez mil reais",
            },
            {"question": "Na lei de arbitragem, quem pode escolher entre direito e equidade?", "answer": "não existe"},
        ]
    )
    generator = LexMLReferenceQuestionGenerator(Settings(), backend="llamacpp", client=client)
    result = generator.generate(
        corpus_dir=corpus, output_dir=tmp_path / "out", count=1, seed=1, shares={"via_article": 1.0}
    )
    assert result["case_count"] == 1 and result["reference_pairs"] == 3
    case = json.loads((tmp_path / "out" / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()[0])
    span = case["expected_spans"][0]
    assert LAW[span["start"] : span["end"]] == "multa de dez mil reais"
    assert case["target_article"] == "Art. 3º — Lei nº 9.307" and case["source_article"] == "Art. 1º — Lei nº 9.307"
    assert "observadas as penalidades previstas no art. 3º" in case["citing_spans"][0]["text"]
    assert case["split"] in {"dev", "heldout"} and case["question_type"] == "via_article"
    # The commencement clause ("Esta Lei entra em vigor ... observado o art.
    # 3º") is never asked about.
    assert all("entra em vigor" not in prompt.split("ARTIGO CITADO")[0] for prompt in client.prompts)


def test_scenarios_take_points_of_view_in_turn(tmp_path):
    corpus = _corpus(tmp_path)
    client = FakeChat(
        [
            # First pair (art. 1 cites art. 3): names the law, rejected.
            {
                "question": "Pela Lei de Arbitragem, que multa pago se não cumprir o acordo?",
                "answer": "multa de dez mil reais",
            },
            # Second pair (art. 2 cites art. 1).
            {
                "question": "Tenho uma pequena loja e quero resolver uma briga com um fornecedor sem ir à Justiça. "
                "Quem pode usar esse caminho?",
                "answer": "As pessoas capazes de contratar",
            },
        ]
    )
    generator = LexMLReferenceQuestionGenerator(Settings(), backend="llamacpp", client=client)
    result = generator.generate(
        corpus_dir=corpus, output_dir=tmp_path / "out", count=1, seed=1, shares={"scenario": 1.0}
    )
    assert result["case_count"] == 1 and result["rejected"] == {"names_law": 1}
    case = json.loads((tmp_path / "out" / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert case["question_type"] == "scenario" and case["target_article"] == "Art. 1º — Lei nº 9.307"
    # Each attempt gets the next point of view, and the prompt says which.
    viewpoints = [
        next(view for view in PERSONAS if f"PONTO DE VISTA: {PERSONAS[view]}" in prompt) for prompt in client.prompts
    ]
    assert len(set(viewpoints)) == 2 and case["persona"] == viewpoints[1]
    metadata = json.loads((tmp_path / "out" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["rejected_by_type"]["scenario"] == {"names_law": 1}
    assert metadata["by_persona"][viewpoints[1]] == 1 and metadata["shares"] == {"scenario": 1.0}


def test_split_is_seeded():
    cases = [{"id": str(index)} for index in range(10)]
    again = [{"id": str(index)} for index in range(10)]
    assign_splits(cases, seed=7)
    assign_splits(again, seed=7)
    assert [case["split"] for case in cases] == [case["split"] for case in again]
    assert sum(case["split"] == "dev" for case in cases) == 3


def test_compare_reports_the_held_out_questions_apart():
    types = ["scenario", "via_topic", "scenario", "via_article"]

    def run(label: str, hits: list[int]) -> dict:
        rows = [
            {
                "id": f"q{i}",
                "type": types[i],
                "split": "dev" if i < 2 else "heldout",
                "recall@5": hit,
                "reciprocal_rank": float(hit),
            }
            for i, hit in enumerate(hits)
        ]
        return {"label": label, "suites": [{"suite": "lexml_references", "cases": rows}]}

    comparison = compare_runs(run("a", [0, 0, 0, 1]), run("b", [1, 0, 1, 1]))
    entry = comparison["suites"]["lexml_references"]
    assert entry["by_split"]["heldout"]["recall@5"]["gained"] == 1
    assert entry["by_split"]["dev"]["recall@5"]["gained"] == 1
    # Per type on the held-out part: the numbers to report.
    assert set(entry["by_type_heldout"]) == {"scenario", "via_article"}
    assert entry["by_type_heldout"]["scenario"]["questions"] == 1
    assert entry["by_type_heldout"]["scenario"]["recall@5"]["gained"] == 1
    assert "lexml_references · heldout · scenario" in render(comparison)
