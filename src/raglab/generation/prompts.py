from __future__ import annotations

import textwrap
from dataclasses import dataclass

from raglab.domain.schemas import RetrievedChunk
from raglab.domain.versions import prompt_line, strip_revoked


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
        # Version state of the passage (versions option, phase 9.10): the
        # model is told which article version it reads, and does not read
        # the wording of provisions marked repealed.
        status = prompt_line(chunk.version)
        text = chunk.chunk_text
        version = chunk.version
        if version is not None and version.in_prompt and version.source == "markers" and version.revoked_lines:
            text = strip_revoked(text)
        blocks.append(
            "\n".join(
                [
                    f"[Source rank={chunk.rank}]",
                    f"Fichier: {chunk.file_name}",
                    f"Chemin: {chunk.source_path}",
                    f"Score: {chunk.score:.4f}",
                    *([status] if status else []),
                    "Extrait:",
                    text,
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
        Quand un extrait porte un « Statut », tiens-en compte : appuie-toi sur
        la version en vigueur et, si tu cites une version abrogée ou ancienne,
        dis-le avec sa date.
        Quand tu affirmes un fait issu du contexte, cite-le inline en placant
        [Rank X] immédiatement après l'affirmation (X = le rank du chunk utilisé).
        N'ajoute jamais de ligne `Sources:` séparée à la fin : les citations inline suffisent.
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
        3. Citer les sources inline avec [Rank X] juste après chaque fait cité. Pas de section `Sources:` finale.
        """
    ).strip()
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
