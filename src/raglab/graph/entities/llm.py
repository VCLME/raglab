from __future__ import annotations

import json
import logging
import re

from raglab.config import Settings, get_settings
from raglab.graph.entities.base import (
    DEFAULT_ENTITY_TYPES,
    ExtractedEntity,
    normalise_name,
    normalise_type,
)
from raglab.ollama.service import OllamaService

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You extract named entities from text. Return a JSON object of the form "
    '{"entities": [{"name": "...", "type": "..."}]}. '
    "Use EXACTLY these types: " + ", ".join(DEFAULT_ENTITY_TYPES) + ". "
    "If an entity doesn't fit any of these types, omit it. "
    "Return the shortest possible surface form (the name only, no article). "
    "Do not invent entities that are not literally mentioned in the text. "
    "Reply with JSON only, no commentary."
)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


class LLMEntityExtractor:
    """Extract entities by asking an Ollama chat model for structured JSON.

    Slow but flexible and multilingual — follows whatever language the
    chunk is in, and the default type set covers common law/business
    cases without retraining.
    """

    engine = "llm"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        ollama: OllamaService | None = None,
        model: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.ollama = ollama or OllamaService(self.settings)
        self.model = model or self.settings.generation_model

    def extract(self, text: str) -> list[ExtractedEntity]:
        if not text.strip():
            return []
        user_prompt = f"Text:\n{text}\n\nReturn JSON only."
        try:
            result = self.ollama.chat(
                messages=[{"role": "user", "content": user_prompt}],
                model=self.model,
                system=_SYSTEM_PROMPT,
                options={"temperature": 0.0, "num_predict": 512},
            )
        except Exception as exc:
            logger.warning("entity_extractor.llm.chat_failed: %s", exc)
            return []

        return _parse_entities(result.get("answer", ""))


def _parse_entities(answer: str) -> list[ExtractedEntity]:
    """Best-effort parse of the LLM response into ExtractedEntity rows."""
    if not answer:
        return []

    match = _JSON_BLOCK_RE.search(answer)
    if match is None:
        logger.debug("entity_extractor.llm.no_json_found", extra={"len": len(answer)})
        return []

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.debug("entity_extractor.llm.json_decode_failed: %s", exc)
        return []

    raw_entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(raw_entities, list):
        return []

    seen: set[tuple[str, str]] = set()
    out: list[ExtractedEntity] = []
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        name_raw = raw.get("name")
        type_raw = raw.get("type")
        if not isinstance(name_raw, str) or not name_raw.strip():
            continue
        name = normalise_name(name_raw)
        etype = normalise_type(type_raw if isinstance(type_raw, str) else "")
        key = (name, etype)
        if key in seen:
            continue
        seen.add(key)
        out.append(ExtractedEntity(name=name, type=etype, raw_text=name_raw.strip()))
    return out
