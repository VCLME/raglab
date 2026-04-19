from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

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

    FQuAD repeats the same title across several paragraphs; we dedupe on
    the context hash to keep one file per unique paragraph, and include
    the title as prefix for human readability.
    """
    digest = hashlib.sha1(context.encode("utf-8")).hexdigest()[:12]
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title.strip().lower())[:48]
    return f"{safe_title or 'article'}__{digest}"


class FQuADLoader(BenchmarkLoader):
    """Loader for FQuAD — SQuAD-style French reading-comprehension dataset.

    Source: https://fquad.illuin.tech (Illuin Technology).
    Hugging Face dataset id: ``fquad``.
    Licence: CC-BY-SA-3.0.

    Notes:
    - FQuAD on Hugging Face may require accepting the dataset licence via
      `huggingface-cli login`. If the download fails with an access error,
      log in first, then re-run `raglab bench download fquad`.
    - Each question is tied to exactly one source paragraph. `expected_file_names`
      contains a single entry per case, perfect for Recall@K on retrieval.
    """

    name = "fquad"
    language = "fr"
    licence = "CC-BY-SA-3.0"
    description = "SQuAD-style French QA over Wikipedia passages (Illuin Technology)"
    default_corpus_name = "fquad_fr"
    source = "https://huggingface.co/datasets/fquad"

    DEFAULT_HF_DATASET = "fquad"
    DEFAULT_SPLIT = "validation"

    def __init__(
        self,
        *,
        hf_dataset: str | None = None,
        hf_split: str | None = None,
    ) -> None:
        self.hf_dataset = hf_dataset or self.DEFAULT_HF_DATASET
        self.hf_split = hf_split or self.DEFAULT_SPLIT

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
            "bench.fquad.download_started",
            hf_dataset=self.hf_dataset,
            hf_split=self.hf_split,
            limit=limit,
            output_dir=str(output_dir),
        )

        dataset = load_dataset(self.hf_dataset, split=self.hf_split)

        iterator = iter(dataset)
        seen_stems: dict[str, str] = {}
        cases: list[GroundTruthCase] = []
        processed = 0

        for example in iterator:
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
                        "source": "fquad",
                        "title": title,
                        "hf_dataset": self.hf_dataset,
                        "hf_split": self.hf_split,
                    },
                )
                seen_stems[stem] = title

            cases.append(
                GroundTruthCase(
                    id=f"fquad-{example_id}",
                    question=question,
                    expected_file_names=[f"{stem}.txt"],
                    ground_truth_answer=primary_answer,
                    expected_substrings=[primary_answer] if primary_answer else [],
                )
            )

        if not cases:
            raise RuntimeError(
                "No cases were produced from FQuAD. Check the Hugging Face split "
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
            "bench.fquad.download_completed",
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
