"""Pluggable benchmark dataset loaders for raglab.

Each loader produces a `BenchmarkDataset` on disk: a corpus of text files
ready for `raglab ingest`, a ground-truth JSONL compatible with
`RecallBenchmarkService`, and a `metadata.json` describing the source.

The registry below is the single source of truth used by the CLI
(`raglab bench download`) and by tests.
"""

from raglab.benchmarks.base import BenchmarkDataset, BenchmarkLoader
from raglab.benchmarks.fquad import FQuADLoader
from raglab.benchmarks.piaf import PIAFLoader
from raglab.benchmarks.squad_style import SquadStyleLoader

AVAILABLE_LOADERS: dict[str, type[BenchmarkLoader]] = {
    PIAFLoader.name: PIAFLoader,
    FQuADLoader.name: FQuADLoader,
}


def get_loader(name: str) -> type[BenchmarkLoader]:
    if name not in AVAILABLE_LOADERS:
        supported = ", ".join(sorted(AVAILABLE_LOADERS)) or "(none)"
        raise ValueError(f"Benchmark loader inconnu: '{name}'. Disponibles : {supported}")
    return AVAILABLE_LOADERS[name]


__all__ = [
    "AVAILABLE_LOADERS",
    "BenchmarkDataset",
    "BenchmarkLoader",
    "FQuADLoader",
    "PIAFLoader",
    "SquadStyleLoader",
    "get_loader",
]
