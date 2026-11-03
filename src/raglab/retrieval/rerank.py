"""Cross-encoder re-ranking of the retrieved candidates (phase 9.3).

The first-stage retriever (dense, lexical or hybrid) returns
`rerank_candidates` chunks; a cross-encoder reads each (question, chunk) pair
and the `top_k` best are kept. The model (`BAAI/bge-reranker-v2-m3` by default)
is loaded once per configuration and shared between requests, like the
embedder. `release_rerankers()` frees its VRAM before a llama.cpp judge pass.

Scores are cached per (model, question, chunk id) in a bounded LRU: the
benchmark and the UI re-ask the same questions, and a chunk's text never
changes under a given id.
"""

from __future__ import annotations

import gc
import logging
from collections import OrderedDict
from collections.abc import Sequence
from threading import Lock
from typing import Any, Protocol

from raglab.config import Settings, get_settings
from raglab.domain.schemas import RetrievedChunk
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


class PairScorer(Protocol):
    """Scores (query, passage) pairs; higher means more relevant."""

    model_name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...

    def release(self) -> None: ...


class CrossEncoderScorer:
    """transformers cross-encoder, fp16 on CUDA, loaded on first use."""

    def __init__(self, settings: Settings):
        self.model_name = settings.rerank_model_name
        self.requested_device = settings.rerank_device
        self.batch_size = max(1, settings.rerank_batch_size)
        self.max_length = settings.rerank_max_length
        self.device = "cpu"
        self._tokenizer: Any = None
        self._model: Any = None
        # One forward pass at a time: the model is shared between requests
        # and concurrent batches on one GPU only add memory pressure.
        self._lock = Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        cuda = self.requested_device.startswith("cuda") and torch.cuda.is_available()
        self.device = self.requested_device if cuda else "cpu"
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        # Cast before moving so the GPU never holds the fp32 weights.
        model.to(dtype=torch.float16 if cuda else torch.float32)
        model.to(self.device)
        model.eval()
        self._model = model
        log_event(LOGGER, logging.INFO, "rerank.model_loaded", model=self.model_name, device=self.device)

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        import torch

        with self._lock:
            self._ensure_loaded()
            scores: list[float] = []
            for start in range(0, len(passages), self.batch_size):
                batch = list(passages[start : start + self.batch_size])
                encoded = self._tokenizer(
                    [query] * len(batch),
                    batch,
                    padding=True,
                    # longest_first trims the chunk, never a short question,
                    # and does not fail on an over-long one.
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                with torch.inference_mode():
                    logits = self._model(**encoded).logits.view(-1).float()
                scores.extend(logits.cpu().tolist())
            return scores

    def release(self) -> None:
        with self._lock:
            if self._model is None:
                return
            self._model = None
            self._tokenizer = None
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            log_event(LOGGER, logging.INFO, "rerank.model_released", model=self.model_name, device=self.device)


class RerankScoreCache:
    """LRU of cross-encoder scores keyed by (model, question, chunk id)."""

    def __init__(self, max_entries: int):
        self.max_entries = max(0, max_entries)
        self._entries: OrderedDict[tuple[str, str, str], float] = OrderedDict()
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[str, str, str]) -> float | None:
        with self._lock:
            score = self._entries.get(key)
            if score is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return score

    def put(self, key: tuple[str, str, str], score: float) -> None:
        if self.max_entries == 0:
            return
        with self._lock:
            self._entries[key] = score
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0


class Reranker:
    def __init__(self, scorer: PairScorer, cache: RerankScoreCache):
        self.scorer = scorer
        self.cache = cache

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> tuple[list[RetrievedChunk], dict[str, float]]:
        """Score every candidate, sort by cross-encoder score, keep top_k.

        `score` / `rank` become the cross-encoder's; the first-stage scores
        and ranks (dense, lexical, fused) stay on the chunk. Ties keep the
        first-stage order. Returns the chunks and this request's stats.
        """
        model = self.scorer.model_name
        scores: list[float | None] = []
        missing: list[int] = []
        for position, chunk in enumerate(chunks):
            cached = self.cache.get((model, question, chunk.chunk_id))
            scores.append(cached)
            if cached is None:
                missing.append(position)
        if missing:
            fresh = self.scorer.score(question, [chunks[position].chunk_text for position in missing])
            for position, score in zip(missing, fresh, strict=True):
                scores[position] = score
                self.cache.put((model, question, chunks[position].chunk_id), score)

        resolved = [score for score in scores if score is not None]
        if len(resolved) != len(chunks):
            raise ValueError("Le cross-encoder n'a pas renvoye un score par chunk")
        order = sorted(range(len(chunks)), key=lambda position: (-resolved[position], chunks[position].rank))
        reranked = [
            chunks[position].model_copy(
                update={
                    "score": resolved[position],
                    "rank": new_rank,
                    "rerank_score": resolved[position],
                    "rerank_rank": new_rank,
                }
            )
            for new_rank, position in enumerate(order[:top_k], start=1)
        ]
        hits = len(chunks) - len(missing)
        lookups = self.cache.hits + self.cache.misses
        stats = {
            "candidates": float(len(chunks)),
            "scored": float(len(missing)),
            "cache_hits": float(hits),
            "cache_hit_rate": round(hits / len(chunks), 4) if chunks else 0.0,
            "cache_size": float(len(self.cache)),
            "cache_hit_rate_total": round(self.cache.hits / lookups, 4) if lookups else 0.0,
        }
        return reranked, stats

    def release(self) -> None:
        self.scorer.release()


# One reranker per configuration, shared by every QueryService (the API builds
# one service per request). The score cache lives with it.
_RERANKERS: dict[tuple, Reranker] = {}
_RERANKERS_LOCK = Lock()


def _reranker_key(settings: Settings) -> tuple:
    return (
        settings.rerank_model_name,
        settings.rerank_device,
        settings.rerank_batch_size,
        settings.rerank_max_length,
        settings.rerank_cache_size,
    )


def get_reranker(settings: Settings | None = None) -> Reranker:
    resolved = settings or get_settings()
    key = _reranker_key(resolved)
    with _RERANKERS_LOCK:
        reranker = _RERANKERS.get(key)
        if reranker is None:
            reranker = Reranker(CrossEncoderScorer(resolved), RerankScoreCache(resolved.rerank_cache_size))
            _RERANKERS[key] = reranker
    return reranker


def release_rerankers() -> None:
    """Free the VRAM of every loaded cross-encoder; score caches are kept.

    Called before a llama.cpp judge pass. The next rerank reloads the model.
    """
    with _RERANKERS_LOCK:
        rerankers = list(_RERANKERS.values())
    for reranker in rerankers:
        reranker.release()


def clear_rerankers() -> None:
    release_rerankers()
    with _RERANKERS_LOCK:
        _RERANKERS.clear()
