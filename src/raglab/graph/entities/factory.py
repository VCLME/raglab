from __future__ import annotations

from raglab.config import Settings, get_settings
from raglab.graph.entities.base import (
    SUPPORTED_ENGINES,
    EntityExtractor,
    UnsupportedExtractionEngineError,
)


def build_entity_extractor(
    engine: str,
    *,
    settings: Settings | None = None,
) -> EntityExtractor:
    """Return an EntityExtractor for the requested engine.

    spaCy is imported lazily so the base install stays slim. If the
    user picks `spacy` without the dependency, we surface a precise
    error that tells them which pip extra to install.
    """
    if engine not in SUPPORTED_ENGINES:
        raise UnsupportedExtractionEngineError(
            f"Moteur d'extraction inconnu: {engine!r}. Valeurs supportées: {SUPPORTED_ENGINES}"
        )
    cfg = settings or get_settings()

    if engine == "llm":
        from raglab.graph.entities.llm import LLMEntityExtractor

        return LLMEntityExtractor(settings=cfg)

    from raglab.graph.entities.spacy import SpacyEntityExtractor

    return SpacyEntityExtractor(settings=cfg)
