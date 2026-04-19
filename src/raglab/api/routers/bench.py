from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from raglab.api.schemas import (
    BenchDatasetOnDisk,
    BenchDownloadRequest,
    BenchDownloadResponse,
    BenchLoaderInfo,
)
from raglab.benchmarks import AVAILABLE_LOADERS, get_loader
from raglab.config import get_settings

router = APIRouter(prefix="/api/bench", tags=["bench"])


@router.get("/loaders", response_model=list[BenchLoaderInfo])
def list_loaders() -> list[BenchLoaderInfo]:
    return [
        BenchLoaderInfo(
            name=cls.name,
            language=cls.language,
            licence=cls.licence,
            description=cls.description,
            default_corpus_name=cls.default_corpus_name,
            source=cls.source,
        )
        for cls in AVAILABLE_LOADERS.values()
    ]


@router.get("/datasets", response_model=list[BenchDatasetOnDisk])
def list_local_datasets() -> list[BenchDatasetOnDisk]:
    """Scan `data/benchmarks/*/` for ground_truth.jsonl files already on disk.

    Used by the Benchmarks page to populate the dataset dropdown without
    having to re-trigger a download. Loader metadata (language, source,
    article_count, case_count) is read from the sibling `metadata.json`
    when available.
    """
    base = get_settings().data_dir / "benchmarks"
    if not base.exists():
        return []

    results: list[BenchDatasetOnDisk] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        ground_truth = entry / "ground_truth.jsonl"
        if not ground_truth.exists():
            continue
        corpus_dir = entry / "corpus"
        metadata_path = entry / "metadata.json"
        info = BenchDatasetOnDisk(
            loader=entry.name,
            dataset_dir=str(entry.resolve()),
            ground_truth_path=str(ground_truth.resolve()),
            corpus_dir=str(corpus_dir.resolve()) if corpus_dir.exists() else "",
            metadata_path=str(metadata_path.resolve()) if metadata_path.exists() else None,
        )
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                info.article_count = meta.get("article_count")
                info.case_count = meta.get("case_count")
                info.language = meta.get("language")
                info.source = meta.get("source")
                info.loader = meta.get("loader") or info.loader
            except Exception:
                pass
        results.append(info)
    return results


@router.post("/download", response_model=BenchDownloadResponse)
def download_dataset(body: BenchDownloadRequest) -> BenchDownloadResponse:
    loader_cls = get_loader(body.loader)
    settings = get_settings()
    output_dir = (
        Path(body.output_dir).resolve()
        if body.output_dir
        else (settings.data_dir / "benchmarks" / loader_cls.name).resolve()
    )
    loader = loader_cls()
    dataset = loader.download(output_dir, limit=body.limit)
    return BenchDownloadResponse(
        loader=loader_cls.name,
        corpus_dir=str(dataset.corpus_dir),
        ground_truth_path=str(dataset.ground_truth_path),
        metadata_path=str(dataset.metadata_path),
        corpus_name=dataset.corpus_name,
        article_count=dataset.article_count,
        case_count=dataset.case_count,
    )
