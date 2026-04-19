from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from raglab.api.schemas import (
    BenchCustomRequest,
    BenchCustomResponse,
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


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _safe_dataset_slug(name: str) -> str:
    slug = _SAFE_NAME_RE.sub("_", name.strip()).strip("_").lower()
    if not slug:
        raise HTTPException(status_code=400, detail="name must contain alphanumeric characters")
    return slug


@router.get("/suggestions", response_model=list[str])
def dataset_suggestions(corpus: str, limit: int = 4) -> list[str]:
    """Return up to `limit` questions from datasets matching the given corpus.

    Used by the Chat page to replace generic hardcoded suggestions with
    real questions drawn from whichever validation dataset is pinned to
    this corpus (custom datasets store it explicitly; downloaded loaders
    match by loader-name substring, e.g. `piaf` in `piaf_fr`).
    """
    base = get_settings().data_dir / "benchmarks"
    if not base.exists() or limit <= 0:
        return []
    limit = max(1, min(limit, 20))
    corpus_lc = corpus.lower()

    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        ground_truth = entry / "ground_truth.jsonl"
        if not ground_truth.exists():
            continue

        pinned_corpus: str | None = None
        metadata_path = entry / "metadata.json"
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                pinned_corpus = meta.get("corpus")
            except Exception:
                pinned_corpus = None

        explicit_match = pinned_corpus and pinned_corpus.lower() == corpus_lc
        heuristic_match = entry.name.lower() in corpus_lc or corpus_lc in entry.name.lower()
        if not (explicit_match or heuristic_match):
            continue

        questions: list[str] = []
        with ground_truth.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                q = row.get("question")
                if isinstance(q, str) and q.strip():
                    questions.append(q.strip())
                    if len(questions) >= limit:
                        break
        if questions:
            return questions

    return []


@router.post("/custom", response_model=BenchCustomResponse, status_code=201)
def create_custom_dataset(body: BenchCustomRequest) -> BenchCustomResponse:
    if not body.cases:
        raise HTTPException(status_code=400, detail="cases must not be empty")
    for i, case in enumerate(body.cases):
        if not case.question.strip():
            raise HTTPException(status_code=400, detail=f"case {i}: question is empty")
        if not case.expected_file_names and not (case.expected_answer and case.expected_answer.strip()):
            raise HTTPException(
                status_code=400,
                detail=f"case {i}: provide expected_file_names or expected_answer",
            )

    slug = _safe_dataset_slug(body.name)
    settings = get_settings()
    dataset_dir = (settings.data_dir / "benchmarks" / f"custom_{slug}").resolve()
    dataset_dir.mkdir(parents=True, exist_ok=True)

    ground_truth_path = dataset_dir / "ground_truth.jsonl"
    with ground_truth_path.open("w", encoding="utf-8") as fh:
        for case in body.cases:
            fh.write(
                json.dumps(
                    {
                        "id": str(uuid4()),
                        "question": case.question.strip(),
                        "expected_file_names": [f for f in case.expected_file_names if f],
                        "ground_truth_answer": (case.expected_answer or "").strip() or None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    metadata_path = dataset_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "loader": f"custom_{slug}",
                "kind": "custom",
                "name": body.name,
                "corpus": body.corpus,
                "language": body.language,
                "description": body.description,
                "case_count": len(body.cases),
                "source": "user-created",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return BenchCustomResponse(
        name=body.name,
        dataset_dir=str(dataset_dir),
        ground_truth_path=str(ground_truth_path),
        metadata_path=str(metadata_path),
        case_count=len(body.cases),
    )


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
