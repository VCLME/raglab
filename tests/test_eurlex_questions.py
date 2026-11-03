from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from raglab.benchmarks.eurlex_questions import (
    CitingUnit,
    EurlexQuestionGenerator,
    Passage,
    citing_units,
    load_sidecars,
    rejection_reason,
    review_question_set,
    sample_passages,
    text_rejection_reason,
)

DORA = "32022R2554"
ART30_EN = [
    "1. The rights and obligations of the financial entity and of the ICT third-party service provider shall be "
    "clearly allocated and set out in writing.",
    "2. The contractual arrangements on the use of ICT services shall include a clear and complete description of "
    "all functions and ICT services to be provided by the ICT third-party service provider.",
]
ART30_FR = [
    "1. Les droits et obligations de l’entité financière et du prestataire tiers de services TIC sont définis "
    "clairement et consignés par écrit.",
    "2. Les accords contractuels relatifs à l’utilisation de services TIC comprennent une description claire et "
    "complète de toutes les fonctions et de tous les services TIC à fournir par le prestataire.",
]
ART28_EN = [
    "1. Financial entities shall manage ICT third-party risk as an integral component of ICT risk within their "
    "ICT risk management framework, and in line with Article 30 on key contractual provisions.",
    "2. Financial entities that rely on ICT services remain fully responsible for compliance with all their "
    "obligations under this Regulation and the applicable financial services law at all times.",
]


def _write(corpus: Path, name: str, language: str, number: str, lines: list[str], references: list[dict]) -> None:
    label = {"en": "Article", "fr": "Article"}[language]
    text = f"Regulation (EU) 2022/2554 (DORA) — {label} {number}\nTitle\n\n" + "\n".join(lines)
    (corpus / f"{name}.txt").write_text(text, encoding="utf-8")
    (corpus / f"{name}.json").write_text(
        json.dumps(
            {
                "celex": DORA,
                "act_short": "DORA",
                "unit": "article",
                "unit_number": number,
                "unit_label": f"{label} {number}",
                "unit_key": f"{DORA}:article:{number}",
                "language": language,
                "in_force": True,
                "version_count": 1,
                "references": references,
            }
        ),
        encoding="utf-8",
    )


def _corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    cite_30 = [{"unit": "article", "number": "30", "celex": DORA, "scope": "same_act", "text": "Article 30"}]
    _write(corpus, "dora_en_art028_oj", "en", "28", ART28_EN, cite_30)
    _write(corpus, "dora_en_art030_oj", "en", "30", ART30_EN, [])
    _write(corpus, "dora_fr_art030_oj", "fr", "30", ART30_FR, [])
    return corpus


def test_passages_are_drawn_one_unit_at_a_time(tmp_path: Path):
    corpus = _corpus(tmp_path)
    passages = sample_passages(corpus, count=2, seed=3, target_chars=250)
    assert len({passage.number for passage in passages}) == 2
    again = sample_passages(corpus, count=2, seed=3, target_chars=250)
    assert [(p.file_name, p.start) for p in passages] == [(p.file_name, p.start) for p in again]
    article_30 = next(
        passage for passage in sample_passages(corpus, count=4, seed=1, target_chars=250) if passage.number == "30"
    )
    other = {"en": "dora_fr_art030_oj.txt", "fr": "dora_en_art030_oj.txt"}[article_30.language]
    assert article_30.same_unit_files == [other]


def test_citing_units_link_same_language_units(tmp_path: Path):
    cited_by = citing_units(load_sidecars(_corpus(tmp_path)))
    assert [name for name, _ in cited_by["dora_en_art030_oj.txt"]] == ["dora_en_art028_oj.txt"]
    assert "dora_fr_art030_oj.txt" not in cited_by


def test_text_rules_in_three_languages():
    assert text_rejection_reason("What does this Article require?", "clearly allocated") == "vague"
    assert text_rejection_reason("Que prévoit cet article ?", "définis clairement") == "vague"
    assert text_rejection_reason("O que prevê este artigo?", "definidos claramente") == "vague"
    assert (
        text_rejection_reason("When does DORA apply?", "This Regulation shall enter into force") == "boilerplate_answer"
    )
    assert text_rejection_reason("How must DORA contracts allocate rights?", "clearly allocated and set out") is None


def _passage(language: str = "en") -> Passage:
    text = "\n".join(ART30_EN if language == "en" else ART30_FR)
    return Passage(
        file_name=f"dora_{language}_art030_oj.txt",
        celex=DORA,
        act_short="DORA",
        unit="article",
        number="30",
        unit_label="Article 30",
        language=language,
        start=0,
        end=len(text),
        text=text,
        version_count=1,
    )


def test_type_checks():
    passage = _passage()
    answer = "clearly allocated and set out in writing"
    ok = {"question": "Under Article 30 of DORA, how must rights and obligations be recorded?", "answer": answer}
    assert rejection_reason(ok, passage, "reference", language="en") is None
    assert rejection_reason(ok, passage, "paraphrase", language="en") == "leaks_reference"
    assert rejection_reason(ok, passage, "reference", language="fr") == "wrong_language"
    missing = {"question": "Under DORA, how must rights and obligations be recorded?", "answer": answer}
    assert rejection_reason(missing, passage, "reference", language="en") == "reference_missing"
    assert rejection_reason(missing, passage, "paraphrase", language="en") is None
    # Cross-language: French question, answer quoted from the English passage.
    french = {"question": "Selon DORA, comment les droits des parties doivent-ils être consignés ?", "answer": answer}
    assert rejection_reason(french, passage, "cross_language", language="fr") is None

    citing_text = ART28_EN[0]
    citing = CitingUnit(
        "dora_en_art028_oj.txt", "article", "28", DORA, "DORA", "Article 28", 0, len(citing_text), citing_text
    )
    cross = {"question": "Under Article 28 of DORA, how must the key contractual rights be recorded?", "answer": answer}
    assert (
        rejection_reason(cross, passage, "cross_reference", language="en", citing=citing, citing_text=citing_text)
        is None
    )
    leaked = {"question": "Under Article 28 of DORA and its Article 30, how are rights recorded?", "answer": answer}
    reason = rejection_reason(leaked, passage, "cross_reference", language="en", citing=citing, citing_text=citing_text)
    assert reason == "leaks_target"


_QUESTIONS = {
    "en": (
        "Under DORA, how must the arrangements with ICT providers be recorded?",
        "Under {ref} of DORA, how must the arrangements be recorded?",
    ),
    "fr": (
        "Selon DORA, comment les accords avec les prestataires TIC sont-ils consignés ?",
        "Selon l'{ref} de DORA, comment les accords sont-ils consignés ?",
    ),
    "pt": (
        "Nos termos do DORA, como são registados os acordos com os prestadores de TIC?",
        "Nos termos do {ref} do DORA, como são registados os acordos?",
    ),
}


def _fake_writer(*, messages, **_):
    prompt = messages[0]["content"]
    kind = re.search(r"^TYPE: (\w+)$", prompt, re.MULTILINE).group(1)
    language = {"English": "en", "French": "fr", "Portuguese": "pt"}[
        re.search(r"^LANGUAGE: (\w+)$", prompt, re.MULTILINE).group(1)
    ]
    passage = prompt.split("):\n", 1)[1].split("\n\nAnswer only", 1)[0]
    answer = " ".join(passage.split("\n")[0].split()[1:8])
    plain, cited = _QUESTIONS[language]
    if kind in ("reference", "cross_reference"):
        reference = re.search(r"^REFERENCE: (\w+) (\w+) — ", prompt, re.MULTILINE)
        word = {"en": "Article", "fr": "article", "pt": "artigo"}[language]
        question = cited.format(ref=f"{word} {reference.group(2)}" + (".º" if language == "pt" else ""))
    else:
        question = plain
    return {"answer": json.dumps({"question": question, "answer": answer})}


def test_generate_writes_typed_cases_with_spans_and_context(tmp_path: Path):
    corpus = _corpus(tmp_path)
    client = MagicMock()
    client.chat.side_effect = _fake_writer
    generator = EurlexQuestionGenerator(client=client, backend="llamacpp", model="qwen-test")
    result = generator.generate(corpus_dir=corpus, output_dir=tmp_path / "out", count=3, seed=0)

    cases = [json.loads(line) for line in Path(result["ground_truth_path"]).read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 3
    assert {case["question_type"] for case in cases} >= {"paraphrase", "reference"}
    for case in cases:
        (span,) = case["expected_spans"]
        text = (corpus / span["file_name"]).read_text(encoding="utf-8")
        assert text[span["start"] : span["end"]] == span["text"]
        assert case["split"] in {"dev", "heldout"} and case["id"].startswith("eurlex-")
        assert case["context"]["unit_key"].startswith(DORA)
    metadata = json.loads((tmp_path / "out" / "metadata.json").read_text(encoding="utf-8"))
    assert (metadata["language"], metadata["generator_model"], metadata["case_count"]) == ("multi", "qwen-test", 3)


def test_review_marks_cases_failing_current_rules(tmp_path: Path):
    path = tmp_path / "ground_truth.jsonl"
    rows = [
        {"id": "a", "question": "What does this Article require?", "ground_truth_answer": "clearly allocated"},
        {"id": "b", "question": "How must DORA contracts allocate rights?", "ground_truth_answer": "clearly allocated"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert review_question_set(path) == {"vague": 1}
    statuses = [json.loads(line).get("review_status") for line in path.read_text(encoding="utf-8").splitlines()]
    assert statuses == ["rejected", None]
