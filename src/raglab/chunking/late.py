from __future__ import annotations

from raglab.chunking.base import Chunker
from raglab.chunking.utils import estimate_tokens, find_next_start_index, sentence_spans
from raglab.domain.schemas import ChunkDraft


class LateChunker(Chunker):
    def chunk_text(self, text: str) -> list[ChunkDraft]:
        spans = sentence_spans(text)
        if not spans:
            return []

        context_chars = self.config.late_context_chars or 0
        chunks: list[ChunkDraft] = []
        start_idx = 0
        order = 0

        while start_idx < len(spans):
            focal_start = spans[start_idx][0]
            end_idx = start_idx
            while end_idx < len(spans) and spans[end_idx][1] - focal_start <= self.config.chunk_size:
                end_idx += 1
            if end_idx == start_idx:
                end_idx += 1

            focal_end = spans[end_idx - 1][1]
            focal_text = text[focal_start:focal_end].strip()
            context_start = max(0, focal_start - context_chars)
            context_end = min(len(text), focal_end + context_chars)
            embedding_text = text[context_start:context_end]
            relative_start = focal_start - context_start
            relative_end = focal_end - context_start

            if focal_text:
                chunks.append(
                    ChunkDraft(
                        strategy=self.config.strategy,
                        order=order,
                        text=focal_text,
                        char_start=focal_start,
                        char_end=focal_end,
                        token_estimate=estimate_tokens(focal_text),
                        metadata_json={
                            "context_start": context_start,
                            "context_end": context_end,
                            "late_context_chars": context_chars,
                        },
                        embedding_text=embedding_text,
                        embedding_span=(relative_start, relative_end),
                    )
                )
                order += 1

            if end_idx >= len(spans):
                break

            next_start_target = max(focal_start + 1, focal_end - self.config.chunk_overlap)
            start_idx = find_next_start_index(
                spans,
                current_start_index=start_idx,
                target_start_char=next_start_target,
            )

        return chunks
