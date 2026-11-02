from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from raglab.api.schemas import (
    LexMLFullTextRequest,
    LexMLGetDataRequest,
    LexMLLoadRequest,
    LexMLQuestionsRequest,
)
from raglab.benchmarks.lexml_questions import LexMLQuestionGenerator
from raglab.config import get_settings
from raglab.lexml import LexMLLoadService, getDataFromLexML
from raglab.lexml.fulltext import FullTextCollector

router = APIRouter(prefix="/api/lexml", tags=["lexml"])


@router.post("/get-data")
def lexml_get_data(body: LexMLGetDataRequest) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(body.output_dir) if body.output_dir else settings.lexml_documents_dir
    return getDataFromLexML(output_dir=output_dir, page_limit=body.page_limit)


@router.post("/fulltext")
def lexml_fulltext(body: LexMLFullTextRequest) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(body.output_dir) if body.output_dir else settings.lexml_fulltext_dir
    return FullTextCollector(settings).collect(
        output_dir=output_dir,
        years=range(body.year_from, body.year_to + 1),
        per_year=body.per_year,
        seed=body.seed,
        min_chars=body.min_chars,
        max_chars=body.max_chars,
    )


@router.post("/questions")
def lexml_questions(body: LexMLQuestionsRequest) -> dict[str, Any]:
    settings = get_settings()
    corpus_dir = Path(body.corpus_dir) if body.corpus_dir else settings.lexml_fulltext_dir / "corpus"
    output_dir = Path(body.output_dir) if body.output_dir else settings.data_dir / "benchmarks" / "lexml_fulltext"
    return LexMLQuestionGenerator(settings, model=body.model).generate(
        corpus_dir=corpus_dir,
        output_dir=output_dir,
        count=body.count,
        seed=body.seed,
    )


@router.post("/load")
def lexml_load(body: LexMLLoadRequest) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(body.output_dir) if body.output_dir else settings.lexml_documents_dir
    service = LexMLLoadService()
    return service.run(
        output_dir=output_dir,
        corpus_name=body.corpus,
        strategy=body.strategy,
        page_limit=body.page_limit,
        incremental=body.incremental,
        tags=body.tags,
        embedding_provider=body.embedding_provider,
        embedding_model_name=body.embedding_model,
        initialize_db=True,
    )
