"""Shared download logic for SQuAD-style datasets.

Several French and multilingual QA datasets on Hugging Face share the same
schema popularized by SQuAD: each row has `id`, `title`, `context`, `question`,
`answers={"text": [...], "answer_start": [...]}`. FQuAD, PIAF, mMARCO-fr
variants, SQuAD-fr, original SQuAD — all fit this mould.

This module factorises the pipeline so each concrete loader only needs to
declare the HF dataset id, the split to read from, and its public metadata.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from raglab.benchmarks.base import (
    BenchmarkDataset,
    BenchmarkLoader,
    GroundTruthCase,
    write_article,
    write_ground_truth,
    write_metadata,
)
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


def _article_stem(title: str, context: str) -> str:
    """Deterministic file stem for a (title, context) pair.

    SQuAD-style datasets repeat the same title across paragraphs, so we dedupe
    on the context hash (one file per unique paragraph) and prefix with a
    slug of the title for human readability.
    """
    digest = hashlib.sha1(context.encode("utf-8")).hexdigest()[:12]
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title.strip().lower())[:48]
    return f"{safe_title or 'article'}__{digest}"


class SquadStyleLoader(BenchmarkLoader):
    """Base class for loaders backed by a SQuAD-style HF dataset."""

    #: Hugging Face dataset id (e.g. "etalab-ia/piaf").
    hf_dataset_id: str = ""
    #: Default split to read. Subclasses may override.
    default_split: str = "train"

    def __init__(
        self,
        *,
        hf_dataset: str | None = None,
        hf_split: str | None = None,
    ) -> None:
        self.hf_dataset = hf_dataset or self.hf_dataset_id
        self.hf_split = hf_split or self.default_split

    def download(
        self,
        output_dir: Path,
        *,
        limit: int | None = None,
    ) -> BenchmarkDataset:
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError(
                "The 'datasets' package is required for benchmark loaders. "
                "Install it with: pip install datasets"
            ) from exc

        output_dir = Path(output_dir).resolve()
        corpus_dir = output_dir / "corpus"
        ground_truth_path = output_dir / "ground_truth.jsonl"
        metadata_path = output_dir / "metadata.json"

        log_event(
            LOGGER,
            logging.INFO,
            "bench.squad_style.download_started",
            loader=self.name,
            hf_dataset=self.hf_dataset,
            hf_split=self.hf_split,
            limit=limit,
            output_dir=str(output_dir),
        )

        dataset = load_dataset(self.hf_dataset, split=self.hf_split)

        seen_stems: dict[str, str] = {}
        cases: list[GroundTruthCase] = []
        processed = 0

        for example in dataset:
            if limit is not None and len(cases) >= limit:
                break

            title = (example.get("title") or "unknown").strip()
            context = (example.get("context") or "").strip()
            question = (example.get("question") or "").strip()
            example_id = str(example.get("id") or f"row-{processed}")
            answers = example.get("answers") or {}
            answer_texts: list[str] = list(answers.get("text") or [])
            primary_answer = answer_texts[0] if answer_texts else None

            processed += 1
            if not context or not question:
                continue

            stem = _article_stem(title, context)
            if stem not in seen_stems:
                write_article(
                    corpus_dir,
                    stem=stem,
                    text=context,
                    metadata={
                        "source": self.name,
                        "title": title,
                        "hf_dataset": self.hf_dataset,
                        "hf_split": self.hf_split,
                    },
                )
                seen_stems[stem] = title

            cases.append(
                GroundTruthCase(
                    id=f"{self.name}-{example_id}",
                    question=question,
                    expected_file_names=[f"{stem}.txt"],
                    ground_truth_answer=primary_answer,
                    expected_substrings=[primary_answer] if primary_answer else [],
                )
            )

        if not cases:
            raise RuntimeError(
                f"No cases produced from {self.name}. Check the HF split "
                f"'{self.hf_split}' for '{self.hf_dataset}'."
            )

        write_ground_truth(ground_truth_path, cases)
        write_metadata(
            metadata_path,
            {
                "loader": self.name,
                "source": self.source,
                "hf_dataset": self.hf_dataset,
                "hf_split": self.hf_split,
                "language": self.language,
                "licence": self.licence,
                "description": self.description,
                "article_count": len(seen_stems),
                "case_count": len(cases),
                "limit": limit,
            },
        )

        log_event(
            LOGGER,
            logging.INFO,
            "bench.squad_style.download_completed",
            loader=self.name,
            articles=len(seen_stems),
            cases=len(cases),
            processed_examples=processed,
        )

        return BenchmarkDataset(
            corpus_dir=corpus_dir,
            ground_truth_path=ground_truth_path,
            metadata_path=metadata_path,
            corpus_name=self.default_corpus_name,
            article_count=len(seen_stems),
            case_count=len(cases),
        )
