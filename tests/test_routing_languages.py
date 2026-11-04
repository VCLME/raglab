from __future__ import annotations

import pytest

from raglab.experiments.routing_languages import (
    AbstentionPolicy,
    RoutingPolicy,
    calibrate,
    compare,
    corpus_scores,
    paired,
    replay,
)

LANGUAGES = {"lexml": "pt", "piaf": "fr"}
DOCUMENTARY = {"documentary": 0.9, "conversational": 0.8, "out_of_scope": 0.8}


def _entry(dense, rerank=1.0, hit=True, translated=None, **extra):
    entry = {
        "dense": dense,
        "rerank": rerank,
        "hit": hit,
        "timings_ms": {"embed": 10.0, "retrieval": 40.0, "rerank": 300.0},
        "translated": translated is not None,
        "translation_ms": 2000.0 if translated is not None else 0.0,
        "legal_citation_found": False,
    }
    if translated is not None:
        entry.update(dense_translated=translated, translated_dense_ms=5.0, **extra)
    return entry


def _record(case_id, source, language, expected, chunk, examples, corpora, category="in_scope"):
    return {
        "id": case_id,
        "source": source,
        "category": category,
        "language": language,
        "language_detected": language,
        "expected_corpus": expected,
        "intent_scores": DOCUMENTARY,
        "chunk_centroid": chunk,
        "examples": examples,
        "router_ms": {"total": 20.0},
        "corpora": corpora,
    }


def _report():
    french = _record(
        "q1",
        "lexml_fr",
        "fr",
        "lexml",
        {"lexml": 0.84, "piaf": 0.85},
        {"lexml": {"fr": 0.90, "pt": 0.85}, "piaf": {"fr": 0.86}},
        {
            "lexml": _entry(
                0.83,
                translated=0.88,
                chunk_centroid_translated=0.89,
                examples_translated={"lexml": {"fr": 0.86, "pt": 0.93}, "piaf": {"fr": 0.8}},
            ),
            "piaf": _entry(0.80, hit=False),
        },
    )
    piaf = _record(
        "q2",
        "piaf",
        "fr",
        "piaf",
        {"lexml": 0.80, "piaf": 0.86},
        {"lexml": {"fr": 0.82, "pt": 0.80}, "piaf": {"fr": 0.90}},
        {"lexml": _entry(0.81, translated=0.82, chunk_centroid_translated=0.81), "piaf": _entry(0.85)},
    )
    off_topic = _record(
        "x1",
        "abstention",
        "fr",
        None,
        {"lexml": 0.80, "piaf": 0.86},
        {"lexml": {"fr": 0.82}, "piaf": {"fr": 0.84}},
        {"lexml": _entry(0.82, translated=0.83), "piaf": _entry(0.79, rerank=-8.0)},
        category="out_of_scope",
    )
    calibration = [
        {"corpus": "lexml", "language": "pt", "dense": 0.87, "rerank": 0.0},
        {"corpus": "lexml", "language": "fr", "dense": 0.84, "dense_translated": 0.87, "rerank": -1.0},
        {"corpus": "piaf", "language": "fr", "dense": 0.80, "rerank": -5.0},
    ]
    return {
        "config": {
            "corpus_languages": LANGUAGES,
            "abstention_thresholds": {"lexml": 0.85, "piaf": 0.79},
            "rerank_abstention_thresholds": {"lexml": -3.0, "piaf": -5.0},
        },
        "records": [french, piaf, off_topic],
        "calibration": calibration,
    }


def test_chunk_centroids_send_the_french_question_to_the_french_corpus():
    scores = corpus_scores(_report()["records"][0], RoutingPolicy("chunks"), LANGUAGES)
    assert max(scores, key=lambda c: scores[c]) == "piaf"


def test_rescoring_reads_the_translated_question_within_the_margin():
    record = _report()["records"][0]
    assert corpus_scores(record, RoutingPolicy("chunks", 0.02), LANGUAGES)["lexml"] == pytest.approx(0.89)
    # Outside the margin the translation is not read.
    assert corpus_scores(record, RoutingPolicy("chunks", 0.001), LANGUAGES)["lexml"] == pytest.approx(0.84)


def test_example_centroids_take_the_closest_language():
    scores = corpus_scores(_report()["records"][0], RoutingPolicy("examples"), LANGUAGES)
    assert scores == {"lexml": 0.90, "piaf": 0.86}


def test_replay_counts_answers_refusals_and_latency():
    report = _report()
    run = replay(report, RoutingPolicy("chunks", 0.02), AbstentionPolicy("dense_xl", "production"))
    by_source = run["metrics"]["by_source"]
    assert by_source["lexml_fr"]["answered_right"] == 1
    assert by_source["piaf"]["answered_right"] == 1
    # The off-topic question stays on PIAF and scores above its threshold.
    assert run["metrics"]["refusals_kept"] == 0
    # Router + retrieval, the translation for the chosen corpus counted once.
    assert by_source["lexml_fr"]["latency_p50_ms"] == pytest.approx(20 + 350 + 5)


def test_dense_without_translation_refuses_the_french_question():
    run = replay(_report(), RoutingPolicy("chunks", 0.02), AbstentionPolicy("dense", "production"))
    assert run["metrics"]["by_source"]["lexml_fr"]["refused"] == 1


def test_language_thresholds_are_calibrated_per_language_and_corpus():
    report = _report()
    production = {"dense": {"lexml": 0.85}, "rerank": {}}
    lookup = calibrate(report["calibration"], AbstentionPolicy("dense", "language", 0.5), LANGUAGES, production)
    assert lookup("lexml", "fr") == pytest.approx(0.84)
    assert lookup("lexml", "pt") == pytest.approx(0.87)
    # A language without calibration questions keeps the production threshold, as in the router.
    assert lookup("lexml", "en") == pytest.approx(0.85)
    corpus = calibrate(report["calibration"], AbstentionPolicy("dense", "corpus", 0.5), LANGUAGES, {})
    assert corpus("lexml", "fr") == pytest.approx(0.87)


def test_paired_counts_gains_and_losses():
    report = _report()
    before = replay(report, RoutingPolicy("chunks", 0.02), AbstentionPolicy("dense", "production"))
    after = replay(report, RoutingPolicy("chunks", 0.02), AbstentionPolicy("dense_xl", "production"))
    assert paired(before, after)["lexml_fr"] == {"gained": 1, "lost": 0, "p_value": 1.0}


def test_compare_lists_every_setting():
    comparison = compare(_report())
    names = [row["name"] for row in comparison["rows"]]
    assert names[0] == "default"
    assert "c_examples" in names
