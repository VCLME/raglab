from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from raglab.benchmarks.lexml_questions import (
    LexMLQuestionGenerator,
    lexical_overlap,
    sample_passages,
)

LAW = "\n".join(
    [
        "LEI Nº 8.078, DE 11 DE SETEMBRO DE 1990.",
        "Dispõe sobre a proteção do consumidor.",
        "TÍTULO I",
        "Art. 48. As declarações de vontade constantes de escritos particulares vinculam o fornecedor.",
        "Art. 49. O consumidor pode desistir do contrato, no prazo de 7 dias a contar de sua assinatura.",
        "Parágrafo único. Os valores pagos serão devolvidos de imediato, monetariamente atualizados.",
        "Art. 50. A garantia contratual é complementar à legal e será conferida mediante termo escrito.",
        "Art. 51. São nulas de pleno direito as cláusulas que impossibilitem a indenização pelo FGTS.",
    ]
)


def _corpus(tmp_path: Path, laws: int = 3) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for index in range(laws):
        stem = f"lei_{8000 + index}_1990"
        (corpus / f"{stem}.txt").write_text(LAW, encoding="utf-8")
        (corpus / f"{stem}.json").write_text(
            json.dumps(
                {
                    "urn": f"urn:lex:br:federal:lei:1990-01-01;{8000 + index}",
                    "title": f"Lei nº {8000 + index}",
                    "ementa": "Dispõe sobre a proteção do consumidor.",
                }
            ),
            encoding="utf-8",
        )
    return corpus


def test_passages_come_from_the_body_with_their_article(tmp_path: Path):
    corpus = _corpus(tmp_path)
    passages = sample_passages(corpus, count=3, seed=1, target_chars=150)
    assert len(passages) == 3
    assert len({passage.file_name for passage in passages}) == 3  # one per law first
    for passage in passages:
        text = (corpus / passage.file_name).read_text(encoding="utf-8")
        assert text[passage.start : passage.end] == passage.text
        assert passage.start >= text.index("Art. 48")  # heading lines skipped
        assert passage.article in {"48", "49", "50", "51"}


def test_passage_sampling_is_deterministic(tmp_path: Path):
    corpus = _corpus(tmp_path)
    first = sample_passages(corpus, count=4, seed=3)
    again = sample_passages(corpus, count=4, seed=3)
    assert [(p.file_name, p.start) for p in first] == [(p.file_name, p.start) for p in again]


def test_lexical_overlap():
    assert lexical_overlap("consumidor desistir contrato", "O consumidor pode desistir do contrato") == 1.0
    assert lexical_overlap("Quem paga pela garantia?", "O consumidor pode desistir") == 0.0


def _generator(answers: list[str]) -> LexMLQuestionGenerator:
    ollama = MagicMock()
    ollama.chat.side_effect = [{"answer": answer} for answer in answers]
    return LexMLQuestionGenerator(settings=MagicMock(generation_model="qwen2.5:7b"), ollama=ollama)


def test_generate_keeps_only_questions_whose_quote_is_in_the_passage(tmp_path: Path):
    corpus = _corpus(tmp_path, laws=3)
    answers = [
        "Voilà: " + json.dumps({"question": "Em quanto tempo o comprador pode voltar atrás?", "answer": "7 dias"}),
        json.dumps({"question": "Pergunta inventada?", "answer": "texto que não existe no trecho"}),
        "não é JSON",
    ] + [json.dumps({"question": "Q?", "answer": "inexistente"})] * 20
    generator = _generator(answers)
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=3, seed=0)

    assert result["rejected"]["invalid_json"] >= 1
    assert result["rejected"]["quote_not_found"] >= 1
    cases = [json.loads(line) for line in Path(result["ground_truth_path"]).read_text(encoding="utf-8").splitlines()]
    assert [case["ground_truth_answer"] for case in cases] == ["7 dias"]
    for case in cases:
        (span,) = case["expected_spans"]
        text = (corpus / span["file_name"]).read_text(encoding="utf-8")
        assert text[span["start"] : span["end"]] == span["text"]
        assert case["question_type"] in {"paraphrase", "reference", "entity"}
        assert case["review_status"] == "generated"
        assert 0.0 <= case["lexical_overlap"] <= 1.0


def test_paraphrase_questions_citing_articles_are_rejected(tmp_path: Path):
    corpus = _corpus(tmp_path, laws=1)
    generator = _generator(
        [json.dumps({"question": "O que diz o art. 49 sobre desistência?", "answer": "7 dias"})] * 30
    )
    # Force every passage to the paraphrase type.
    import raglab.benchmarks.lexml_questions as module

    original = module.pick_question_type
    module.pick_question_type = lambda passage, wanted: "paraphrase"
    try:
        result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=2, seed=0)
    finally:
        module.pick_question_type = original
    assert result["case_count"] == 0
    assert result["rejected"]["leaks_reference"] > 0


def test_numeric_tables_are_not_sampled(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    table = "\n".join(["LEI Nº 1", "Abre crédito", "ANEXO"] + ["10.000 20.000 30.000 40.000 50.000 60.000"] * 40)
    (corpus / "lei_1_2000.txt").write_text(table, encoding="utf-8")
    (corpus / "lei_1_2000.json").write_text("{}", encoding="utf-8")
    assert sample_passages(corpus, count=3, seed=0) == []


def test_types_are_balanced_and_prompt_carries_the_law_subject(tmp_path: Path):
    corpus = _corpus(tmp_path, laws=6)
    ollama = MagicMock()
    ollama.chat.return_value = {
        "answer": json.dumps({"question": "Na lei do consumidor, qual o prazo para desistir?", "answer": "7 dias"})
    }

    def reply(**kwargs):
        content = kwargs["messages"][0]["content"]
        if "TIPO: reference" in content:
            reference = content.split("REFERÊNCIA: ")[1].split("\n")[0]  # "art. 49 da Lei nº 8003"
            article, law = reference.split(" da ")
            question = f"O que diz o {article} da {law.replace('.', '')}?"
            return {"answer": json.dumps({"question": question, "answer": "7 dias"})}
        return ollama.chat.return_value

    ollama.chat.side_effect = reply
    generator = LexMLQuestionGenerator(settings=MagicMock(generation_model="m"), ollama=ollama)
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=6, seed=0)

    assert result["by_type"] == {"paraphrase": 2, "reference": 2, "entity": 2}
    prompt = ollama.chat.call_args_list[0].kwargs["messages"][0]["content"]
    assert prompt.startswith("ASSUNTO DA LEI: Dispõe sobre a proteção do consumidor.")


def test_reference_questions_must_cite_article_and_law(tmp_path: Path):
    from raglab.benchmarks.lexml_questions import Passage, _cites_reference

    passage = Passage("lei_8078_1990.txt", "", "Lei nº 8.078", "", 0, 10, "...", "49")
    assert _cites_reference("O que dispõe o art. 49 da Lei nº 8.078?", passage)
    assert _cites_reference("Segundo o artigo 49 da Lei 8078/1990, qual o prazo?", passage)
    assert not _cites_reference("O que dispõe a Lei nº 8.078 sobre o prazo?", passage)
    assert not _cites_reference("O que dispõe o art. 49 sobre o prazo?", passage)


def test_budget_laws_are_not_sampled(tmp_path: Path):
    corpus = _corpus(tmp_path, laws=1)
    sidecar = next(corpus.glob("*.json"))
    sidecar.write_text(
        json.dumps({"ementa": "Abre ao Orçamento Fiscal da União crédito suplementar"}), encoding="utf-8"
    )
    assert sample_passages(corpus, count=2, seed=0) == []


def test_vague_questions_are_rejected():
    from raglab.benchmarks.lexml_questions import _VAGUE_RE

    assert _VAGUE_RE.search("Qual lei é alterada por esta Lei?")
    assert _VAGUE_RE.search("Qual programa é mencionado neste trecho?")
    assert _VAGUE_RE.search("O que prevê o texto deste artigo?")
    assert not _VAGUE_RE.search("Na lei que trata do FGTS, qual o prazo de recolhimento?")


def test_boilerplate_and_filler_answers_are_rejected():
    from raglab.benchmarks.lexml_questions import Passage, _rejection_reason

    text = "Art. 5o ..................................................\nA PRESIDENTA DA REPÚBLICA sanciona."
    passage = Passage("lei_1_2000.txt", "", "Lei nº 1", "", 0, len(text), text, "5")
    dots = {"question": "Na lei X, o que diz o item?", "answer": "........................................"}
    formula = {"question": "Na lei X, quem sanciona?", "answer": "A PRESIDENTA DA REPÚBLICA"}
    assert _rejection_reason(dots, passage, "paraphrase") == "boilerplate_answer"
    assert _rejection_reason(formula, passage, "entity") == "boilerplate_answer"


def test_passages_start_after_the_enacting_formula(tmp_path: Path):
    corpus = _corpus(tmp_path)
    for passage in sample_passages(corpus, count=6, seed=5, target_chars=120):
        assert "Dispõe sobre" not in passage.text


def test_review_marks_contentless_and_vague_cases_without_dropping_them(tmp_path: Path):
    from raglab.benchmarks.lexml_questions import review_question_set

    rows = [
        {"id": "a", "question": "Na lei do FGTS, qual o prazo?", "ground_truth_answer": "até o dia sete de cada mês"},
        {"id": "b", "question": "O que dispõe o art. 10 da Lei nº 9.262?", "ground_truth_answer": "(VETADO)"},
        {
            "id": "c",
            "question": "Quando entra em vigor a lei X?",
            "ground_truth_answer": "Esta Lei entra em vigor na data de sua publicação",
        },
        {
            "id": "d",
            "question": "Qual o percentual conforme o subtítulo mencionado?",
            "ground_truth_answer": "quarenta por cento da soma",
        },
    ]
    path = tmp_path / "ground_truth.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    counts = review_question_set(path)

    cases = {case["id"]: case for case in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    assert len(cases) == 4
    assert "review_status" not in cases["a"]
    assert cases["b"]["rejection_reason"] == "boilerplate_answer"
    assert cases["c"]["rejection_reason"] == "boilerplate_answer"
    assert cases["d"]["rejection_reason"] == "vague"
    assert counts == {"boilerplate_answer": 2, "vague": 1}
