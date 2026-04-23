from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

SUPPORTED_ENGINES = ("llm", "spacy")

DEFAULT_ENTITY_TYPES = (
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "DATE",
    "LAW",
    "EVENT",
    "PRODUCT",
)
"""Canonical entity types raglab asks extractors to return.

We intentionally stay coarse-grained — users can refine per corpus
later. Extractors that produce their own labels (spaCy) are mapped
onto this set.
"""


class UnsupportedExtractionEngineError(ValueError):
    """Raised when the requested engine isn't `llm` or `spacy`."""


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    """One entity mention found in a chunk.

    `name` is the surface form after normalisation (lowercased, trimmed).
    `type` is one of `DEFAULT_ENTITY_TYPES`. `span` is optional — some
    extractors (LLM) don't reliably return offsets.
    """

    name: str
    type: str
    span: tuple[int, int] | None = None
    score: float | None = None
    raw_text: str | None = None


@dataclass(slots=True)
class ExtractionResult:
    """Entities extracted from a single chunk of text."""

    entities: list[ExtractedEntity] = field(default_factory=list)


class EntityExtractor(Protocol):
    """Protocol for backends that pull named entities out of text."""

    engine: str

    def extract(self, text: str) -> list[ExtractedEntity]:
        """Return the entities found in `text`. Empty list when nothing."""


def normalise_name(raw: str) -> str:
    """Canonicalise an entity surface form for graph dedup.

    Cheap and deterministic: trim, collapse whitespace, lowercase. We
    avoid accent stripping so that `Böhme` stays distinct from `Bohme`
    unless an explicit normaliser is added.
    """
    return " ".join(raw.split()).lower()


def normalise_type(raw: str) -> str:
    """Return an uppercase entity type; fallback to MISC if unknown."""
    upper = (raw or "").strip().upper()
    if upper in DEFAULT_ENTITY_TYPES:
        return upper
    return "MISC"
