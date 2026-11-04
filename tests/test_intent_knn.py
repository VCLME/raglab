from __future__ import annotations

import json

import numpy as np
import pytest

from raglab.experiments.routing import ABSTENTION_PATH, quantile
from raglab.routing.examples import iter_examples
from raglab.routing.intent import normalize
from raglab.routing.intent_knn import (
    JointGroup,
    KnnIntentClassifier,
    build_joint_calibration,
    clear_knn_cache,
    documentary_questions,
    get_knn_intent_classifier,
    joint_score,
    load_joint_calibration,
    parse_joint_calibration,
)
from raglab.routing.schemas import Intent

# One axis per theme, as in test_routing.py.
AXES = {"loi": 0, "lei": 0, "bonjour": 1, "olá": 1, "météo": 2, "pedido": 2, "musée": 3}


class FakeEmbedder:
    def __init__(self):
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        vector = np.full(5, 0.01, dtype=np.float32)
        for word in text.lower().replace("?", " ").split():
            if word in AXES:
                vector[AXES[word]] += 1.0
        return (vector / np.linalg.norm(vector)).tolist()


EXAMPLES = [
    ("documentary", "fr", "que dit la loi"),
    ("conversational", "fr", "bonjour"),
    ("conversational", "pt", "olá"),
    ("out_of_scope", "fr", "météo de demain"),
    ("out_of_scope", "pt", "meu pedido"),
]


@pytest.fixture(autouse=True)
def _clear():
    clear_knn_cache()
    yield
    clear_knn_cache()


def _embed(text: str) -> np.ndarray:
    return normalize(FakeEmbedder().embed_query(text))


def test_knn_intent_reads_the_nearest_labelled_questions():
    classifier = KnnIntentClassifier(FakeEmbedder(), k=1, examples=EXAMPLES, documentary_questions=["quel musée"])
    documentary = classifier.classify(_embed("que dit la lei"), margin=0.02)
    assert documentary.intent == Intent.DOCUMENTARY
    assert documentary.method == "knn"
    assert documentary.documentary_margin is not None and documentary.documentary_margin > 0.02
    # A calibration question counts as a documentary neighbour.
    assert classifier.classify(_embed("musée"), margin=0.02).intent == Intent.DOCUMENTARY
    assert classifier.classify(_embed("météo"), margin=0.02).intent == Intent.OUT_OF_SCOPE
    greeting = classifier.classify(_embed("bonjour"), margin=0.02)
    assert greeting.intent == Intent.CONVERSATIONAL
    assert greeting.nearest_example == "bonjour"
    assert set(greeting.scores) == {"documentary", "conversational", "out_of_scope"}


def test_knn_intent_keeps_documentary_within_the_margin():
    classifier = KnnIntentClassifier(FakeEmbedder(), k=1, examples=EXAMPLES)
    # Equally close to a documentary and an out-of-scope example.
    vector = normalize(np.array([1.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32))
    assert abs(classifier.documentary_margin(vector)) < 0.02
    assert classifier.classify(vector, margin=0.02).intent == Intent.DOCUMENTARY
    assert classifier.classify(vector, margin=-0.5).intent != Intent.DOCUMENTARY


def test_knn_scores_can_leave_a_calibration_question_out():
    classifier = KnnIntentClassifier(FakeEmbedder(), k=1, examples=EXAMPLES, documentary_questions=["quel musée"])
    vector = _embed("quel musée")
    assert classifier.scores(vector)["documentary"] == pytest.approx(1.0, abs=1e-3)
    assert classifier.scores(vector, exclude="quel musée")["documentary"] < 0.5


def test_joint_score_adds_the_log_ranks_of_both_signals():
    group = JointGroup(margins=[0.0, 0.1, 0.2], dense=[0.80, 0.85, 0.90], threshold=-3.0)
    # Above every calibration value: rank 4/5 on both.
    assert joint_score(group, 0.3, 0.95) == pytest.approx(2 * np.log(4 / 5), abs=1e-4)
    # Below every value: rank 1/5 on both, far under the threshold.
    assert joint_score(group, -0.1, 0.7) == pytest.approx(2 * np.log(1 / 5), abs=1e-4)
    # Low on one signal only stays above a question low on both.
    assert joint_score(group, -0.1, 0.95) > joint_score(group, -0.1, 0.7)


def test_joint_calibration_round_trips_through_json(tmp_path):
    rows = [("bench_a", "fr", 0.01 * i, 0.80 + 0.001 * i) for i in range(50)] + [("bench_a", "pt", 0.05, 0.9)] * 5
    payload = build_joint_calibration(rows, k=20, quantile=0.02, rank_quantile=quantile)
    group = payload["groups"]["bench_a"]["fr"]
    assert group["questions"] == 50
    assert group["margins"] == sorted(group["margins"])
    path = tmp_path / "intent_calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    calibration = load_joint_calibration(path)
    assert calibration is not None and calibration.k == 20
    assert calibration.group("bench_a", "fr") == parse_joint_calibration(payload).group("bench_a", "fr")
    assert calibration.group("bench_a", "en") is None
    assert calibration.group(None, "fr") is None
    # About `quantile` of the calibration questions fall under their threshold.
    fr = calibration.group("bench_a", "fr")
    assert fr is not None
    below = sum(
        joint_score(fr, margin, dense) < fr.threshold for _, language, margin, dense in rows if language == "fr"
    )
    assert below <= 1
    assert load_joint_calibration(tmp_path / "absent.json") is None


def test_knn_classifier_is_cached_per_embedder_and_file(tmp_path):
    path = tmp_path / "corpus_examples.jsonl"
    path.write_text(
        json.dumps({"corpus": "bench_a", "language": "fr", "question": "quel musée"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert documentary_questions(path) == ["quel musée"]
    embedder = FakeEmbedder()
    first = get_knn_intent_classifier(embedder, path)
    calls = len(embedder.calls)
    assert get_knn_intent_classifier(embedder, path) is first
    assert len(embedder.calls) == calls
    assert "quel musée" in first.texts


def test_extended_examples_stay_out_of_the_frozen_evaluation_sets():
    frozen = {json.loads(line)["question"].strip().lower() for line in ABSTENTION_PATH.read_text("utf-8").splitlines()}
    for path in ("benchmarks/piaf/ground_truth.jsonl", "benchmarks/lexml_fulltext/ground_truth.jsonl"):
        full = ABSTENTION_PATH.parents[2] / path
        frozen |= {json.loads(line)["question"].strip().lower() for line in full.read_text("utf-8").splitlines()}
    examples = [text.strip().lower() for _, _, text in iter_examples(extended=True)]
    assert len(examples) == len(set(examples))
    assert not frozen & set(examples)
    assert len(examples) > len(list(iter_examples()))


def test_logistic_signal_declines_on_its_own():
    from raglab.routing.intent_knn import LogisticIntent, fit_logistic

    x = np.stack([_embed(text) for text in ("que dit la loi", "quel musée", "météo de demain", "meu pedido")])
    weights, bias = fit_logistic(x, np.array([0.0, 0.0, 1.0, 1.0]), steps=500)
    logistic = LogisticIntent(np.asarray(weights), bias, 20.0, threshold=0.5)
    assert logistic.probability(_embed("météo")) > 0.5 > logistic.probability(_embed("loi"))
    # Margin gate disabled (documentary examples only): the logistic cut decides.
    classifier = KnnIntentClassifier(FakeEmbedder(), k=1, examples=[EXAMPLES[0], EXAMPLES[3]])
    decision = classifier.classify(_embed("météo"), margin=1.0, logistic=logistic)
    assert decision.intent == Intent.OUT_OF_SCOPE
    assert decision.not_documentary_probability is not None and decision.not_documentary_probability > 0.5
    assert classifier.classify(_embed("météo"), margin=1.0).intent == Intent.DOCUMENTARY


def test_joint_decision_replaces_the_score_threshold():
    from raglab.routing.abstention import decide_abstention

    low = decide_abstention(
        intent=Intent.DOCUMENTARY, score=0.95, threshold=0.8, score_source="dense", joint=(-6.0, -5.0)
    )
    assert low.abstain and low.reason == "low_joint_score"
    assert (low.joint_score, low.joint_threshold) == (-6.0, -5.0)
    kept = decide_abstention(
        intent=Intent.DOCUMENTARY, score=0.70, threshold=0.8, score_source="dense", joint=(-1.0, -5.0)
    )
    assert not kept.abstain
    # Intent and legal citations still come first.
    assert (
        decide_abstention(
            intent=Intent.OUT_OF_SCOPE, score=0.9, threshold=0.8, score_source="dense", joint=(-1.0, -5.0)
        ).reason
        == "intent:out_of_scope"
    )
    assert not decide_abstention(
        intent=Intent.DOCUMENTARY,
        score=0.9,
        threshold=0.8,
        score_source="dense",
        joint=(-9.0, -5.0),
        legal_citation=True,
    ).abstain
