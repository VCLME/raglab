from __future__ import annotations

import hashlib
import json
from pathlib import Path

from raglab.benchmarks.suite import render_markdown, verify_manifest


def test_verify_manifest_reports_missing_and_changed_files(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.txt").write_text("texte a", encoding="utf-8")
    (corpus / "b.txt").write_text("texte b modifié", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {"file_name": "a.txt", "sha256": hashlib.sha256(b"texte a").hexdigest()},
                    {"file_name": "b.txt", "sha256": hashlib.sha256(b"texte b").hexdigest()},
                    {"file_name": "c.txt", "sha256": "0" * 64},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert verify_manifest(corpus, manifest) == ["changed:b.txt", "missing:c.txt"]


def _run(label: str, recall5: float, embed_p50: float, with_types: bool) -> dict:
    return {
        "label": label,
        "suites": [
            {
                "suite": "lexml_fulltext",
                "language": "pt",
                "total_cases": 277,
                "summary": {
                    "recall@5": recall5,
                    "mrr": 0.5,
                    "latency_embed_p50_ms": embed_p50,
                    "faithfulness_mean": 0.8,
                    "faithfulness_judged": 100,
                },
                "by_type": {"reference": {"cases": 97, "recall@5": 0.4, "mrr": 0.3}} if with_types else {},
            }
        ],
    }


def test_render_markdown_puts_runs_side_by_side():
    text = render_markdown([_run("v0", 0.61, 812.0, True), _run("v0.1", 0.61, 14.2, True)])
    assert "### lexml_fulltext (pt, 277 questions)" in text
    assert "| Métrique | v0 | v0.1 |" in text
    assert "| Recall@5 | 0.610 | 0.610 |" in text
    assert "| dont embedding p50 | 812 ms | 14.2 ms |" in text
    assert "| reference | 0.400 / 0.300 (97) | 0.400 / 0.300 (97) |" in text
    assert "Juges RAGAS calculés sur les 100 premières questions." in text
    assert "Answer relevancy" not in text  # rows without values are dropped


def test_report_names_the_retrieval_mode_of_each_run():
    dense = _run("baseline-v1", 0.61, 14.2, False)
    hybrid = _run("hybrid-v1", 0.66, 14.2, False)
    hybrid["retrieval_mode"] = "hybrid"
    hybrid["suites"][0].update({"retrieval_mode": "hybrid", "lexical_weight": 0.5, "rrf_k": 60})
    hybrid["suites"][0]["summary"]["latency_lexical_p50_ms"] = 19.3
    text = render_markdown([dense, hybrid])
    # Results written before 9.2 have no mode: they were dense.
    assert "| Retrieval | dense | hybrid (w=0.5, k=60) |" in text
    assert "| dont BM25 p50 | — | 19.3 ms |" in text


def test_report_shows_confidence_intervals():
    run = _run("v1", 0.61, 14.2, False)
    run["suites"][0]["summary"].update({"recall@5_ci_low": 0.55, "recall@5_ci_high": 0.67})
    assert "| Recall@5 | 0.610 [0.55–0.67] |" in render_markdown([run])


def test_total_ram_is_reported():
    from raglab.benchmarks.suite import _total_ram

    assert _total_ram().endswith("GiB")
