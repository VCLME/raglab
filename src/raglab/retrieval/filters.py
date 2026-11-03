from __future__ import annotations

from collections.abc import Iterable

from raglab.document_metadata import normalize_tags
from raglab.domain.schemas import RetrievalFilters


def parse_metadata_equals(values: Iterable[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_value in values or []:
        key, separator, value = raw_value.partition("=")
        key = key.strip()
        value = value.strip()
        if separator != "=" or not key or not value:
            raise ValueError(f"Filtre metadata invalide: {raw_value!r}. Format attendu: cle=valeur")
        if key in parsed:
            raise ValueError(f"Filtre metadata duplique pour la cle {key!r}")
        parsed[key] = value
    return parsed


def build_retrieval_filters(
    *,
    document_ids: list[str] | None = None,
    file_names: list[str] | None = None,
    source_path_contains: str | None = None,
    tags: list[str] | None = None,
    metadata_equals: Iterable[str] | None = None,
) -> RetrievalFilters | None:
    filters = RetrievalFilters(
        document_ids=[value.strip() for value in document_ids or [] if value.strip()],
        file_names=[value.strip() for value in file_names or [] if value.strip()],
        source_path_contains=(source_path_contains or "").strip() or None,
        tags=normalize_tags(tags),
        metadata_equals=parse_metadata_equals(metadata_equals),
    )
    return None if filters.is_empty() else filters
