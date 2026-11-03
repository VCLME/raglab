from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from raglab.benchmarks.fquad import FQuADLoader, _article_stem


def _fake_dataset_rows() -> list[dict]:
    """Three synthetic FQuAD-shaped rows sharing the same (title, context)
    pair on the first two rows — the loader must dedupe them into a single
    article file and keep two ground-truth cases pointing to it.
    """
    ctx_a = "La Révolution française commence en 1789 avec la prise de la Bastille."
    ctx_b = "Molière est un dramaturge et comédien français du XVIIe siècle."
    return [
        {
            "id": "q1",
            "title": "Révolution française",
            "context": ctx_a,
            "question": "Quand commence la Révolution française ?",
            "answers": {"text": ["1789"], "answer_start": [39]},
        },
        {
            "id": "q2",
            "title": "Révolution française",
            "context": ctx_a,
            "question": "Quelle place est prise en premier ?",
            "answers": {"text": ["la Bastille"], "answer_start": [60]},
        },
        {
            "id": "q3",
            "title": "Molière",
            "context": ctx_b,
            "question": "Quel siècle pour Molière ?",
            "answers": {"text": ["XVIIe siècle"], "answer_start": [55]},
        },
    ]


def test_article_stem_is_deterministic_on_context():
    stem_a1 = _article_stem("Revolution francaise", "ctx a")
    stem_a2 = _article_stem("Revolution francaise", "ctx a")
    stem_b = _article_stem("Revolution francaise", "ctx b")
    assert stem_a1 == stem_a2
    assert stem_a1 != stem_b


def test_fquad_loader_download_writes_corpus_ground_truth_and_metadata(tmp_path: Path):
    loader = FQuADLoader()
    with patch("datasets.load_dataset", return_value=_fake_dataset_rows()):
        result = loader.download(tmp_path, limit=None)

    # Corpus: two unique articles (q1 & q2 share the same context)
    article_files = sorted(result.corpus_dir.glob("*.txt"))
    assert len(article_files) == 2
    sidecars = sorted(result.corpus_dir.glob("*.json"))
    assert len(sidecars) == 2
    for sidecar in sidecars:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        assert payload["source"] == "fquad"
        assert payload["hf_dataset"] == FQuADLoader.hf_dataset_id
        assert payload["title"]

    # Ground truth: 3 cases, each with exactly one expected file name that
    # matches one of the corpus files.
    cases = [
        json.loads(line) for line in result.ground_truth_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(cases) == 3
    corpus_names = {p.name for p in article_files}
    for case in cases:
        assert case["id"].startswith("fquad-")
        assert case["question"]
        assert len(case["expected_file_names"]) == 1
        assert case["expected_file_names"][0] in corpus_names
        assert case["ground_truth_answer"]
        assert case["expected_substrings"] == [case["ground_truth_answer"]]
    # The two cases on the same article should map to the same file.
    shared_file = cases[0]["expected_file_names"][0]
    assert cases[1]["expected_file_names"][0] == shared_file

    # Metadata sidecar
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert meta["loader"] == "fquad"
    assert meta["language"] == "fr"
    assert meta["article_count"] == 2
    assert meta["case_count"] == 3

    assert result.article_count == 2
    assert result.case_count == 3
    assert result.corpus_name == "fquad_fr"


def test_fquad_loader_respects_limit(tmp_path: Path):
    loader = FQuADLoader()
    with patch("datasets.load_dataset", return_value=_fake_dataset_rows()):
        result = loader.download(tmp_path, limit=2)
    cases = [
        json.loads(line) for line in result.ground_truth_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(cases) == 2
    assert result.case_count == 2


def test_fquad_loader_skips_rows_with_empty_context_or_question(tmp_path: Path):
    loader = FQuADLoader()
    rows = _fake_dataset_rows() + [
        {"id": "bad1", "title": "Empty ctx", "context": "", "question": "a?", "answers": {"text": []}},
        {"id": "bad2", "title": "Empty q", "context": "Some ctx", "question": "", "answers": {"text": []}},
    ]
    with patch("datasets.load_dataset", return_value=rows):
        result = loader.download(tmp_path)
    cases = [
        json.loads(line) for line in result.ground_truth_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(cases) == 3  # only the three valid rows from _fake_dataset_rows


def test_fquad_loader_raises_when_all_rows_are_empty(tmp_path: Path):
    loader = FQuADLoader()
    rows = [{"id": "x", "title": "t", "context": "", "question": "q?", "answers": {"text": []}}]
    with patch("datasets.load_dataset", return_value=rows):
        with pytest.raises(RuntimeError) as exc:
            loader.download(tmp_path)
    assert loader.name in str(exc.value)
