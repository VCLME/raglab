from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def normalize_tags(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = str(value).strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return normalized


def _metadata_candidates(path: Path) -> list[Path]:
    return [
        path.with_suffix(".json"),
        path.parent / f"{path.name}.metadata.json",
        path.parent / f"{path.stem}.metadata.json",
    ]


def find_metadata_sidecar(path: Path) -> Path | None:
    for candidate in _metadata_candidates(path):
        if candidate == path:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def load_metadata_sidecar(path: Path) -> tuple[Path | None, dict[str, Any]]:
    sidecar_path = find_metadata_sidecar(path)
    if sidecar_path is None:
        return None, {}

    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Metadata sidecar ignored for %s: %s", path, exc)
        return sidecar_path, {}

    if not isinstance(payload, dict):
        LOGGER.warning("Metadata sidecar ignored for %s because it does not contain a JSON object.", path)
        return sidecar_path, {}

    return sidecar_path, payload


def build_document_metadata(
    path: Path,
    *,
    root: Path,
    extra_tags: Iterable[str] | None = None,
) -> dict[str, Any]:
    sidecar_path, sidecar_payload = load_metadata_sidecar(path)

    raw_tags = sidecar_payload.pop("tags", [])
    if isinstance(raw_tags, str):
        sidecar_tags = [raw_tags]
    elif isinstance(raw_tags, Iterable):
        sidecar_tags = [str(value) for value in raw_tags]
    else:
        sidecar_tags = []

    metadata = dict(sidecar_payload)
    metadata["relative_path"] = str(path.relative_to(root))
    metadata["size_bytes"] = path.stat().st_size
    metadata["tags"] = normalize_tags([*sidecar_tags, *(extra_tags or [])])

    if sidecar_path is not None:
        metadata["metadata_sidecar_path"] = str(sidecar_path.relative_to(root))

    return metadata
