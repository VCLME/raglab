"""Corpus choice on example questions (docs/routage-multilingue.md).

A corpus's passage centroid mixes what the corpus is about with the language
it is written in: with multilingual-e5-small, a French question about a
Brazilian law is closer to a French encyclopedia's centroid than to the
Portuguese laws holding its answer. Example questions written in each
language give one centroid per (corpus, language); a corpus scores the
similarity of its closest language centroid, so a question is compared with
questions in its own language about each corpus. Question to question, no
LLM: the examples are written offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from raglab.routing.intent import normalize

# Centroids per (examples file, mtime, embedder): computed once per process.
_CACHE: dict[tuple[str, float, int], dict[str, dict[str, np.ndarray]]] = {}
_LOCK = Lock()


def load_corpus_examples(path: Path) -> dict[str, dict[str, list[str]]]:
    """corpus -> language -> questions. An absent file means no examples."""
    examples: dict[str, dict[str, list[str]]] = {}
    if not path.is_file():
        return examples
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            examples.setdefault(row["corpus"], {}).setdefault(row["language"], []).append(row["question"])
    return examples


def example_centroids(examples: dict[str, dict[str, list[str]]], embedder: Any) -> dict[str, dict[str, np.ndarray]]:
    return {
        corpus: {
            language: normalize(np.stack([normalize(embedder.embed_query(q)) for q in questions]).mean(axis=0))
            for language, questions in by_language.items()
            if questions
        }
        for corpus, by_language in examples.items()
    }


def get_example_centroids(path: Path, embedder: Any) -> dict[str, dict[str, np.ndarray]]:
    key = (str(path.resolve()), path.stat().st_mtime if path.is_file() else 0.0, id(embedder))
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    centroids = example_centroids(load_corpus_examples(path), embedder)
    with _LOCK:
        _CACHE[key] = centroids
    return centroids


def clear_example_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def example_score(centroids: dict[str, np.ndarray], embedding: np.ndarray) -> float:
    """Similarity to the closest language centroid of one corpus."""
    return round(max(float(centroid @ embedding) for centroid in centroids.values()), 4)
