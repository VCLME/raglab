"""Intent by nearest neighbours, and the joint abstention rule (docs/intentions.md).

The centroid classifier (`intent.py`) averages each intent's examples into
one vector per language. A question asking for a task or for personal data
("Combien font 17 % de 2 340 euros ?") then sits between the
`out_of_scope` and `documentary` centroids, within the 0.02 margin, and is
answered from whatever passages come back. Here the question is compared
with its k nearest labelled questions instead:

- documentary neighbours: the documentary examples plus the calibration
  questions of each corpus (`corpus_examples.jsonl`, disjoint from every
  evaluated set), i.e. what in-scope questions actually look like;
- other neighbours: the conversational and out-of-scope examples
  (`examples.py`, extended set).

`documentary_margin` = mean similarity of the k nearest documentary
neighbours minus that of the k nearest others. below `-margin` (0.02, as
for the centroids) the question is declined on intent. A small logistic
regression on the same embedding (trained on the same labelled questions,
weights in the calibration file) is a second intent signal: the question is
also declined when its probability of not being documentary passes a cut
set on the calibration questions.

That gate alone declines no more than the centroids: what helps is reading
it **with** the retrieval score. A question slightly short on both (a little
less documentary than the calibration questions, a slightly lower dense
score) is declined, where two independent gates each let it through. For
each (corpus, question language) with calibration questions, both signals
are turned into their rank among those questions (empirical CDF) and the
log ranks are added; the question is declined when that joint score falls
below the score the calibration questions reach at a fixed quantile. The
calibration (`intent_calibration.json`) is written offline by
`raglab experiment routing-languages --replay ... --intent`, from in-scope
calibration questions only. No LLM: dot products with a few hundred vectors.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from raglab.routing.corpus_examples import load_corpus_examples
from raglab.routing.examples import iter_examples
from raglab.routing.intent import normalize
from raglab.routing.schemas import Intent, IntentDecision

DEFAULT_K = 20


@dataclass(frozen=True)
class LogisticIntent:
    """Logistic regression on the question embedding: P(not documentary)."""

    weights: np.ndarray
    bias: float
    scale: float
    # Declined above this probability (a quantile of the calibration questions).
    threshold: float

    def probability(self, embedding: np.ndarray) -> float:
        return float(1 / (1 + np.exp(-(self.scale * float(embedding @ self.weights) + self.bias))))


def fit_logistic(
    x: np.ndarray, y: np.ndarray, *, l2: float = 1.0, scale: float = 20.0, steps: int = 3000
) -> tuple[np.ndarray, float]:
    """L2 logistic regression by gradient descent, classes balanced (numpy only).
    `y` = 1 for not documentary. Returns (weights, bias) on `scale * x`."""
    x = x * scale
    balance = np.where(y > 0, 0.5 / y.mean(), 0.5 / (1 - y.mean()))
    weights = np.zeros(x.shape[1])
    bias = 0.0
    for _ in range(steps):
        gradient = (1 / (1 + np.exp(-(x @ weights + bias))) - y) * balance
        weights -= 0.5 * (x.T @ gradient / len(y) + l2 * weights / len(y))
        bias -= 0.5 * float(gradient.mean())
    return weights, bias


class KnnIntentClassifier:
    def __init__(
        self,
        embedder: Any,
        *,
        k: int = DEFAULT_K,
        examples: list[tuple[str, str, str]] | None = None,
        documentary_questions: list[str] | None = None,
    ):
        rows = list(examples if examples is not None else iter_examples(extended=True))
        rows += [(Intent.DOCUMENTARY.value, "", text) for text in documentary_questions or []]
        self.k = k
        self.texts = [text for _, _, text in rows]
        self.intents = np.array([intent for intent, _, _ in rows])
        self.matrix = np.stack([normalize(embedder.embed_query(text)) for text in self.texts])

    def scores(self, embedding: np.ndarray, *, exclude: str | None = None) -> dict[str, float]:
        """Mean similarity of the k nearest neighbours of each intent, and of
        all non-documentary ones (`other`). `exclude`: a text left out of the
        neighbours (a calibration question scored against the others)."""
        similarities = self.matrix @ embedding
        keep = np.ones(len(self.texts), dtype=bool)
        if exclude is not None:
            keep &= np.array([text != exclude for text in self.texts])

        def top(mask: np.ndarray) -> float:
            values = similarities[mask & keep]
            return float(np.sort(values)[-self.k :].mean()) if values.size else -1.0

        documentary = self.intents == Intent.DOCUMENTARY.value
        return {
            Intent.DOCUMENTARY.value: round(top(documentary), 4),
            Intent.CONVERSATIONAL.value: round(top(self.intents == Intent.CONVERSATIONAL.value), 4),
            Intent.OUT_OF_SCOPE.value: round(top(self.intents == Intent.OUT_OF_SCOPE.value), 4),
            "other": round(top(~documentary), 4),
        }

    def documentary_margin(self, embedding: np.ndarray, *, exclude: str | None = None) -> float:
        scores = self.scores(embedding, exclude=exclude)
        return round(scores[Intent.DOCUMENTARY.value] - scores["other"], 4)

    def classify(
        self, embedding: np.ndarray, *, margin: float, logistic: LogisticIntent | None = None
    ) -> IntentDecision:
        scores = self.scores(embedding)
        documentary_margin = round(scores[Intent.DOCUMENTARY.value] - scores.pop("other"), 4)
        probability = round(logistic.probability(embedding), 4) if logistic is not None else None
        intent = Intent.DOCUMENTARY
        if documentary_margin < -margin or (
            logistic is not None and probability is not None and probability > logistic.threshold
        ):
            intent = (
                Intent.CONVERSATIONAL
                if scores[Intent.CONVERSATIONAL.value] > scores[Intent.OUT_OF_SCOPE.value]
                else Intent.OUT_OF_SCOPE
            )
        return IntentDecision(
            intent=intent,
            scores=scores,
            margin=margin,
            nearest_example=self.texts[int(np.argmax(self.matrix @ embedding))],
            method="knn",
            documentary_margin=documentary_margin,
            not_documentary_probability=probability,
        )


# ---------------------------------------------------------------- joint rule


@dataclass(frozen=True)
class JointGroup:
    """Calibration of one (corpus, question language)."""

    # Sorted documentary margins and dense scores of its calibration questions.
    margins: list[float]
    dense: list[float]
    # Joint score of the calibration questions at the chosen quantile.
    threshold: float


def _rank(values: list[float], value: float) -> float:
    """Empirical CDF, kept inside (0, 1) so its log is finite."""
    return (bisect_right(values, value) + 1) / (len(values) + 2)


def joint_score(group: JointGroup, documentary_margin: float, dense: float) -> float:
    """Sum of the log ranks of both signals among the calibration questions."""
    return round(math.log(_rank(group.margins, documentary_margin)) + math.log(_rank(group.dense, dense)), 4)


@dataclass(frozen=True)
class JointCalibration:
    k: int
    quantile: float
    groups: dict[str, dict[str, JointGroup]]
    logistic: LogisticIntent | None = None

    def group(self, corpus_name: str | None, language: str | None) -> JointGroup | None:
        return (self.groups.get(corpus_name or "") or {}).get(language or "")


def build_joint_calibration(
    rows: list[tuple[str, str, float, float]],
    *,
    k: int,
    quantile: float,
    rank_quantile: Any,
    logistic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-ready calibration from (corpus, language, documentary margin,
    dense score) rows of in-scope calibration questions. `rank_quantile`
    (values, fraction) -> value is the study's quantile rule. `logistic`:
    weights, bias, scale, threshold (and the quantile it came from)."""
    grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for corpus, language, margin, score in rows:
        grouped.setdefault((corpus, language), []).append((margin, score))
    groups: dict[str, dict[str, Any]] = {}
    for (corpus, language), values in sorted(grouped.items()):
        margins = sorted(margin for margin, _ in values)
        scores = sorted(score for _, score in values)
        group = JointGroup(margins, scores, 0.0)
        joint = [joint_score(group, margin, score) for margin, score in values]
        groups.setdefault(corpus, {})[language] = {
            "questions": len(values),
            "threshold": round(rank_quantile(joint, quantile), 4),
            "margins": [round(v, 4) for v in margins],
            "dense": [round(v, 4) for v in scores],
        }
    payload: dict[str, Any] = {"k": k, "quantile": quantile, "score": "dense", "groups": groups}
    if logistic is not None:
        payload["logistic"] = logistic
    return payload


def parse_joint_calibration(payload: dict[str, Any]) -> JointCalibration:
    logistic = payload.get("logistic")
    return JointCalibration(
        k=int(payload["k"]),
        quantile=float(payload["quantile"]),
        groups={
            corpus: {
                language: JointGroup(list(group["margins"]), list(group["dense"]), float(group["threshold"]))
                for language, group in by_language.items()
            }
            for corpus, by_language in payload["groups"].items()
        },
        logistic=(
            LogisticIntent(
                weights=np.asarray(logistic["weights"], dtype=np.float32),
                bias=float(logistic["bias"]),
                scale=float(logistic["scale"]),
                threshold=float(logistic["threshold"]),
            )
            if logistic
            else None
        ),
    )


# ---------------------------------------------------------------- caches

_CLASSIFIERS: dict[tuple[str, float, int, int], tuple[Any, KnnIntentClassifier]] = {}
_CALIBRATIONS: dict[tuple[str, float], JointCalibration | None] = {}
_LOCK = Lock()


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.is_file() else 0.0


def load_joint_calibration(path: Path) -> JointCalibration | None:
    """None when the file is absent: the router then keeps the plain thresholds."""
    key = (str(path.resolve()), _mtime(path))
    with _LOCK:
        if key in _CALIBRATIONS:
            return _CALIBRATIONS[key]
    calibration = parse_joint_calibration(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else None
    with _LOCK:
        _CALIBRATIONS[key] = calibration
    return calibration


def documentary_questions(path: Path) -> list[str]:
    """Calibration questions of every corpus and language, in file order."""
    return [
        question
        for by_language in load_corpus_examples(path).values()
        for questions in by_language.values()
        for question in questions
    ]


def get_knn_intent_classifier(embedder: Any, questions_path: Path, k: int = DEFAULT_K) -> KnnIntentClassifier:
    """Embed the neighbours once per (questions file, embedder, k)."""
    key = (str(questions_path.resolve()), _mtime(questions_path), id(embedder), k)
    with _LOCK:
        cached = _CLASSIFIERS.get(key)
    # Keep a reference to the embedder: a recycled id() must not match.
    if cached is not None and cached[0] is embedder:
        return cached[1]
    classifier = KnnIntentClassifier(embedder, k=k, documentary_questions=documentary_questions(questions_path))
    with _LOCK:
        _CLASSIFIERS[key] = (embedder, classifier)
    return classifier


def clear_knn_cache() -> None:
    with _LOCK:
        _CLASSIFIERS.clear()
        _CALIBRATIONS.clear()
