from __future__ import annotations

import json
from pathlib import Path

from raglab.experiments.judge_calibration import build_items, summarise


def _dataset(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    rows = []
    for index in range(4):
        name = f"p{index}.txt"
        (corpus / name).write_text(f"Paragraphe {index}. Le chiffre est {index * 10} et la ville est V{index}.", encoding="utf-8")
        rows.append({"id": f"q{index}a", "question": "Quel chiffre ?", "expected_file_names": [name], "ground_truth_answer": f"{index * 10}"})
        rows.append({"id": f"q{index}b", "question": "Quelle ville ?", "expected_file_names": [name], "ground_truth_answer": f"V{index}"})
    path = tmp_path / "gt.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path, corpus


def test_items_cover_every_variant_with_known_verdicts(tmp_path: Path):
    path, corpus = _dataset(tmp_path)
    items = build_items(path, corpus, count=3, seed=1)
    assert len(items) == 15
    variants = {item.variant: item for item in items}
    assert variants["faithful"].expected and variants["on_topic"].expected
    assert not variants["fabricated"].expected and not variants["off_topic"].expected
    embellished = variants["embellished"]
    assert not embellished.expected
    assert embellished.answer.startswith(variants["faithful"].answer)  # correct answer + an unsupported claim
    assert variants["fabricated"].answer not in variants["fabricated"].context


def test_summary_counts_unparsed_verdicts_as_wrong():
    rows = [
        {"variant": "faithful", "expected": True, "score": 1.0},
        {"variant": "fabricated", "expected": False, "score": 0.0},
        {"variant": "embellished", "expected": False, "score": 0.8},
        {"variant": "embellished", "expected": False, "score": None},
        {"variant": "on_topic", "expected": True, "score": 0.5},
        {"variant": "off_topic", "expected": False, "score": 0.2},
    ]
    summary = summarise(rows)
    assert summary["accuracy_by_variant"]["embellished"] == 0.0
    assert summary["accuracy_by_metric"] == {"faithfulness": 0.5, "answer_relevancy": 1.0}
    assert summary["unparsed"] == 1
