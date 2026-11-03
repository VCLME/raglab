from __future__ import annotations

import re
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


# Frequent function words, enough to tell the benchmark languages apart in a
# question. The prompt is written in the question's language: with a French
# prompt, qwen2.5:7b answered 29 of 100 Portuguese questions in French.
_LANGUAGE_WORDS = {
    "fr": {
        "le",
        "la",
        "les",
        "des",
        "du",
        "est",
        "une",
        "un",
        "que",
        "qui",
        "pour",
        "quel",
        "quelle",
        "quels",
        "dans",
        "sur",
        "au",
        "aux",
        "peut",
        "ce",
        "pourquoi",
        "comment",
        "il",
        "elle",
        "et",
    },
    "pt": {
        "o",
        "os",
        "da",
        "do",
        "das",
        "dos",
        "que",
        "não",
        "é",
        "uma",
        "um",
        "para",
        "com",
        "qual",
        "quais",
        "no",
        "na",
        "pela",
        "pelo",
        "dispõe",
        "são",
        "quem",
        "deve",
        "ser",
        "nos",
        "em",
        "pode",
        "conforme",
        "seu",
        "sua",
    },
    "en": {
        "the",
        "what",
        "which",
        "is",
        "are",
        "of",
        "does",
        "do",
        "for",
        "how",
        "can",
        "who",
        "when",
        "under",
        "must",
        "should",
        "why",
    },
}

# The fallback sentence per language; French comes from the settings
# (RAGLAB_GENERATION_NO_CONTEXT_ANSWER).
NO_CONTEXT_ANSWERS = {
    "pt": "Não posso responder com segurança com o contexto recuperado.",
    "en": "I cannot answer reliably from the retrieved context.",
}

# Quote first, then answer: measured on the frozen sets against the previous
# prompt (same retrieved passages, Gemma judge), refusals with the answer in
# the context fell from 24 to 9 of 100 (PIAF) and 19 to 9 (LexML),
# faithfulness rose 0.907 → 0.943 and 0.895 → 0.930, correctness 0.738 →
# 0.817 on PIAF (LexML unchanged). See docs/benchmarks/prompt.md.
_SYSTEM = {
    "fr": (
        "Tu es un assistant de recherche documentaire. Réponds uniquement à partir du contexte fourni, en français.\n"
        "Procède ainsi :\n"
        "1. Cherche dans le contexte la ou les phrases qui répondent à la question et recopie-les entre guillemets, "
        "avec leur [Rank X].\n"
        "2. Puis réponds en une ou deux phrases en t'appuyant sur ces citations, en citant chaque fait avec [Rank X].\n"
        "N'invente aucun fait, aucune date, aucun numéro d'article ni aucune référence juridique.\n"
        "Si plusieurs sources se contredisent, signale-le.\n"
        "Seulement si aucune phrase du contexte ne se rapporte à la question, réponds exactement par cette phrase "
        "et rien d'autre :\n"
        '"{fallback}"'
    ),
    "pt": (
        "Você é um assistente de pesquisa documental. Responda somente com base no contexto fornecido, em português.\n"
        "Proceda assim:\n"
        "1. Procure no contexto a(s) frase(s) que respondem à pergunta e copie-as entre aspas, com o seu [Rank X].\n"
        "2. Depois responda em uma ou duas frases com base nessas citações, citando cada fato com [Rank X].\n"
        "Não invente fatos, datas, números de artigo nem referências jurídicas.\n"
        "Se as fontes se contradisserem, diga isso.\n"
        "Somente se nenhuma frase do contexto tratar da pergunta, responda exatamente com esta frase e nada mais:\n"
        '"{fallback}"'
    ),
    "en": (
        "You are a document research assistant. Answer only from the provided context, in English.\n"
        "Proceed as follows:\n"
        "1. Find the sentence(s) in the context that answer the question and copy them in quotes, with their [Rank X].\n"
        "2. Then answer in one or two sentences based on those quotes, citing each fact with [Rank X].\n"
        "Never invent facts, dates, article numbers or legal references.\n"
        "If sources contradict each other, say so.\n"
        "Only if no sentence of the context relates to the question, reply exactly with this sentence and nothing "
        "else:\n"
        '"{fallback}"'
    ),
}
_LABELS = {"fr": ("Question", "Contexte"), "pt": ("Pergunta", "Contexto"), "en": ("Question", "Context")}


def question_language(question: str) -> str:
    """ "fr", "pt" or "en" by counting frequent function words; French when
    nothing tips the balance (the project's default language)."""
    words = re.findall(r"[a-zà-ÿ]+", question.lower())
    scores = {language: sum(word in vocabulary for word in words) for language, vocabulary in _LANGUAGE_WORDS.items()}
    best = max(scores, key=lambda language: scores[language])
    return best if scores[best] > scores["fr"] else "fr"


def no_context_answer_for(language: str, french_answer: str) -> str:
    return NO_CONTEXT_ANSWERS.get(language, french_answer)


def build_context(chunks: list[RetrievedChunk]) -> str:
    # Kept as measured (French labels in every language): only the
    # instructions follow the question's language.
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
    """Prompt in the question's language; `no_context_answer` is the French
    fallback sentence (the others are in NO_CONTEXT_ANSWERS)."""
    language = question_language(question)
    fallback = no_context_answer_for(language, no_context_answer)
    question_label, context_label = _LABELS[language]
    system_prompt = _SYSTEM[language].format(fallback=fallback)
    user_prompt = f"{question_label}:\n{question}\n\n{context_label}:\n{build_context(chunks)}"
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
