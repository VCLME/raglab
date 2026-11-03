from __future__ import annotations

import logging
from typing import Any

from raglab.config import Settings, get_settings
from raglab.graph.entities.base import (
    ExtractedEntity,
    normalise_name,
)

logger = logging.getLogger(__name__)

# spaCy emits the OntoNotes-style labels below. We map them onto
# raglab's coarse DEFAULT_ENTITY_TYPES so both extractors produce the
# same graph schema.
_SPACY_TO_RAGLAB = {
    "PERSON": "PERSON",
    "PER": "PERSON",
    "NORP": "ORGANIZATION",
    "ORG": "ORGANIZATION",
    "FAC": "LOCATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "DATE": "DATE",
    "TIME": "DATE",
    "EVENT": "EVENT",
    "LAW": "LAW",
    "WORK_OF_ART": "PRODUCT",
    "PRODUCT": "PRODUCT",
    "MISC": "MISC",
}


class SpacyEntityExtractor:
    """spaCy-backed extractor. Fast, language-specific, 18-type schema.

    Falls back gracefully when spaCy isn't installed or the requested
    model isn't downloaded — raising a descriptive error at
    construction time rather than at first use.
    """

    engine = "spacy"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        model_name: str | None = None,
        nlp: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_name = model_name or self.settings.entity_spacy_model

        if nlp is not None:
            self._nlp = nlp
            return

        try:
            import spacy  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "spaCy n'est pas installé. Lance "
                "`pip install raglab[graph]` "
                '(ou `pip install spacy>=3.7`) ou choisis engine="llm".'
            ) from exc

        try:
            self._nlp = spacy.load(self.model_name, disable=["parser", "lemmatizer"])
        except OSError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                f"Le modèle spaCy {self.model_name!r} n'est pas téléchargé. "
                f"Lance `python -m spacy download {self.model_name}` ou choisis un autre modèle."
            ) from exc

    def extract(self, text: str) -> list[ExtractedEntity]:
        if not text.strip():
            return []
        doc = self._nlp(text)
        seen: set[tuple[str, str]] = set()
        out: list[ExtractedEntity] = []
        for ent in doc.ents:
            mapped = _SPACY_TO_RAGLAB.get(ent.label_, "MISC")
            name = normalise_name(ent.text)
            if not name:
                continue
            key = (name, mapped)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                ExtractedEntity(
                    name=name,
                    type=mapped,
                    span=(ent.start_char, ent.end_char),
                    raw_text=ent.text,
                )
            )
        return out
