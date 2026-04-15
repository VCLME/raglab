from __future__ import annotations

from collections.abc import Sequence

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from raglab.config import Settings
from raglab.domain.schemas import ChunkDraft


class TransformersEmbeddingProvider:
    provider_name = "transformers"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model_name = settings.embedding_model_name
        self.dimension = settings.embedding_dimension
        self.device = self._resolve_device(settings.embedding_device)
        self._tokenizer = None
        self._model = None

    def _resolve_device(self, requested: str) -> str:
        if requested.startswith("cuda") and torch.cuda.is_available():
            return requested
        return "cpu"

    def _ensure_loaded(self) -> None:
        if self._tokenizer is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        if self._model is None:
            self._model = AutoModel.from_pretrained(self.model_name)
            self._model.to(self.device)
            self._model.eval()

    def _mean_pool(self, last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        masked = last_hidden_state * attention_mask.unsqueeze(-1)
        summed = masked.sum(dim=1)
        counts = attention_mask.sum(dim=1).clamp(min=1).unsqueeze(-1)
        return summed / counts

    def _encode_batch(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.settings.embedding_max_tokens,
            return_tensors="pt",
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        with torch.inference_mode():
            outputs = self._model(**encoded)
            pooled = self._mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
            pooled = F.normalize(pooled, p=2, dim=1)
        return pooled.cpu().tolist()

    def _embed_contextual_span(self, embedding_text: str, span: tuple[int, int]) -> list[float]:
        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None

        prefixed_text = f"{self.settings.passage_prefix}{embedding_text}"
        span_start = span[0] + len(self.settings.passage_prefix)
        span_end = span[1] + len(self.settings.passage_prefix)

        encoded = self._tokenizer(
            prefixed_text,
            truncation=True,
            max_length=self.settings.embedding_max_tokens,
            return_offsets_mapping=True,
            return_tensors="pt",
        )
        offset_mapping = encoded.pop("offset_mapping")[0].tolist()
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        selected_positions: list[int] = []
        for idx, (start, end) in enumerate(offset_mapping):
            if start == end == 0:
                continue
            if end > span_start and start < span_end:
                selected_positions.append(idx)

        with torch.inference_mode():
            outputs = self._model(**encoded)
            hidden = outputs.last_hidden_state[0]
            if selected_positions:
                pooled = hidden[selected_positions].mean(dim=0)
            else:
                pooled = self._mean_pool(outputs.last_hidden_state, encoded["attention_mask"])[0]
            pooled = F.normalize(pooled, p=2, dim=0)
        return pooled.cpu().tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._encode_batch([f"{self.settings.query_prefix}{text}"])[0]

    def embed_chunks(self, chunks: Sequence[ChunkDraft]) -> list[list[float]]:
        regular_texts: list[str] = []
        regular_positions: list[int] = []
        vectors: list[list[float] | None] = [None] * len(chunks)

        for index, chunk in enumerate(chunks):
            if chunk.embedding_span is not None and chunk.embedding_text:
                vectors[index] = self._embed_contextual_span(chunk.embedding_text, chunk.embedding_span)
            else:
                regular_texts.append(f"{self.settings.passage_prefix}{chunk.embedding_text or chunk.text}")
                regular_positions.append(index)

        if regular_texts:
            regular_vectors = self._encode_batch(regular_texts)
            for position, vector in zip(regular_positions, regular_vectors, strict=True):
                vectors[position] = vector

        if any(vector is None for vector in vectors):
            raise ValueError("Au moins un chunk n'a pas recu de vecteur d'embedding")
        return [vector for vector in vectors if vector is not None]
