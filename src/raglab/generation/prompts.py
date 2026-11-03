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


# The fallback sentence in the other benchmark languages. With a French-only
# sentence, qwen2.5 answered Portuguese questions in French, garbled the
# sentence, and refused 20 of 100 LexML questions, 11 with the answer in the
# context (full-v1).
NO_CONTEXT_ANSWERS = {
    "portugais": "Não posso responder com segurança com o contexto recuperado.",
    "anglais": "I cannot answer reliably from the retrieved context.",
}


def build_prompt_bundle(question: str, chunks: list[RetrievedChunk], *, no_context_answer: str) -> PromptBundle:
    fallbacks = "\n".join(
        f'        - {language} : "{answer}"'
        for language, answer in [("français", no_context_answer), *NO_CONTEXT_ANSWERS.items()]
    )
    system_prompt = textwrap.dedent(
        f"""
        Tu es un assistant RAG local.
        Réponds uniquement à partir du contexte fourni, dans la langue de la question.
        N'invente aucun fait, aucune date, aucun article, aucune référence juridique ou métier.
        Si le contexte répond en partie, donne ce qu'il contient et précise ce qui manque.
        Si le contexte ne contient pas du tout l'information demandée, réponds exactement
        par la phrase de la langue de la question :
{fallbacks}
        Si plusieurs sources se contredisent, signale l'incertitude.
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
        2. Répondre dans la langue de la question ; si l'information manque entièrement, utiliser exactement la phrase de fallback de cette langue.
        3. Citer les sources inline avec [Rank X] juste après chaque fait cité. Pas de section `Sources:` finale.
        """
    ).strip()
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
