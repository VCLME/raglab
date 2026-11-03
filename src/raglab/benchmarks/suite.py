"""`raglab bench all`: rebuild every benchmark number from a single command.

For each suite (PIAF in French, LexML full text in Portuguese) the runner:

1. makes sure the corpus is on disk (downloads / collects it otherwise) and,
   for LexML, that every text still matches the frozen manifest;
2. ingests and indexes it in a dedicated corpus (`bench_*`), reusing a
   compatible index run when nothing changed;
3. runs the recall benchmark on the frozen question set, generating and
   grading answers for the first `ragas_limit` cases;
4. records the machine, the software versions and the exact command.

The result is written as JSON (`benchmarks/results/<label>.json`) and as a
Markdown report, so the README table can always be regenerated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import text

from raglab.config import Settings, get_settings
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.experiments.ragas import JudgeConfig
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Suite:
    name: str
    language: str
    corpus_name: str
    corpus_dir: Path
    dataset_path: Path
    manifest_path: Path | None = None


def default_suites(settings: Settings, repo_root: Path) -> list[Suite]:
    return [
        Suite(
            name="piaf",
            language="fr",
            corpus_name="bench_piaf_fr",
            corpus_dir=settings.data_dir / "benchmarks" / "piaf" / "corpus",
            dataset_path=repo_root / "benchmarks" / "piaf" / "ground_truth.jsonl",
        ),
        Suite(
            name="lexml_fulltext",
            language="pt",
            corpus_name="bench_lexml_pt",
            corpus_dir=settings.lexml_fulltext_dir / "corpus",
            dataset_path=repo_root / "benchmarks" / "lexml_fulltext" / "ground_truth.jsonl",
            manifest_path=repo_root / "benchmarks" / "lexml_fulltext" / "corpus_manifest.json",
        ),
    ]


def verify_manifest(corpus_dir: Path, manifest_path: Path) -> list[str]:
    """Return the files that are missing or differ from the frozen manifest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for row in manifest["documents"]:
        path = corpus_dir / row["file_name"]
        if not path.exists():
            problems.append(f"missing:{row['file_name']}")
            continue
        digest = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if digest != row["sha256"]:
            problems.append(f"changed:{row['file_name']}")
    return problems


def _ensure_corpus(suite: Suite, settings: Settings) -> None:
    if suite.corpus_dir.exists() and any(suite.corpus_dir.glob("*.txt")):
        return
    if suite.name == "piaf":
        from raglab.benchmarks.piaf import PIAFLoader

        PIAFLoader().download(suite.corpus_dir.parent, limit=500, sample_seed=42)
    elif suite.name == "lexml_fulltext":
        from raglab.lexml.fulltext import FullTextCollector

        FullTextCollector(settings).collect(
            output_dir=suite.corpus_dir.parent, years=range(1988, 2025), per_year=7, seed=42
        )
    else:
        raise ValueError(f"Corpus absent et pas de recette pour le produire: {suite.corpus_dir}")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def _gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return out or "none"
    except (OSError, subprocess.CalledProcessError):
        return "none"


def environment_report(settings: Settings, session: Any, judge: JudgeConfig | None) -> dict[str, Any]:
    """Machine, versions and models: what a reader needs to reproduce."""
    ollama_digest = "unknown"
    try:
        tags = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=5).json().get("models", [])
        ollama_digest = next(
            (model.get("digest", "")[:12] for model in tags if model.get("name") == settings.generation_model),
            "missing",
        )
    except (requests.RequestException, ValueError):
        pass
    pgvector = session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
    postgres = session.execute(text("SHOW server_version")).scalar()
    try:
        import psutil  # type: ignore[import-untyped]

        ram = f"{psutil.virtual_memory().total / 2**30:.0f} Go"
    except ImportError:
        ram = "unknown"
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram": ram,
        "gpu": _gpu(),
        "python": sys.version.split()[0],
        "torch": _version("torch"),
        "transformers": _version("transformers"),
        "postgres": postgres,
        "pgvector": pgvector,
        "embedding_model": f"{settings.embedding_provider}:{settings.embedding_model_name} ({settings.embedding_device})",
        "distance": settings.distance_metric,
        "generation_model": f"ollama:{settings.generation_model} ({ollama_digest})",
        "judge": judge.label(settings) if judge else None,
        "command": " ".join(["raglab", *sys.argv[1:]]) if sys.argv else "raglab bench all",
    }


def run_suite(
    suite: Suite,
    *,
    settings: Settings,
    strategy: ChunkingStrategy,
    top_k: int,
    ragas_limit: int | None,
    judge: JudgeConfig | None,
    retrieval_mode: RetrievalMode | None = None,
    rerank: bool | None = None,
) -> dict[str, Any]:
    from raglab.db import session_scope
    from raglab.experiments.recall import RecallBenchmarkService
    from raglab.indexing.service import IndexingService
    from raglab.ingestion.service import IngestionService

    _ensure_corpus(suite, settings)
    problems = verify_manifest(suite.corpus_dir, suite.manifest_path) if suite.manifest_path else []
    if problems:
        raise RuntimeError(
            f"Le corpus {suite.name} ne correspond plus au manifeste fige ({len(problems)} fichiers, ex. {problems[:3]}). "
            "Les positions des reponses attendues ne sont plus fiables."
        )

    with session_scope() as session:
        ingestion = IngestionService(session).ingest_folder(
            suite.corpus_dir, corpus_name=suite.corpus_name, description=f"Benchmark {suite.name} (fige)"
        )
    with session_scope() as session:
        indexing = IndexingService(session).index_corpus(
            corpus_name=suite.corpus_name, strategy=strategy, incremental=True
        )
    log_event(LOGGER, logging.INFO, "bench.suite.indexed", suite=suite.name, ingestion=ingestion, indexing=indexing)

    with session_scope() as session:
        service = RecallBenchmarkService(session, settings)
        try:
            report = service.run(
                corpus_name=suite.corpus_name,
                strategy=strategy,
                dataset_path=suite.dataset_path,
                k_values=tuple(sorted({1, top_k, 10})),
                benchmark_name=suite.name,
                compute_ragas=ragas_limit is not None and ragas_limit > 0,
                ragas_case_limit=ragas_limit,
                judge=judge,
                index_run_id=str(indexing["index_run_id"]),
                retrieval_mode=retrieval_mode,
                rerank=rerank,
            )
        finally:
            service.close()
    return {
        "suite": suite.name,
        "language": suite.language,
        "corpus_name": suite.corpus_name,
        "index_run_id": indexing["index_run_id"],
        "chunks": indexing.get("chunks"),
        "documents": ingestion.get("ingested", 0) + ingestion.get("updated", 0) + ingestion.get("skipped", 0),
        "total_cases": report["total_cases"],
        "summary": report["summary"],
        "by_type": report.get("by_type") or {},
        "report_path": report["report_path"],
        "experiment_run_id": report["experiment_run_id"],
    }


def run_all(
    *,
    label: str,
    strategy: ChunkingStrategy = ChunkingStrategy.TRADITIONAL,
    top_k: int = 5,
    ragas_limit: int | None = 100,
    judge: JudgeConfig | None = None,
    suites: list[str] | None = None,
    repo_root: Path | None = None,
    settings: Settings | None = None,
    retrieval_mode: RetrievalMode | None = None,
    rerank: bool | None = None,
) -> dict[str, Any]:
    from raglab.db import initialize_database, session_scope

    settings = settings or get_settings()
    repo_root = repo_root or Path.cwd()
    judge = judge or JudgeConfig(backend="llamacpp")
    initialize_database()
    with session_scope() as session:
        env = environment_report(settings, session, judge if ragas_limit else None)
    selected = [suite for suite in default_suites(settings, repo_root) if not suites or suite.name in suites]
    mode = RetrievalMode(retrieval_mode or settings.default_retrieval_mode)
    do_rerank = settings.default_rerank if rerank is None else rerank
    results = [
        run_suite(
            suite,
            settings=settings,
            strategy=strategy,
            top_k=top_k,
            ragas_limit=ragas_limit,
            judge=judge,
            retrieval_mode=mode,
            rerank=do_rerank,
        )
        for suite in selected
    ]
    return {
        "label": label,
        "strategy": strategy.value,
        "retrieval_mode": mode.value,
        "rerank": do_rerank,
        **(
            {"rerank_model": settings.rerank_model_name, "rerank_candidates": settings.rerank_candidates}
            if do_rerank
            else {}
        ),
        "top_k": top_k,
        "ragas_limit": ragas_limit,
        "environment": env,
        "suites": results,
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _ms(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} ms".replace(",", " ") if value >= 100 else f"{value:.1f} ms"


def render_markdown(results: list[dict[str, Any]]) -> str:
    """Comparison table across runs (one column per run label), per suite."""
    lines: list[str] = []
    labels = [run["label"] for run in results]
    suite_names = list(dict.fromkeys(s["suite"] for run in results for s in run["suites"]))
    rows = [
        ("Recall@1", "recall@1", _fmt),
        ("Recall@5", "recall@5", _fmt),
        ("Recall@10", "recall@10", _fmt),
        ("MRR", "mrr", _fmt),
        ("Latence requête p50 (embed + recherche + re-ranking)", "latency_query_p50_ms", _ms),
        ("Latence requête p95", "latency_query_p95_ms", _ms),
        ("dont embedding p50", "latency_embed_p50_ms", _ms),
        ("dont recherche pgvector p50", "latency_retrieval_p50_ms", _ms),
        ("dont re-ranking p50", "latency_rerank_p50_ms", _ms),
        ("dont re-ranking p95", "latency_rerank_p95_ms", _ms),
        ("Cache des scores de re-ranking (taux de hit)", "rerank_cache_hit_rate", _fmt),
        ("Génération p50", "latency_generation_p50_ms", _ms),
        ("Génération p95", "latency_generation_p95_ms", _ms),
        ("Débit de génération p50 (tokens/s)", "generation_tokens_per_second_p50", lambda v: _fmt(v, 1)),
        ("Faithfulness", "faithfulness_mean", _fmt),
        ("Answer relevancy", "answer_relevancy_mean", _fmt),
        ("Answer correctness", "answer_correctness_mean", _fmt),
    ]
    for suite_name in suite_names:
        per_run = [next((s for s in run["suites"] if s["suite"] == suite_name), None) for run in results]
        first = next(s for s in per_run if s)
        lines.append(f"### {suite_name} ({first['language']}, {first['total_cases']} questions)")
        lines.append("")
        lines.append("| Métrique | " + " | ".join(labels) + " |")
        lines.append("|---|" + "---|" * len(labels))
        for title, key, fmt in rows:
            values = [fmt(s["summary"].get(key)) if s else "—" for s in per_run]
            if all(v == "—" for v in values):
                continue
            lines.append(f"| {title} | " + " | ".join(values) + " |")
        judged = [s["summary"].get("faithfulness_judged") for s in per_run if s]
        if any(judged):
            lines.append("")
            lines.append(f"Juges RAGAS calculés sur les {max(j or 0 for j in judged)} premières questions.")
        by_type_runs = [s.get("by_type") if s else None for s in per_run]
        if any(by_type_runs):
            types = sorted({t for bt in by_type_runs if bt for t in bt})
            lines.append("")
            lines.append("| Recall@5 / MRR par type | " + " | ".join(labels) + " |")
            lines.append("|---|" + "---|" * len(labels))
            for question_type in types:
                cells = []
                for bt in by_type_runs:
                    row = (bt or {}).get(question_type)
                    cells.append(f"{row['recall@5']:.3f} / {row['mrr']:.3f} ({int(row['cases'])})" if row else "—")
                lines.append(f"| {question_type} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)
