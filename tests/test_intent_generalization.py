from __future__ import annotations

import json

import numpy as np
import pytest

from raglab.experiments.intent_generalization import Model, Variant, decide, eligible, family, metrics
from raglab.experiments.routing import (
    ABSTENTION_PATH,
    CALIBRATION_FILES,
    EXTRA_SETS,
    REPO_ROOT,
    VALIDATION_ABSTENTION_PATH,
    load_calibration_files,
    load_cases,
)
from raglab.routing.intent_knn import JointGroup, load_training_examples


def _texts(path):
    return {json.loads(line)["question"].strip().lower() for line in path.read_text("utf-8").splitlines() if line}


def test_training_and_calibration_stay_out_of_every_evaluated_set():
    evaluated = _texts(ABSTENTION_PATH) | _texts(VALIDATION_ABSTENTION_PATH)
    for name in ("validation", "br_expat", "lexml_fr", "lexml_fr_pt"):
        evaluated |= _texts(EXTRA_SETS[name].path)
    for path in ("piaf/ground_truth.jsonl", "eurlex_compliance/ground_truth.jsonl"):
        evaluated |= _texts(REPO_ROOT / "benchmarks" / path)
    training = {
        text.strip().lower()
        for _, _, text in load_training_examples(REPO_ROOT / "benchmarks" / "routing" / "intent_training.jsonl")
    }
    assert training and not training & evaluated
    calibration = {case.question.strip().lower() for case in load_calibration_files(["br_expat"])}
    assert calibration and not calibration & evaluated
    # EUR-Lex calibration questions are drawn from its ground truth, never from the evaluated draw.
    eurlex = {case.id for case in load_calibration_files(["eurlex"])}
    validation_ids = {json.loads(line)["id"] for line in EXTRA_SETS["validation"].path.read_text("utf-8").splitlines()}
    assert eurlex and not eurlex & validation_ids


def test_calibration_files_name_their_corpus_and_language():
    cases = load_calibration_files(["lexml_fr", "br_expat", "eurlex"])
    assert {case.expected_corpus for case in cases} == {
        "bench_lexml_pt",
        "bench_br_expat_pt",
        "bench_eurlex_compliance",
    }
    assert {case.language for case in cases if case.expected_corpus == "bench_eurlex_compliance"} == {"en", "fr", "pt"}
    assert all(case.source.startswith("calibration:") for case in cases)
    with pytest.raises(ValueError):
        load_calibration_files(["nope"])
    assert set(CALIBRATION_FILES) >= {"br_expat", "eurlex"}


def test_validation_rows_keep_their_own_corpus():
    cases = load_cases(
        abstention_path=VALIDATION_ABSTENTION_PATH, in_scope_sets=(EXTRA_SETS["validation"],), sample_size=160
    )
    in_scope = [case for case in cases if case.category == "in_scope"]
    assert len(in_scope) == 160
    assert {case.expected_corpus for case in in_scope} == {
        "bench_piaf_fr",
        "bench_lexml_pt",
        "bench_br_expat_pt",
        "bench_eurlex_compliance",
    }
    assert len(cases) - len(in_scope) == 80


def _record(category="in_scope", **extra):
    record = {
        "question": "q",
        "category": category,
        "source": "piaf" if category == "in_scope" else "abstention",
        "language": "fr",
        "language_detected": "fr",
        "expected_corpus": "piaf" if category == "in_scope" else None,
        "corpus_routed": "piaf",
        "legal_citation": False,
        "hit": True,
        "dense_original": 0.85,
        "router_abstention": {"best_score": 0.85, "threshold": 0.8},
    }
    record.update(extra)
    return record


def test_decide_follows_the_router_order():
    vector = np.ones(3) / np.sqrt(3)
    keep = Model(Variant("x"), lambda v: False)
    assert decide(keep, _record(), vector) is False
    assert decide(keep, _record(router_abstention={"best_score": 0.7, "threshold": 0.8}), vector) is True
    assert decide(keep, _record(router_abstention={"best_score": None, "threshold": 0.8}), vector) is True
    refuse = Model(Variant("x"), lambda v: True)
    assert decide(refuse, _record(), vector) is True
    assert decide(refuse, _record(legal_citation=True), vector) is False
    # A calibrated pair reads the joint rule instead of the threshold.
    joint = Model(
        Variant("x"),
        lambda v: False,
        joint={("piaf", "fr"): JointGroup([0.1, 0.2], [0.9, 0.95], threshold=-1.0)},
        margin=lambda v: 0.0,
    )
    assert decide(joint, _record(), vector) is True
    thresholds = Model(Variant("x"), lambda v: False, thresholds={("piaf", "fr"): 0.9})
    assert decide(thresholds, _record(), vector) is True


def test_metrics_count_answers_refusals_and_paired_losses():
    report = {"records": [_record(), _record(hit=False), _record("out_of_scope"), _record("near_miss")]}
    before = [False, False, False, False]
    after = [True, False, True, False]
    result = metrics(report, after, before)
    assert (result["refusals_kept"], result["false_refusals"], result["answered"]) == (1, 1, 0)
    assert result["paired"]["piaf"] == {"gained": 0, "lost": 1, "p_value": 1.0}
    assert eligible(result) is False  # 50 % false refusals


def test_family_ignores_levels():
    a = Variant("a", "knn", "first_person", "all", 10, None, 0.02)
    b = Variant("b", "knn", "first_person", "all", 20, None, 0.03)
    assert family(a) == family(b) != family(Variant("c", "knn", "first_person", "first", 20))
