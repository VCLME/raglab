from __future__ import annotations

import textwrap

import requests

from raglab.config import Settings, get_settings
from raglab.domain.schemas import RetrievedChunk


class OllamaGenerator:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        blocks: list[str] = []
        for chunk in chunks:
            blocks.append(
                "\n".join(
                    [
                        f"[Rank {chunk.rank}] {chunk.file_name}",
                        f"Score: {chunk.score:.4f}",
                        chunk.chunk_text,
                    ]
                )
            )
        return "\n\n".join(blocks)

    def generate_answer(self, question: str, chunks: list[RetrievedChunk]) -> str:
        context = self._build_context(chunks)
        messages = [
            {
                "role": "system",
                "content": textwrap.dedent(
                    """
                    Tu es un assistant RAG local.
                    Reponds uniquement a partir du contexte fourni.
                    Si l'information manque dans le contexte, dis-le explicitement.
                    Cite les fichiers quand c'est utile.
                    """
                ).strip(),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nContexte:\n{context}",
            },
        ]

        response = requests.post(
            f"{self.settings.ollama_base_url}/api/chat",
            json={
                "model": self.settings.generation_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.settings.generation_temperature},
            },
            timeout=self.settings.generation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["message"]["content"].strip()
