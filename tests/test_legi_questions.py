from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from raglab.benchmarks.base import GroundTruthCase
from raglab.benchmarks.legi_questions import (
    LegiQuestionGenerator,
    _rejection_reason,
    assign_splits,
    review_question_set,
    sample_passages,
    text_rejection_reason,
)

BODY_18 = (
    "Le consommateur dispose d'un délai de quatorze jours pour exercer son droit de rétractation d'un contrat "
    "conclu à distance, sans avoir à motiver sa décision.\n"
    "Le délai court à compter du jour de la conclusion du contrat pour les prestations de services, ou de la "
    "réception du bien par le consommateur pour les contrats de vente de biens."
)
BODY_OLD = (
    "Le consommateur dispose d'un délai de sept jours francs pour exercer son droit de rétractation sans avoir "
    "à justifier de motifs ni à payer de pénalités, à l'exception des frais de retour du bien commandé."
)
BODY_ENTITY = (
    "Les agents de la Direction générale de la concurrence, de la consommation et de la répression des fraudes "
    "(DGCCRF) recherchent et constatent les infractions ; la Banque de France tient le fichier des incidents de "
    "remboursement des crédits aux particuliers."
)


def _write(corpus: Path, number: str, legi_id: str, etat: str, body: str, date: str = "2016-07-01") -> None:
    stem = f"consommation_{number}_{legi_id}"
    (corpus / f"{stem}.txt").write_text(f"Code de la consommation — Article {number}\n\n{body}", encoding="utf-8")
    (corpus / f"{stem}.json").write_text(
        json.dumps(
            {
                "code": "consommation",
                "code_title": "Code de la consommation",
                "article_number": number,
                "legi_id": legi_id,
                "etat": etat,
                "date_debut": date,
                "path": ["Partie législative nouvelle", "Livre II : CONTRATS"],
            }
        ),
        encoding="utf-8",
    )


def _corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "consommation" / "corpus"
    corpus.mkdir(parents=True)
    _write(corpus, "L221-18", "LEGIARTI2", "VIGUEUR", BODY_18)
    _write(corpus, "L221-18", "LEGIARTI1", "MODIFIE", BODY_OLD + " " + BODY_18.split("\n")[0], date="1993-07-27")
    _write(corpus, "L511-3", "LEGIARTI3", "VIGUEUR", BODY_ENTITY)
    _write(corpus, "L121-21", "LEGIARTI4", "ABROGE", BODY_OLD)
    _write(corpus, "Annexe_III", "LEGIARTI5", "VIGUEUR", BODY_18)
    return corpus


def test_passages_come_from_numbered_articles_in_force(tmp_path: Path):
    corpus = _corpus(tmp_path)
    passages = sample_passages(corpus, count=10, seed=1)
    assert {passage.legi_id for passage in passages} == {"LEGIARTI2", "LEGIARTI3"}
    for passage in passages:
        text = (corpus / passage.file_name).read_text(encoding="utf-8")
        assert text[passage.start : passage.end] == passage.text
        assert not passage.text.startswith("Code de la consommation")  # heading skipped
    by_id = {passage.legi_id: passage for passage in passages}
    assert by_id["LEGIARTI2"].version_count == 2
    assert by_id["LEGIARTI2"].other_versions == ["consommation_L221-18_LEGIARTI1.txt"]
    assert by_id["LEGIARTI3"].version_count == 1


def test_passage_sampling_is_deterministic(tmp_path: Path):
    corpus = _corpus(tmp_path)
    first = sample_passages(corpus, count=2, seed=3)
    second = sample_passages(corpus, count=2, seed=3)
    assert [(p.file_name, p.start) for p in first] == [(p.file_name, p.start) for p in second]


def test_french_vague_and_boilerplate_rules():
    assert text_rejection_reason("Que prévoit cet article en cas de retard ?", "un remboursement") == "vague"
    assert text_rejection_reason("Que dit le présent code sur la garantie ?", "deux ans") == "vague"
    assert text_rejection_reason("Quel délai est mentionné pour la rétractation ?", "quatorze jours") == "vague"
    assert text_rejection_reason("Qui fixe les modalités du crédit ?", "par décret en Conseil d'État") == (
        "boilerplate_answer"
    )
    assert text_rejection_reason("Quand le texte s'applique-t-il ?", "entrent en vigueur le 1er juillet") == (
        "boilerplate_answer"
    )
    assert text_rejection_reason("Combien de jours pour se rétracter d'un achat à distance ?", "quatorze jours") is None


def test_reference_questions_must_cite_the_article_as_the_resolver_reads_it(tmp_path: Path):
    passage = next(p for p in sample_passages(_corpus(tmp_path), count=4, seed=0) if p.legi_id == "LEGIARTI2")
    answer = "quatorze jours"
    good = {"question": "Quel délai prévoit l'article L. 221-18 du code de la consommation pour se rétracter ?"}
    wrong_article = {"question": "Quel délai prévoit l'article L. 221-19 du code de la consommation ?"}
    other_code = {"question": "Quel délai prévoit l'article L. 221-18 du code de commerce pour se rétracter ?"}
    assert _rejection_reason({**good, "answer": answer}, passage, "reference") is None
    assert _rejection_reason({**wrong_article, "answer": answer}, passage, "reference") == "reference_missing"
    assert _rejection_reason({**other_code, "answer": answer}, passage, "reference") == "reference_missing"
    # A paraphrase must not give the article away.
    assert _rejection_reason({**good, "answer": answer}, passage, "paraphrase") == "leaks_reference"


def test_splits_are_seeded_and_stratified_by_type():
    cases = [
        GroundTruthCase(id=f"q{index:02d}", question="?", expected_file_names=[], question_type=kind)
        for index, kind in enumerate(["paraphrase"] * 8 + ["reference"] * 4)
    ]
    assign_splits(cases, seed=42)
    first = [case.split for case in cases]
    assign_splits(cases, seed=42)
    assert [case.split for case in cases] == first
    dev = [case for case in cases if case.split == "dev"]
    assert sorted(case.question_type for case in dev) == ["paraphrase", "paraphrase", "reference"]


def _fake_writer(messages, **_):
    """Answers like a well-behaved model: the right article, a real quote."""
    prompt = messages[0]["content"]
    reference = re.search(r"RÉFÉRENCE : article (\S+ \S+)", prompt)
    if "DGCCRF" in prompt:
        if reference:
            question = f"Qui tient le fichier selon l'article {reference.group(1)} du code de la consommation ?"
        else:
            question = "Qui tient le fichier des incidents de remboursement des crédits ?"
        return {"answer": json.dumps({"question": question, "answer": "la Banque de France"})}
    if reference:
        question = f"Quel délai l'article {reference.group(1)} du code de la consommation donne-t-il ?"
    else:
        question = "Combien de jours pour annuler un achat fait sur internet ?"
    return {"answer": "Voici : " + json.dumps({"question": question, "answer": "quatorze jours"})}


def test_generate_writes_spans_splits_and_version_context(tmp_path: Path):
    corpus = _corpus(tmp_path)
    client = MagicMock()
    client.chat.side_effect = _fake_writer
    generator = LegiQuestionGenerator(client=client, backend="llamacpp", model="qwen-test")
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=2, seed=0)

    cases = [json.loads(line) for line in Path(result["ground_truth_path"]).read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 2
    for case in cases:
        (span,) = case["expected_spans"]
        text = (corpus / span["file_name"]).read_text(encoding="utf-8")
        assert text[span["start"] : span["end"]] == span["text"]
        assert case["split"] in {"dev", "heldout"}
        assert case["id"].startswith("legi-consommation-")
    on_l221_18 = next(case for case in cases if case["context"]["article"] == "L221-18")
    assert on_l221_18["context"]["version_count"] == 2
    # The older version also says "quatorze jours": the version trap is recorded.
    assert on_l221_18["context"]["answer_in_other_version"] is True
    metadata = json.loads((tmp_path / "out" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["language"] == "fr"
    assert metadata["generator_model"] == "qwen-test"
    assert sum(metadata["by_split"].values()) == 2
    prompt = client.chat.call_args_list[0].kwargs["messages"][0]["content"]
    assert prompt.startswith("PLAN : Code de la consommation > Partie législative nouvelle > Livre II : CONTRATS")


def test_review_marks_cases_failing_current_rules(tmp_path: Path):
    path = tmp_path / "ground_truth.jsonl"
    rows = [
        {"id": "a", "question": "Que prévoit cet article ?", "ground_truth_answer": "quatorze jours"},
        {"id": "b", "question": "Combien de jours pour se rétracter ?", "ground_truth_answer": "quatorze jours"},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    assert review_question_set(path) == {"vague": 1}
    reviewed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row.get("review_status") for row in reviewed] == ["rejected", None]
    assert reviewed[0]["rejection_reason"] == "vague"


def test_scenario_questions_describe_a_situation_without_giving_the_article_away(tmp_path: Path):
    passage = next(p for p in sample_passages(_corpus(tmp_path), count=4, seed=0) if p.legi_id == "LEGIARTI2")
    answer = "quatorze jours"
    good = {"question": "Mon client a acheté un canapé en ligne il y a dix jours, peut-il encore annuler ?"}
    assert _rejection_reason({**good, "answer": answer}, passage, "scenario") is None
    cited = {"question": "Mon client peut-il annuler selon l'article L. 221-18 ?"}
    assert _rejection_reason({**cited, "answer": answer}, passage, "scenario") == "leaks_reference"
    code = {"question": "Selon le code de la consommation, mon client peut-il encore annuler son achat ?"}
    assert _rejection_reason({**code, "answer": answer}, passage, "scenario") == "names_code"
    copied = {"question": "Le consommateur dispose d'un délai de combien pour exercer son droit ?"}
    assert _rejection_reason({**copied, "answer": answer}, passage, "scenario") == "copies_wording"
    dated = {"question": "Mon client a acheté un canapé en ligne en 2015, pouvait-il annuler ?"}
    assert _rejection_reason({**dated, "answer": answer}, passage, "scenario") == "dated"


def test_scenario_is_the_main_type(tmp_path: Path):
    corpus = _corpus(tmp_path)
    client = MagicMock()
    client.chat.side_effect = _fake_writer
    generator = LegiQuestionGenerator(client=client, backend="llamacpp", model="qwen-test")
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=2, seed=0)
    assert result["by_type"]["scenario"] >= 1
    first_prompt = client.chat.call_args_list[0].kwargs["messages"][0]["content"]
    assert "TYPE : scenario" in first_prompt
