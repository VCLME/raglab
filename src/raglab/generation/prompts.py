from __future__ import annotations

import textwrap
from dataclasses import dataclass

from raglab.domain.schemas import RetrievedChunk


@dataclass(slots=True)
class PromptBundle:
    system_prompt: str
    user_prompt: str

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_prompt},
        ]


def build_context(chunks: list[RetrievedChunk]) -> str:
    blocks: list[str] = []
    for chunk in chunks:
        blocks.append(
            "\n".join(
                [
                    f"[Source rank={chunk.rank}]",
                    f"Fichier: {chunk.file_name}",
                    f"Chemin: {chunk.source_path}",
                    f"Score: {chunk.score:.4f}",
                    "Extrait:",
                    chunk.chunk_text,
                ]
            )
        )
    return "\n\n".join(blocks)


def build_prompt_bundle(question: str, chunks: list[RetrievedChunk], *, no_context_answer: str) -> PromptBundle:
    system_prompt = textwrap.dedent(
        f"""
        Tu es un assistant RAG local.
        Réponds uniquement à partir du contexte fourni.
        N'invente aucun fait, aucune date, aucun article, aucune référence juridique ou métier.
        Si le contexte est insuffisant, réponds exactement :
        "{no_context_answer}"
        Si plusieurs sources se contredisent, signale l'incertitude.
        Quand tu réponds, cite les sources utiles à la fin sous la forme :
        Sources: [Rank X] nom_fichier
        Garde une réponse concise, factuelle et directement exploitable.
        """
    ).strip()

    context = build_context(chunks)
    user_prompt = textwrap.dedent(
        f"""
        Question:
        {question}

        Contexte:
        {context}

        Consigne de sortie:
        1. Répondre en t'appuyant uniquement sur le contexte.
        2. Si l'information manque, utiliser exactement la phrase de fallback.
        3. Ajouter une ligne `Sources:` uniquement si au moins une source a été réellement utilisée.
        """
    ).strip()
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
