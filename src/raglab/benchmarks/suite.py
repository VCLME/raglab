"""`raglab bench all`: rebuild every benchmark number from a single command.

For each suite (PIAF in French, LexML full text in Portuguese, and on
request the Code de la consommation with its version history or the EU
compliance acts in three languages) the runner:

1. makes sure the corpus is on disk (downloads / collects it otherwise) and,
   for LexML, the French code and the EU acts, that every text still matches
   the frozen manifest;
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

from raglab.benchmarks.compare import case_rows
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
    # Run by `raglab bench all` without --suite. The French code is opt-in:
    # it doubles the GPU time of a full run.
    default: bool = True


def default_suites(settings: Settings, repo_root: Path) -> list[Suite]:
    """Suites of `raglab bench all` without `--suite` (the frozen comparison)."""
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
        Suite(
            name="legi_consommation",
            language="fr",
            corpus_name="bench_legi_consommation_fr",
            corpus_dir=settings.legifrance_dir / "consommation" / "corpus",
            dataset_path=repo_root / "benchmarks" / "legi_consommation" / "ground_truth.jsonl",
            manifest_path=repo_root / "benchmarks" / "legi_consommation" / "corpus_manifest.json",
            default=False,
        ),
        # EU compliance acts (GDPR, AI Act, DORA, NIS 2 and the acts that
        # complete them) in French, English and Portuguese: run when named,
        # `--suite eurlex_compliance`.
        Suite(
            name="eurlex_compliance",
            language="multi",
            corpus_name="bench_eurlex_compliance",
            corpus_dir=settings.eurlex_dir / "compliance" / "corpus",
            dataset_path=repo_root / "benchmarks" / "eurlex_compliance" / "ground_truth.jsonl",
            manifest_path=repo_root / "benchmarks" / "eurlex_compliance" / "corpus_manifest.json",
            default=False,
        ),
        # Questions whose answer is in the article cited by another (9.9b), on
        # the LexML corpus: run when named, `--suite lexml_references`.
        Suite(
            name="lexml_references",
            language="pt",
            corpus_name="bench_lexml_pt",
            corpus_dir=settings.lexml_fulltext_dir / "corpus",
            dataset_path=repo_root / "benchmarks" / "lexml_references" / "ground_truth.jsonl",
            manifest_path=repo_root / "benchmarks" / "lexml_fulltext" / "corpus_manifest.json",
            default=False,
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
    elif suite.name in ("lexml_fulltext", "lexml_references"):
        from raglab.lexml.fulltext import FullTextCollector

        FullTextCollector(settings).collect(
            output_dir=suite.corpus_dir.parent, years=range(1988, 2025), per_year=7, seed=42
        )
    elif suite.name == "legi_consommation":
        from raglab.legifrance.collector import CodeCollector

        CodeCollector(settings).collect(code="consommation", output_dir=suite.corpus_dir.parent)
    elif suite.name == "eurlex_compliance":
        from raglab.eurlex.collector import EurlexCollector

        EurlexCollector(settings).collect(output_dir=suite.corpus_dir.parent)
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


def _total_ram() -> str:
    """Physical memory in GiB, without extra dependencies."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            total = status.ullTotalPhys
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return f"{total / 2**30:.0f} GiB"
    except (OSError, ValueError, AttributeError):
        return "unknown"


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
    ram = _total_ram()
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


def _reusable_index_run(session: Any, corpus_name: str, strategy: ChunkingStrategy, settings: Settings):
    from raglab.db.crud import resolve_latest_index_run

    run = resolve_latest_index_run(session, corpus_name=corpus_name, strategy=strategy, backend="pgvector")
    if run is None:
        return None
    space = run.embedding_space
    if (space.provider, space.model_name) != (settings.embedding_provider, settings.embedding_model_name):
        return None
    if (run.chunk_size, run.chunk_overlap) != (settings.chunk_size, settings.chunk_overlap):
        return None
    # The ingestion summary counts every existing document as "updated";
    # whether the run is stale is decided by the documents' own timestamps
    # and by the run covering every document of the corpus.
    stale = session.execute(
        text(
            "SELECT count(*) FILTER (WHERE d.updated_at > :started) AS changed, "
            "count(*) AS total, "
            "(SELECT count(DISTINCT document_id) FROM chunks WHERE index_run_id = :run) AS covered "
            "FROM documents d WHERE d.corpus_id = :corpus"
        ),
        {"started": run.started_at, "run": run.id, "corpus": run.corpus_id},
    ).one()
    if stale.changed or stale.covered != stale.total:
        return None
    return run


def run_suite(
    suite: Suite,
    *,
    settings: Settings,
    strategy: ChunkingStrategy,
    top_k: int,
    ragas_limit: int | None,
    judge: JudgeConfig | None,
    retrieval_mode: RetrievalMode | str | None = None,
    lexical_weight: float | None = None,
    rrf_k: int | None = None,
    rerank: bool | None = None,
    citations: bool | None = None,
    graph: bool | None = None,
) -> dict[str, Any]:
    from raglab.db import session_scope
    from raglab.experiments.recall import RecallBenchmarkService
    from raglab.indexing.service import IndexingService
    from raglab.ingestion.service import IngestionService

    if not suite.dataset_path.exists():
        raise RuntimeError(
            f"Pas de jeu de questions pour la suite {suite.name} ({suite.dataset_path}). "
            "Voir docs/benchmarks/protocole.md pour le generer."
        )
    _ensure_corpus(suite, settings)
    problems = verify_manifest(suite.corpus_dir, suite.manifest_path) if suite.manifest_path else []
    if problems:
        raise RuntimeError(
            f"Le corpus {suite.name} ne correspond plus au manifeste fige ({len(problems)} fichiers, ex. {problems[:3]}). "
            "Les positions des reponses attendues ne sont plus fiables."
        )

    with session_scope() as session:
        ingestion = IngestionService(session).ingest_folder(
            suite.corpus_dir,
            corpus_name=suite.corpus_name,
            description=f"Benchmark {suite.name} (fige)",
            language=suite.language,
        )
    with session_scope() as session:
        reusable = None
        if not ingestion.get("ingested"):
            reusable = _reusable_index_run(session, suite.corpus_name, strategy, settings)
        if reusable is not None:
            # Same documents, same chunking and embedding: re-indexing would
            # only duplicate embeddings, which bloats the shared HNSW index
            # and slows every search a little more on each benchmark run.
            indexing = {"index_run_id": reusable.id, "chunks": len(reusable.chunks), "reused_run": True}
        else:
            indexing = IndexingService(session).index_corpus(
                corpus_name=suite.corpus_name, strategy=strategy, incremental=True
            )
        documents = session.execute(
            text("SELECT count(*) FROM documents d JOIN corpora c ON c.id = d.corpus_id WHERE c.name = :name"),
            {"name": suite.corpus_name},
        ).scalar_one()
    log_event(LOGGER, logging.INFO, "bench.suite.indexed", suite=suite.name, ingestion=ingestion, indexing=indexing)
    graph_build: dict[str, Any] | None = None
    if graph or (graph is None and settings.graph_retrieval):
        from raglab.graph.structured import ensure_graph

        # A reused index run may predate its graph or the current rules.
        with session_scope() as session:
            graph_build = ensure_graph(session, str(indexing["index_run_id"]), settings=settings)
        log_event(LOGGER, logging.INFO, "bench.suite.graph", suite=suite.name, status=graph_build.get("status"))

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
                lexical_weight=lexical_weight,
                rrf_k=rrf_k,
                rerank=rerank,
                citations=citations,
                graph=graph,
            )
        finally:
            service.close()
    return {
        "suite": suite.name,
        "language": suite.language,
        "corpus_name": suite.corpus_name,
        "index_run_id": indexing["index_run_id"],
        "chunks": indexing.get("chunks"),
        "documents": documents,
        "total_cases": report["total_cases"],
        "retrieval_mode": report.get("retrieval_mode"),
        "lexical_weight": report.get("lexical_weight"),
        "rrf_k": report.get("rrf_k"),
        "rerank": report.get("rerank"),
        "citations": report.get("citations"),
        "graph": report.get("graph"),
        "graph_notices": report.get("graph_notices"),
        **({"graph_build": graph_build.get("status")} if graph_build else {}),
        "summary": report["summary"],
        "by_type": report.get("by_type") or {},
        **({"by_split": report["by_split"]} if report.get("by_split") else {}),
        "report_path": report["report_path"],
        "experiment_run_id": report["experiment_run_id"],
        # Per-question outcomes, so two runs can be compared question by
        # question (`raglab bench compare`) without the local reports.
        "cases": case_rows(report),
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
    retrieval_mode: RetrievalMode | str | None = None,
    lexical_weight: float | None = None,
    rrf_k: int | None = None,
    rerank: bool | None = None,
    citations: bool | None = None,
    graph: bool | None = None,
) -> dict[str, Any]:
    from raglab.db import initialize_database, session_scope

    settings = settings or get_settings()
    repo_root = repo_root or Path.cwd()
    judge = judge or JudgeConfig(backend="llamacpp")
    initialize_database()
    with session_scope() as session:
        env = environment_report(settings, session, judge if ragas_limit else None)
    known = default_suites(settings, repo_root)
    unknown = sorted(set(suites or []) - {suite.name for suite in known})
    if unknown:
        raise ValueError(f"Suite inconnue: {', '.join(unknown)}. Suites: {', '.join(s.name for s in known)}")
    selected = [suite for suite in known if suite.name in suites] if suites else [s for s in known if s.default]
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
            lexical_weight=lexical_weight,
            rrf_k=rrf_k,
            rerank=do_rerank,
            citations=citations,
            graph=graph,
        )
        for suite in selected
    ]
    return {
        "label": label,
        "strategy": strategy.value,
        "retrieval_mode": mode.value,
        "rerank": do_rerank,
        "graph": settings.graph_retrieval if graph is None else graph,
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


def _with_ci(fmt: Any, summary: dict[str, Any], key: str) -> str:
    text = fmt(summary.get(key))
    low, high = summary.get(f"{key}_ci_low"), summary.get(f"{key}_ci_high")
    if low is None or high is None or text == "—":
        return text
    return f"{text} [{low:.2f}–{high:.2f}]"


def _retrieval_label(run: dict[str, Any], suite: dict[str, Any] | None) -> str:
    # Results written before hybrid retrieval carry no mode: they were dense.
    mode = (suite or {}).get("retrieval_mode") or run.get("retrieval_mode") or "dense"
    if mode == "hybrid" and suite:
        mode = f"hybrid (w={suite.get('lexical_weight')}, k={suite.get('rrf_k')})"
    if (suite or {}).get("rerank", run.get("rerank")):
        mode += f" + rerank ({run.get('rerank_candidates', '?')})"
    if (suite or {}).get("graph", run.get("graph")):
        mode += " + graph"
    return mode


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
        ("dont recherche p50", "latency_retrieval_p50_ms", _ms),
        ("dont vectoriel p50 (hybrid)", "latency_dense_p50_ms", _ms),
        ("dont BM25 p50", "latency_lexical_p50_ms", _ms),
        ("dont BM25 p95", "latency_lexical_p95_ms", _ms),
        ("dont fusion RRF p50", "latency_fusion_p50_ms", _ms),
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
        modes = [_retrieval_label(run, s) for run, s in zip(results, per_run, strict=True)]
        lines.append("| Retrieval | " + " | ".join(modes) + " |")
        for title, key, fmt in rows:
            values = [_with_ci(fmt, s["summary"], key) if s else "—" for s in per_run]
            if all(v == "—" for v in values):
                continue
            lines.append(f"| {title} | " + " | ".join(values) + " |")
        judged = [s["summary"].get("faithfulness_judged") for s in per_run if s]
        if any(judged):
            lines.append("")
            lines.append(f"Juges RAGAS calculés sur les {max(j or 0 for j in judged)} premières questions.")
        # Per question type, and per split (dev / heldout) for sets that have one.
        for key, heading in (("by_type", "par type"), ("by_split", "par partie du jeu")):
            group_runs = [s.get(key) if s else None for s in per_run]
            if not any(group_runs):
                continue
            groups = sorted({g for runs in group_runs if runs for g in runs})
            lines.append("")
            lines.append(f"| Recall@5 / MRR {heading} | " + " | ".join(labels) + " |")
            lines.append("|---|" + "---|" * len(labels))
            for group in groups:
                cells = []
                for runs in group_runs:
                    row = (runs or {}).get(group)
                    cells.append(f"{row['recall@5']:.3f} / {row['mrr']:.3f} ({int(row['cases'])})" if row else "—")
                lines.append(f"| {group} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)
