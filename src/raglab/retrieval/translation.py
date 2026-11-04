"""Query translation for the lexical side (cross-language questions).

BM25 matches words: a French question ("ministère des Finances") shares
almost none with a Portuguese law ("Ministério da Fazenda"), while the
multilingual embedder and cross-encoder bridge the two languages. With
`RAGLAB_QUERY_TRANSLATION` on, a question whose detected language differs
from the corpus language is translated into the corpus language by the
local writer (llama.cpp, `RAGLAB_WRITER_MODEL`) and the translation feeds
BM25 only. The dense search, the re-ranking and the answer keep the original
question.

Translation never fails a query: when the writer does not answer (down,
serving another model, timeout), BM25 gets the original question and the
outcome says why (`notice`).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from raglab.config import Settings
from raglab.llm.local_server import model_matches
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.routing.language import detect_language

LOGGER = logging.getLogger(__name__)

LANGUAGE_NAMES = {"fr": "French", "pt": "Brazilian Portuguese", "en": "English"}

_SYSTEM_PROMPT = (
    "You translate search queries about law. Translate the user's question into {target}, "
    "as a lawyer of that country would phrase it, using the legal terms and institution names "
    "of that country. Keep acronyms and proper names. Output only the translated question."
)

_CACHE_SIZE = 512


@dataclass(frozen=True)
class Translation:
    # Text sent to BM25: the translation, or the question when none was made.
    text: str
    source_language: str
    target_language: str | None
    translated: bool
    elapsed_ms: float = 0.0
    # Why the question was not translated: same_language, unknown_language,
    # writer_unavailable, failed.
    notice: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "translated": self.translated,
            "elapsed_ms": round(self.elapsed_ms, 3),
            **({"notice": self.notice} if self.notice else {}),
        }


class QueryTranslator:
    """Translate questions with the local writer, with a small in-memory cache."""

    def __init__(self, settings: Settings, *, client: OpenAICompatibleChat | None = None):
        self.settings = settings
        self.client = client or OpenAICompatibleChat(settings)
        self._cache: OrderedDict[tuple[str, str], str] = OrderedDict()

    def translate(self, question: str, target_language: str | None) -> Translation:
        source = detect_language(question).language
        if not target_language or target_language not in LANGUAGE_NAMES or source not in LANGUAGE_NAMES:
            return Translation(question, source, target_language, False, notice="unknown_language")
        if source == target_language:
            return Translation(question, source, target_language, False, notice="same_language")
        key = (question, target_language)
        if key in self._cache:
            self._cache.move_to_end(key)
            return Translation(self._cache[key], source, target_language, True)
        started = perf_counter()
        try:
            served = self.client.list_models(timeout=2.0)
            if not model_matches(served, self.settings.writer_model):
                return Translation(question, source, target_language, False, notice="writer_unavailable")
            result = self.client.chat(
                messages=[{"role": "user", "content": question}],
                model=self.settings.writer_model,
                system=_SYSTEM_PROMPT.format(target=LANGUAGE_NAMES[target_language]),
                options={"temperature": 0.0, "num_predict": 200, "seed": 42},
                timeout=int(self.settings.query_translation_timeout_seconds),
            )
        except Exception as exc:  # network, HTTP or timeout: BM25 keeps the question
            log_event(LOGGER, logging.WARNING, "query_translation.failed", error=str(exc))
            elapsed = (perf_counter() - started) * 1000
            return Translation(question, source, target_language, False, elapsed, notice="writer_unavailable")
        text = _clean(result.get("answer", ""))
        elapsed = (perf_counter() - started) * 1000
        if not text:
            return Translation(question, source, target_language, False, elapsed, notice="failed")
        self._cache[key] = text
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        log_event(
            LOGGER,
            logging.INFO,
            "query_translation.done",
            source=source,
            target=target_language,
            elapsed_ms=round(elapsed, 2),
        )
        return Translation(text, source, target_language, True, elapsed)


def _clean(answer: str) -> str:
    """First non-empty line, without quotes or a "Translation:" prefix."""
    line = next((part.strip() for part in answer.splitlines() if part.strip()), "")
    if ":" in line[:20] and line.split(":", 1)[0].strip().lower() in ("translation", "tradução", "traduction"):
        line = line.split(":", 1)[1].strip()
    return line.strip("\"'«» ")
