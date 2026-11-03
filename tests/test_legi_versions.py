"""The frozen "versions" question set (phase 9.10): trap mining on a small
code with history, the checks on written questions, the written cases."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from raglab.benchmarks.legi_versions import (
    LegiVersionQuestionGenerator,
    kind_quotas,
    load_versions,
    mine_candidates,
    rejection_reason,
)
from raglab.config import Settings

TODAY = date(2026, 11, 3)

WITHDRAWAL_2014 = (
    "Le consommateur dispose d'un délai de quatorze jours pour exercer son droit de rétractation d'un contrat "
    "conclu à distance, à la suite d'un démarchage téléphonique ou hors établissement, sans avoir à motiver sa "
    "décision ni à supporter d'autres coûts que ceux prévus aux articles L. 121-21-3 à L. 121-21-5.\n"
    "Le délai mentionné au premier alinéa court à compter du jour de la conclusion du contrat, pour les contrats "
    "de prestation de services et ceux mentionnés à l'article L. 121-16-2, ou de la réception du bien."
)
WITHDRAWAL_1993 = (
    "Le consommateur dispose d'un délai de sept jours pour exercer son droit de rétractation d'un contrat "
    "conclu à distance, à la suite d'un démarchage téléphonique ou hors établissement, sans avoir à motiver sa "
    "décision ni à supporter d'autres coûts que ceux prévus aux articles L. 121-21-3 à L. 121-21-5.\n"
    "Le délai mentionné au premier alinéa court à compter du jour de la conclusion du contrat, pour les contrats "
    "de prestation de services et ceux mentionnés à l'article L. 121-16-2, ou de la réception du bien."
)
WITHDRAWAL_2016 = WITHDRAWAL_2014.replace("L. 121-21-3 à L. 121-21-5", "L. 221-23 à L. 221-25").replace(
    "L. 121-16-2", "L. 221-2"
)
EXTENSION_2016 = (
    "Lorsque les informations relatives au droit de rétractation n'ont pas été fournies au consommateur dans les "
    "conditions prévues à l'article L. 221-5, le délai de rétractation est prolongé de trois mois à compter de "
    "l'expiration du délai initial, déterminé conformément à l'article L. 221-18."
)
EXTENSION_2022 = EXTENSION_2016.replace("trois mois", "douze mois")
FEES_2016 = (
    "Est interdit le fait pour un professionnel de solliciter ou de percevoir d'un consommateur des frais de "
    "recouvrement dans des conditions contraires au deuxième alinéa de l'article L. 111-8 du code des procédures "
    "civiles d'exécution, sous peine de l'amende administrative prévue au présent livre."
)


def _write(corpus: Path, number: str, legi_id: str, etat: str, start: str, end: str | None, body: str) -> None:
    stem = f"consommation_{number}_{legi_id}"
    text = f"Code de la consommation — Article {number}\n\n{body}"
    (corpus / f"{stem}.txt").write_text(text, encoding="utf-8")
    metadata = {
        "code": "consommation",
        "code_title": "Code de la consommation",
        "article_number": number,
        "legi_id": legi_id,
        "etat": etat,
        "date_debut": start,
        "date_fin": end,
        "path": ["Partie législative", "Livre II"],
    }
    (corpus / f"{stem}.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")


def _corpus(tmp_path: Path) -> Path:
    """L. 121-21: seven days (1993), fourteen days (2014), repealed in 2016
    and reused for debt-collection fees; the rule moved to L. 221-18.
    L. 221-20: the extension of the period went from three to twelve months."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write(corpus, "L121-21", "LEGIARTI01", "MODIFIE", "1993-07-27", "2014-06-14", WITHDRAWAL_1993)
    _write(corpus, "L121-21", "LEGIARTI02", "ABROGE", "2014-06-14", "2016-07-01", WITHDRAWAL_2014)
    _write(corpus, "L121-21", "LEGIARTI03", "VIGUEUR", "2016-07-01", None, FEES_2016)
    _write(corpus, "L221-18", "LEGIARTI04", "VIGUEUR", "2016-07-01", None, WITHDRAWAL_2016)
    _write(corpus, "L221-20", "LEGIARTI05", "MODIFIE", "2016-07-01", "2022-05-28", EXTENSION_2016)
    _write(corpus, "L221-20", "LEGIARTI06", "VIGUEUR", "2022-05-28", None, EXTENSION_2022)
    return corpus


def test_traps_are_mined_from_the_version_history(tmp_path):
    corpus = _corpus(tmp_path)
    assert [row.legi_id for row in load_versions(corpus)[("consommation", "L121-21")]] == [
        "LEGIARTI01",
        "LEGIARTI02",
        "LEGIARTI03",
    ]
    mined = mine_candidates(corpus, today=TODAY)

    rewritten = {c.expected.legi_id: c for c in mined["rewritten"]}
    assert rewritten["LEGIARTI06"].traps[0].legi_id == "LEGIARTI05"
    assert "trois mois" in rewritten["LEGIARTI06"].trap_passage
    assert "douze mois" in rewritten["LEGIARTI06"].passage

    reused = {c.expected.legi_id: c for c in mined["reused_number"]}
    assert [trap.legi_id for trap in reused["LEGIARTI03"].traps] == ["LEGIARTI02", "LEGIARTI01"]

    moved = {c.expected.legi_id: c for c in mined["moved"]}
    assert moved["LEGIARTI04"].traps[0].legi_id == "LEGIARTI02"

    as_of = {c.expected.legi_id: c for c in mined["as_of"]}
    old = as_of["LEGIARTI05"]
    assert (old.as_of, old.as_of_phrase) == (date(2021, 12, 31), "avant 2022")
    assert old.traps[0].legi_id == "LEGIARTI06"


def test_quotas_add_up():
    assert kind_quotas(100) == {"rewritten": 40, "reused_number": 20, "moved": 20, "as_of": 20}
    assert sum(kind_quotas(37).values()) == 37


def _candidate(tmp_path: Path, kind: str, legi_id: str):
    mined = mine_candidates(_corpus(tmp_path), today=TODAY)
    return next(c for c in mined[kind] if c.expected.legi_id == legi_id)


def test_a_rewritten_trap_needs_both_quotes_in_their_version(tmp_path):
    candidate = _candidate(tmp_path, "rewritten", "LEGIARTI06")
    good = {
        "question": "De combien le délai de rétractation est-il prolongé quand le consommateur n'a pas été informé ?",
        "answer": "douze mois",
        "outdated_answer": "trois mois",
    }
    assert rejection_reason(good, candidate) is None
    assert rejection_reason({**good, "outdated_answer": "six mois"}, candidate) == "outdated_answer_not_found"
    same = {**good, "answer": "droit de rétractation"}
    assert rejection_reason(same, candidate) == "answer_in_trap"
    cited = {**good, "question": "Que prévoit l'article L. 221-20 sur le délai de rétractation ?"}
    assert rejection_reason(cited, candidate) == "leaks_reference"
    dated = {**good, "question": "Avant 2016, de combien le délai de rétractation était-il prolongé ?"}
    assert rejection_reason(dated, candidate) == "unexpected_date"
    assert rejection_reason(None, candidate) == "invalid_json"


def test_an_as_of_trap_must_ask_about_a_date_the_old_version_covers(tmp_path):
    candidate = _candidate(tmp_path, "as_of", "LEGIARTI05")
    good = {
        "question": "Avant 2022, de combien le délai de rétractation était-il prolongé faute d'information ?",
        "answer": "trois mois",
        "outdated_answer": "douze mois",
    }
    assert rejection_reason(good, candidate) is None
    undated = {**good, "question": "De combien le délai de rétractation est-il prolongé faute d'information ?"}
    assert rejection_reason(undated, candidate) == "date_missing"
    too_late = {**good, "question": "En vigueur en 2023, de combien le délai de rétractation était-il prolongé ?"}
    assert rejection_reason(too_late, candidate) == "date_missing"


def test_a_reused_number_trap_cites_the_number(tmp_path):
    candidate = _candidate(tmp_path, "reused_number", "LEGIARTI03")
    good = {
        "question": "Que prévoit l'article L. 121-21 du code de la consommation sur les frais de recouvrement ?",
        "answer": "des frais de recouvrement",
    }
    assert rejection_reason(good, candidate) is None
    uncited = {**good, "question": "Quels frais un professionnel ne peut-il pas percevoir d'un consommateur ?"}
    assert rejection_reason(uncited, candidate) == "reference_missing"


class _ScriptedChat:
    """Answers with the quotes of each kind, as the model should."""

    def chat(self, *, messages, model, system, options, **extra):
        prompt = messages[0]["content"]
        if "RÉFÉRENCE" in prompt:
            payload = {
                "question": "Que prévoit l'article L. 121-21 du code de la consommation sur les frais de recouvrement ?",
                "answer": "des frais de recouvrement",
            }
        elif "DATE : avant 2022" in prompt:
            payload = {
                "question": "Avant 2022, de combien le délai de rétractation était-il prolongé faute d'information ?",
                "answer": "trois mois",
                "outdated_answer": "douze mois",
            }
        elif "ANCIENNE RÉDACTION" in prompt and "trois mois" in prompt.split("ANCIENNE RÉDACTION")[1]:
            payload = {
                "question": "De combien le délai de rétractation est-il prolongé quand le consommateur n'a pas été informé ?",
                "answer": "douze mois",
                "outdated_answer": "trois mois",
            }
        else:
            payload = {
                "question": "Le consommateur qui se rétracte d'un contrat conclu à distance doit-il se justifier ?",
                "answer": "sans avoir à motiver sa décision",
            }
        return {"answer": json.dumps(payload, ensure_ascii=False)}


def test_generated_cases_name_the_trap_and_the_date(tmp_path):
    corpus = _corpus(tmp_path)
    generator = LegiVersionQuestionGenerator(Settings(), backend="llamacpp", client=_ScriptedChat(), model="qwen")
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=5, seed=42, today=TODAY)

    cases = [json.loads(line) for line in (tmp_path / "out" / "ground_truth.jsonl").read_text("utf-8").splitlines()]
    by_type = {case["question_type"]: case for case in cases}
    assert set(by_type) == {"rewritten", "reused_number", "moved", "as_of"}
    assert result["case_count"] == len(cases) == 4

    rewritten = by_type["rewritten"]
    assert rewritten["expected_file_names"] == ["consommation_L221-20_LEGIARTI06.txt"]
    assert rewritten["trap"]["file_names"] == ["consommation_L221-20_LEGIARTI05.txt"]
    assert rewritten["trap"]["answer"] == "trois mois"
    span = rewritten["expected_spans"][0]
    text = (corpus / span["file_name"]).read_text(encoding="utf-8")
    assert text[span["start"] : span["end"]] == "douze mois"

    as_of = by_type["as_of"]
    assert as_of["context"]["as_of"] == "2021-12-31"
    assert as_of["expected_file_names"] == ["consommation_L221-20_LEGIARTI05.txt"]
    assert as_of["trap"]["file_names"][0] == "consommation_L221-20_LEGIARTI06.txt"

    moved = by_type["moved"]
    assert (moved["context"]["article"], moved["trap"]["article"]) == ("L221-18", "L121-21")
    assert {case["split"] for case in cases} <= {"dev", "heldout"}
    metadata = json.loads((tmp_path / "out" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["generator_model"] == "qwen" and metadata["seed"] == 42
