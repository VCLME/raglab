from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class BenchmarkDataset:
    """Result of a benchmark download — paths on disk raglab can ingest.

    - `corpus_dir` contains `.txt` files (+ `.json` sidecars with metadata)
      directly ingestable via `raglab ingest <corpus_dir> --corpus <name>`.
    - `ground_truth_path` is a JSONL compatible with the existing
      `RecallBenchmarkService` (one case per line with `id`, `question`,
      `expected_file_names`, optional `expected_urns`, `ground_truth_answer`,
      `expected_substrings`).
    - `metadata_path` is a JSON sidecar describing the source for audit.
    - `corpus_name` is the suggested raglab corpus name for this dataset.
    """

    corpus_dir: Path
    ground_truth_path: Path
    metadata_path: Path
    corpus_name: str
    article_count: int
    case_count: int


@dataclass(slots=True)
class GroundTruthCase:
    id: str
    question: str
    expected_file_names: list[str]
    ground_truth_answer: str | None = None
    expected_substrings: list[str] = field(default_factory=list)
    expected_urns: list[str] = field(default_factory=list)
    #: Gold passages as `{"file_name", "start", "end", "text"}` dicts. Offsets
    #: index into the normalised document text, so relevance can be judged at
    #: passage level independently of the chunking strategy.
    expected_spans: list[dict] = field(default_factory=list)

    def to_jsonl_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class BenchmarkLoader(ABC):
    """Abstract contract every concrete benchmark loader must implement.

    Subclasses declare static metadata (`name`, `language`, `licence`,
    `description`, `default_corpus_name`) and implement `download` which
    materialises the dataset on disk and returns a `BenchmarkDataset`.
    """

    name: str = ""
    language: str = ""
    licence: str = ""
    description: str = ""
    default_corpus_name: str = ""
    source: str = ""

    @abstractmethod
    def download(
        self,
        output_dir: Path,
        *,
        limit: int | None = None,
        sample_seed: int = 42,
        full_corpus: bool = True,
    ) -> BenchmarkDataset:
        """Materialise the dataset in `output_dir` and return its handles.

        `limit` caps the number of ground-truth cases (not the number of
        articles — articles are always deduplicated). `None` means full
        split. With `full_corpus=True` every article of the split is written
        even when `limit` is set, and the `limit` cases are drawn with
        `sample_seed`: retrieval then has to find the right passage in the
        whole haystack, not among the handful of passages the sample touches.
        """


def write_article(
    corpus_dir: Path,
    *,
    stem: str,
    text: str,
    metadata: dict,
) -> Path:
    """Write a corpus article with its sidecar metadata file.

    Returns the path to the `.txt` file (the key raglab uses to match a
    retrieved chunk back to its article via `expected_file_names`).
    """
    corpus_dir.mkdir(parents=True, exist_ok=True)
    text_path = corpus_dir / f"{stem}.txt"
    sidecar_path = corpus_dir / f"{stem}.json"
    text_path.write_text(text, encoding="utf-8")
    sidecar_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return text_path


def write_metadata(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_ground_truth(path: Path, cases: list[GroundTruthCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(case.to_jsonl_line())
            handle.write("\n")
