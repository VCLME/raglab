"""References question set (9.9b): pairs from the graph rules, checks on the
generated questions, seeded dev / held-out split. No LLM: a fake client."""

from __future__ import annotations

import json
from pathlib import Path

from raglab.benchmarks.compare import compare_runs
from raglab.benchmarks.lexml_references import (
    LexMLReferenceQuestionGenerator,
    assign_splits,
    load_corpus,
    reference_pairs,
    rejection_reason,
)
from raglab.config import Settings

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
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=1, seed=1)
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


def test_split_is_seeded():
    cases = [{"id": str(index)} for index in range(10)]
    again = [{"id": str(index)} for index in range(10)]
    assign_splits(cases, seed=7)
    assign_splits(again, seed=7)
    assert [case["split"] for case in cases] == [case["split"] for case in again]
    assert sum(case["split"] == "dev" for case in cases) == 3


def test_compare_reports_the_held_out_questions_apart():
    def run(label: str, hits: list[int]) -> dict:
        rows = [
            {"id": f"q{i}", "split": "dev" if i < 2 else "heldout", "recall@5": hit, "reciprocal_rank": float(hit)}
            for i, hit in enumerate(hits)
        ]
        return {"label": label, "suites": [{"suite": "lexml_references", "cases": rows}]}

    comparison = compare_runs(run("a", [0, 0, 0, 1]), run("b", [1, 0, 1, 1]))
    entry = comparison["suites"]["lexml_references"]
    assert entry["by_split"]["heldout"]["recall@5"]["gained"] == 1
    assert entry["by_split"]["dev"]["recall@5"]["gained"] == 1
