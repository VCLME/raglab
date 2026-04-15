from __future__ import annotations

from raglab.chunking.base import Chunker
from raglab.chunking.utils import estimate_tokens, find_next_start_index, sentence_spans
from raglab.domain.schemas import ChunkDraft


class TraditionalChunker(Chunker):
    def chunk_text(self, text: str) -> list[ChunkDraft]:
        spans = sentence_spans(text)
        if not spans:
            return []

        chunks: list[ChunkDraft] = []
        start_idx = 0
        order = 0

        while start_idx < len(spans):
            chunk_start = spans[start_idx][0]
            end_idx = start_idx
            while end_idx < len(spans) and spans[end_idx][1] - chunk_start <= self.config.chunk_size:
                end_idx += 1
            if end_idx == start_idx:
                end_idx += 1

            chunk_end = spans[end_idx - 1][1]
            chunk_text = text[chunk_start:chunk_end].strip()
            if chunk_text:
                chunks.append(
                    ChunkDraft(
                        strategy=self.config.strategy,
                        order=order,
                        text=chunk_text,
                        char_start=chunk_start,
                        char_end=chunk_end,
                        token_estimate=estimate_tokens(chunk_text),
                        metadata_json={"overlap_chars": self.config.chunk_overlap},
                    )
                )
                order += 1

            if end_idx >= len(spans):
                break

            next_start_target = max(chunk_start + 1, chunk_end - self.config.chunk_overlap)
            start_idx = find_next_start_index(
                spans,
                current_start_index=start_idx,
                target_start_char=next_start_target,
            )

        return chunks
