from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from raglab.domain.schemas import RetrievedChunk
from raglab.domain.versions import prompt_line, strip_revoked
from raglab.routing.language import detect_language


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
        "{quote_step}\n"
        "{answer_step}\n"
        "{language_rule}"
        "N'invente aucun fait, aucune date, aucun numéro d'article ni aucune référence juridique.\n"
        "Si plusieurs sources se contredisent, signale-le.\n"
        "Seulement si aucune phrase du contexte ne se rapporte à la question, réponds exactement par cette phrase "
        "et rien d'autre :\n"
        '"{fallback}"'
    ),
    "pt": (
        "Você é um assistente de pesquisa documental. Responda somente com base no contexto fornecido, em português.\n"
        "Proceda assim:\n"
        "{quote_step}\n"
        "{answer_step}\n"
        "{language_rule}"
        "Não invente fatos, datas, números de artigo nem referências jurídicas.\n"
        "Se as fontes se contradisserem, diga isso.\n"
        "Somente se nenhuma frase do contexto tratar da pergunta, responda exatamente com esta frase e nada mais:\n"
        '"{fallback}"'
    ),
    "en": (
        "You are a document research assistant. Answer only from the provided context, in English.\n"
        "Proceed as follows:\n"
        "{quote_step}\n"
        "{answer_step}\n"
        "{language_rule}"
        "Never invent facts, dates, article numbers or legal references.\n"
        "If sources contradict each other, say so.\n"
        "Only if no sentence of the context relates to the question, reply exactly with this sentence and nothing "
        "else:\n"
        '"{fallback}"'
    ),
}
# Steps 1 and 2 of _SYSTEM. Passages in the question's language: the quote
# is copied (the measured V4 prompt, unchanged). Passages in another
# language: copied verbatim, a Portuguese or French quote opened the answer
# (101 of 120 cross-language answers with Qwen3.6, 58 with qwen2.5:7b).
# Asked to translate it ("translate"), the writers still copied it in 79 and
# 35 answers; without a quote ("omit", the default) 1 and 5 answers of 120
# kept foreign text (docs/benchmarks/prompt.md, answer-lang-en-v1).
CROSS_LANGUAGE_MODES = ("verbatim", "translate", "omit")
_QUOTE_STEP = {
    "fr": "1. Cherche dans le contexte la ou les phrases qui répondent à la question et recopie-les entre guillemets, "
    "avec leur [Rank X].",
    "pt": "1. Procure no contexto a(s) frase(s) que respondem à pergunta e copie-as entre aspas, com o seu [Rank X].",
    "en": "1. Find the sentence(s) in the context that answer the question and copy them in quotes, with their [Rank X].",
}
_TRANSLATED_QUOTE_STEP = {
    "fr": "1. Cherche dans le contexte la ou les phrases qui répondent à la question. Le contexte est en {source} : "
    "traduis-les en français et donne la traduction entre guillemets, avec leur [Rank X].",
    "pt": "1. Procure no contexto a(s) frase(s) que respondem à pergunta. O contexto está em {source}: "
    "traduza-as para o português e dê a tradução entre aspas, com o seu [Rank X].",
    "en": "1. Find the sentence(s) in the context that answer the question. The context is in {source}: "
    "translate them into English and give the translation in quotes, with their [Rank X].",
}
_PASSAGE_STEP = {
    "fr": "1. Cherche dans le contexte le ou les passages qui répondent à la question (le contexte est en {source}) "
    "et note leur [Rank X].",
    "pt": "1. Procure no contexto o(s) trecho(s) que respondem à pergunta (o contexto está em {source}) "
    "e anote o seu [Rank X].",
    "en": "1. Find the passage(s) of the context that answer the question (the context is in {source}) "
    "and note their [Rank X].",
}
_ANSWER_STEP = {
    "fr": "2. Puis réponds en une ou deux phrases en t'appuyant sur ces citations, en citant chaque fait avec [Rank X].",
    "pt": "2. Depois responda em uma ou duas frases com base nessas citações, citando cada fato com [Rank X].",
    "en": "2. Then answer in one or two sentences based on those quotes, citing each fact with [Rank X].",
}
_ANSWER_FROM_PASSAGES_STEP = {
    "fr": "2. Puis réponds en une ou deux phrases en t'appuyant sur ces passages, en citant chaque fait avec [Rank X].",
    "pt": "2. Depois responda em uma ou duas frases com base nesses trechos, citando cada fato com [Rank X].",
    "en": "2. Then answer in one or two sentences based on those passages, citing each fact with [Rank X].",
}
_LANGUAGE_RULE = {
    "fr": "Écris toute la réponse en français, citations comprises ; seuls les noms propres et les intitulés "
    "(lois, organismes, articles) restent tels qu'ils sont écrits.\n",
    "pt": "Escreva toda a resposta em português, inclusive as citações; só os nomes próprios e os títulos "
    "(leis, órgãos, artigos) ficam como estão escritos.\n",
    "en": "Write the whole answer in English, quotes included; only proper names and titles "
    "(laws, bodies, articles) stay as written.\n",
}
_LANGUAGE_NAMES = {
    "fr": {"fr": "français", "pt": "portugais", "en": "anglais"},
    "pt": {"fr": "francês", "pt": "português", "en": "inglês"},
    "en": {"fr": "French", "pt": "Portuguese", "en": "English"},
}
_LABELS = {"fr": ("Question", "Contexte"), "pt": ("Pergunta", "Contexto"), "en": ("Question", "Context")}


def question_language(question: str) -> str:
    """ "fr", "pt" or "en" by counting frequent function words; French when
    nothing tips the balance (the project's default language)."""
    words = re.findall(r"[a-zà-ÿ]+", question.lower())
    scores = {language: sum(word in vocabulary for word in words) for language, vocabulary in _LANGUAGE_WORDS.items()}
    best = max(scores, key=lambda language: scores[language])
    return best if scores[best] > scores["fr"] else "fr"


def context_language(chunks: list[RetrievedChunk]) -> str | None:
    """Language of most passages ("fr", "pt" or "en"); None when none has a
    clear one."""
    counts: dict[str, int] = {}
    for chunk in chunks:
        detected = detect_language(chunk.chunk_text).language
        if detected in _LANGUAGE_NAMES:
            counts[detected] = counts.get(detected, 0) + 1
    return max(counts, key=lambda language: counts[language]) if counts else None


def no_context_answer_for(language: str, french_answer: str) -> str:
    return NO_CONTEXT_ANSWERS.get(language, french_answer)


def presented_passage(chunk: RetrievedChunk, *, today: date | None = None) -> str:
    """One passage exactly as the writer reads it in its context."""
    # Version state of the passage (versions option, phase 9.10): the model
    # is told which article version it reads, and does not read the wording
    # of provisions marked repealed.
    status = prompt_line(chunk.version, today=today)
    text = chunk.chunk_text
    version = chunk.version
    if version is not None and version.in_prompt and version.source == "markers" and version.revoked_lines:
        text = strip_revoked(text)
    return "\n".join(
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


def presented_passages(chunks: list[RetrievedChunk], *, today: date | None = None) -> list[str]:
    """The passages of the writer's context as presented. Recorded with the
    answer, so the faithfulness judge grades against what the writer saw
    (version line, repealed provisions replaced by a note), not the raw
    chunk text."""
    return [presented_passage(chunk, today=today) for chunk in chunks]


def build_context(chunks: list[RetrievedChunk]) -> str:
    # Kept as measured (French labels in every language): only the
    # instructions follow the question's language.
    return "\n\n".join(presented_passages(chunks))


def build_prompt_bundle(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    no_context_answer: str,
    cross_language: str = "omit",
) -> PromptBundle:
    """Prompt in the question's language; `no_context_answer` is the French
    fallback sentence (the others are in NO_CONTEXT_ANSWERS). `cross_language`
    is what happens to the quote when the passages are in another language
    (CROSS_LANGUAGE_MODES; "verbatim" is the prompt before answer-lang-en)."""
    language = question_language(question)
    fallback = no_context_answer_for(language, no_context_answer)
    question_label, context_label = _LABELS[language]
    source = context_language(chunks) if cross_language != "verbatim" else None
    quote_step, answer_step, language_rule = _QUOTE_STEP[language], _ANSWER_STEP[language], ""
    if source is not None and source != language:
        source_name = _LANGUAGE_NAMES[language][source]
        language_rule = _LANGUAGE_RULE[language]
        if cross_language == "omit":
            quote_step = _PASSAGE_STEP[language].format(source=source_name)
            answer_step = _ANSWER_FROM_PASSAGES_STEP[language]
        else:
            quote_step = _TRANSLATED_QUOTE_STEP[language].format(source=source_name)
    system_prompt = _SYSTEM[language].format(
        fallback=fallback, quote_step=quote_step, answer_step=answer_step, language_rule=language_rule
    )
    user_prompt = f"{question_label}:\n{question}\n\n{context_label}:\n{build_context(chunks)}"
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
