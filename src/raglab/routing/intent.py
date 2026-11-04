"""Intent by nearest centroid of small labelled example sets."""

from __future__ import annotations

from threading import Lock
from typing import Any

import numpy as np

from raglab.routing.examples import iter_examples
from raglab.routing.schemas import Intent, IntentDecision


def normalize(vector: Any) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    return array / norm if norm > 0 else array


class IntentClassifier:
    """One centroid per (intent, language) built from `examples.py`.

    An intent scores the cosine similarity to its closest centroid (French or
    Portuguese), so a question is not penalised for being in the language
    with fewer examples. `documentary` wins unless another intent beats it by
    more than `margin`: a wrong refusal costs more than a useless retrieval,
    which the score-based abstention can still catch.
    """

    def __init__(self, embedder: Any, examples: list[tuple[str, str, str]] | None = None):
        rows = examples if examples is not None else list(iter_examples())
        self.texts = [text for _, _, text in rows]
        self.intents = [intent for intent, _, _ in rows]
        self.languages = [language for _, language, _ in rows]
        self.matrix = np.stack([normalize(embedder.embed_query(text)) for text in self.texts])
        self.centroids: dict[tuple[str, str], np.ndarray] = {}
        for key in sorted(set(zip(self.intents, self.languages, strict=True))):
            members = [i for i, pair in enumerate(zip(self.intents, self.languages, strict=True)) if pair == key]
            self.centroids[key] = normalize(self.matrix[members].mean(axis=0))

    def intent_scores(self, embedding: np.ndarray) -> dict[str, float]:
        scores: dict[str, float] = {}
        for (intent, _language), centroid in self.centroids.items():
            value = float(centroid @ embedding)
            scores[intent] = max(scores.get(intent, -1.0), value)
        return {intent: round(value, 4) for intent, value in scores.items()}

    def language_similarities(self, embedding: np.ndarray) -> dict[str, float]:
        """Similarity to the nearest example of each language."""
        similarities = self.matrix @ embedding
        best: dict[str, float] = {}
        for language, value in zip(self.languages, similarities, strict=True):
            best[language] = max(best.get(language, -1.0), float(value))
        return best

    def classify(self, embedding: np.ndarray, *, margin: float) -> IntentDecision:
        scores = self.intent_scores(embedding)
        return IntentDecision(
            intent=decide_intent(scores, margin=margin),
            scores=scores,
            margin=margin,
            nearest_example=self.texts[int(np.argmax(self.matrix @ embedding))],
        )


def decide_intent(scores: dict[str, float], *, margin: float) -> Intent:
    documentary = scores.get(Intent.DOCUMENTARY.value, -1.0)
    others = {key: value for key, value in scores.items() if key != Intent.DOCUMENTARY.value}
    if not others:
        return Intent.DOCUMENTARY
    best = max(others, key=lambda key: others[key])
    if others[best] - documentary > margin:
        return Intent(best)
    return Intent.DOCUMENTARY


_CLASSIFIERS: dict[int, tuple[Any, IntentClassifier]] = {}
_LOCK = Lock()


def get_intent_classifier(embedder: Any) -> IntentClassifier:
    """Embed the examples once per embedder (the factory caches embedders)."""
    with _LOCK:
        cached = _CLASSIFIERS.get(id(embedder))
        # Keep a reference to the embedder: a recycled id() must not match.
        if cached is None or cached[0] is not embedder:
            cached = (embedder, IntentClassifier(embedder))
            _CLASSIFIERS[id(embedder)] = cached
    return cached[1]


def clear_intent_cache() -> None:
    with _LOCK:
        _CLASSIFIERS.clear()
