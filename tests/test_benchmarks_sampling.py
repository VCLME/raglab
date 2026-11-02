from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from raglab.benchmarks.piaf import PIAFLoader
from raglab.benchmarks.squad_style import locate_span


def _rows(count: int) -> list[dict]:
    """`count` paragraphs with two questions each; answers sit after a run of
    double spaces so normalisation shifts their offsets."""
    rows = []
    for index in range(count):
        context = f"  Paragraphe {index}.  Le  chiffre clé est {index * 7} unités."
        answer = str(index * 7)
        start = context.index(answer)
        for suffix in ("a", "b"):
            rows.append(
                {
                    "id": f"q{index:03d}{suffix}",
                    "title": f"Titre {index}",
                    "context": context,
                    "question": f"Quel est le chiffre du paragraphe {index} ({suffix}) ?",
                    "answers": {"text": [answer], "answer_start": [start]},
                }
            )
    return rows


def _cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_limit_samples_cases_but_keeps_full_haystack(tmp_path: Path):
    with patch("datasets.load_dataset", return_value=_rows(20)):
        result = PIAFLoader().download(tmp_path, limit=5, sample_seed=7)

    assert result.case_count == 5
    assert result.article_count == 20
    assert len(list(result.corpus_dir.glob("*.txt"))) == 20


def test_sample_is_deterministic_and_seed_dependent(tmp_path: Path):
    def sampled_ids(target: Path, seed: int) -> list[str]:
        with patch("datasets.load_dataset", return_value=_rows(20)):
            result = PIAFLoader().download(target, limit=5, sample_seed=seed)
        return [case["id"] for case in _cases(result.ground_truth_path)]

    first = sampled_ids(tmp_path / "a", 7)
    assert first == sampled_ids(tmp_path / "b", 7)
    assert first != sampled_ids(tmp_path / "c", 8)


def test_sample_does_not_depend_on_source_row_order(tmp_path: Path):
    rows = _rows(20)
    with patch("datasets.load_dataset", return_value=rows):
        forward = PIAFLoader().download(tmp_path / "f", limit=5, sample_seed=7)
    with patch("datasets.load_dataset", return_value=list(reversed(rows))):
        backward = PIAFLoader().download(tmp_path / "b", limit=5, sample_seed=7)
    assert _cases(forward.ground_truth_path) == _cases(backward.ground_truth_path)


def test_full_corpus_false_restores_legacy_small_haystack(tmp_path: Path):
    with patch("datasets.load_dataset", return_value=_rows(20)):
        result = PIAFLoader().download(tmp_path, limit=3, full_corpus=False)
    assert result.article_count <= 3


def test_spans_point_at_the_answer_in_the_written_text(tmp_path: Path):
    with patch("datasets.load_dataset", return_value=_rows(4)):
        result = PIAFLoader().download(tmp_path)

    for case in _cases(result.ground_truth_path):
        (span,) = case["expected_spans"]
        assert span["file_name"] == case["expected_file_names"][0]
        text = (result.corpus_dir / span["file_name"]).read_text(encoding="utf-8")
        assert text[span["start"] : span["end"]] == case["ground_truth_answer"]
        assert not text.startswith(" ")  # written already normalised


def test_locate_span_prefers_occurrence_nearest_to_hint():
    text = "12 pommes, puis 12 poires, puis 12 prunes"
    assert locate_span(text, "12", hint=16)["start"] == 16
    assert locate_span(text, "12", hint=0)["start"] == 0
    assert locate_span(text, "absent", hint=0) is None
