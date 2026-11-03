"""Measure what phase 9.3 (cross-encoder re-ranking) changes, on the GPU.

For each first-stage mode (dense, hybrid by default) the frozen PIAF and
LexML sets are run through `raglab bench all` twice, without and with
`--rerank`, retrieval only (no generation, no judge). The script then reports:

1. Recall@1/5/10 and MRR before / after, per suite and per question type;
2. the latency added by the cross-encoder (`rerank` stage p50 / p95, and the
   query latency embed + search + rerank);
3. the GPU memory: used with qwen2.5:7b loaded in Ollama, peak while the
   reranker scores next to it, and after `release()`.

qwen2.5:7b is loaded in Ollama first and kept resident for the whole run, as
in production. Each rerank run starts with an empty score cache and a model
already loaded, so the latency is the model's, not the cache's or the disk's.

The database must already hold the indexed `bench_*` corpora (a copy of the
baseline database migrated to 0002, so the baseline is never touched) and the
data directories must be those the corpora were ingested from: ingestion then
skips every document and nothing is re-embedded.

Usage (from the repository root, with a CUDA build of torch):

    python scripts/bench_reranking.py --label v0 --data-root <worktree>/data --dry-run
    python scripts/bench_reranking.py --label v0 --data-root <worktree>/data

Writes benchmarks/results/rerank-<label>-<mode>[-rerank].json for each run and
benchmarks/results/rerank-<label>.md / .json with the comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_DATABASE_URL = "postgresql+psycopg://raglab:raglab@localhost:5432/raglab_rerank"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="Run label, e.g. v0.")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="data/ directory the bench_* corpora were ingested from (benchmarks/piaf/corpus, lexml/fulltext/corpus).",
    )
    parser.add_argument("--modes", default="dense,hybrid", help="First-stage modes, comma separated.")
    parser.add_argument("--suite", action="append", help="piaf and/or lexml_fulltext (default: both).")
    parser.add_argument("--candidates", type=int, default=None, help="Override RAGLAB_RERANK_CANDIDATES.")
    parser.add_argument("--idle-mib", type=int, default=1200, help="GPU memory above which the GPU counts as busy.")
    parser.add_argument("--no-qwen", action="store_true", help="Do not load qwen2.5:7b next to the reranker.")
    parser.add_argument("--force", action="store_true", help="Run even if the GPU looks busy.")
    parser.add_argument("--dry-run", action="store_true", help="Check inputs only; never touches the GPU.")
    return parser.parse_args()


ARGS = parse_args()

# Settings are read once, from the environment, on first import of raglab.
os.environ["RAGLAB_DATABASE_URL"] = ARGS.database_url
os.environ["RAGLAB_DATA_DIR"] = str(ARGS.data_root.resolve())
os.environ["RAGLAB_LEXML_FULLTEXT_DIR"] = str((ARGS.data_root / "lexml" / "fulltext").resolve())
os.environ["RAGLAB_RERANK_DEVICE"] = "cuda"
os.environ.setdefault("RAGLAB_LOG_LEVEL", "WARNING")
if ARGS.candidates is not None:
    os.environ["RAGLAB_RERANK_CANDIDATES"] = str(ARGS.candidates)

import requests  # noqa: E402

from raglab.benchmarks.suite import default_suites, render_markdown, run_all, verify_manifest  # noqa: E402
from raglab.config import get_settings  # noqa: E402
from raglab.db import session_scope  # noqa: E402
from raglab.domain.enums import RetrievalMode  # noqa: E402
from raglab.retrieval import rerank as rerank_module  # noqa: E402

RESULTS_DIR = Path("benchmarks/results")


def gpu_memory_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return int(out.strip().splitlines()[0])
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def llama_server_running() -> bool:
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, check=True).stdout.lower()
    except (OSError, subprocess.CalledProcessError):
        return False
    return "llama-server" in out


def ollama_loaded(base_url: str) -> list[str]:
    try:
        return [m.get("name", "?") for m in requests.get(f"{base_url}/api/ps", timeout=5).json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []


def ollama_keep_alive(base_url: str, model: str, keep_alive: str | int) -> None:
    """Load (keep_alive > 0) or unload (0) a model without generating."""
    response = requests.post(
        f"{base_url}/api/generate", json={"model": model, "prompt": "", "keep_alive": keep_alive}, timeout=600
    )
    response.raise_for_status()


class VramSampler:
    """Polls nvidia-smi in the background and keeps the maximum."""

    def __init__(self, interval_s: float = 0.25):
        self.interval_s = interval_s
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            used = gpu_memory_used_mib()
            if used is not None:
                self.peak = max(self.peak, used)
            self._stop.wait(self.interval_s)

    def __enter__(self) -> VramSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def preflight(settings: Any, suites: list[str] | None) -> list[str]:
    """Inputs the runs need; returns the problems found (empty = ready)."""
    problems: list[str] = []
    repo_root = Path.cwd()
    for suite in default_suites(settings, repo_root):
        if suites and suite.name not in suites:
            continue
        if not suite.dataset_path.exists():
            problems.append(f"{suite.name}: ground truth absente ({suite.dataset_path})")
        if not any(suite.corpus_dir.glob("*.txt")):
            problems.append(f"{suite.name}: corpus absent ({suite.corpus_dir})")
        elif suite.manifest_path and verify_manifest(suite.corpus_dir, suite.manifest_path):
            problems.append(f"{suite.name}: corpus different du manifeste")
    from sqlalchemy import text

    with session_scope() as session:
        rows = session.execute(
            text(
                "SELECT c.name, count(ch.id) FROM corpora c JOIN index_runs ir ON ir.corpus_id = c.id "
                "JOIN chunks ch ON ch.index_run_id = ir.id WHERE c.name LIKE 'bench_%' "
                "AND ch.lexical_tsv IS NOT NULL GROUP BY c.name"
            )
        ).all()
    indexed = {name: count for name, count in rows}
    for suite in default_suites(settings, repo_root):
        if (not suites or suite.name in suites) and not indexed.get(suite.corpus_name):
            problems.append(f"{suite.corpus_name}: pas d'index avec tsvector dans {settings.database_url}")
    try:
        from huggingface_hub import try_to_load_from_cache

        if not isinstance(try_to_load_from_cache(settings.rerank_model_name, "config.json"), str):
            problems.append(f"{settings.rerank_model_name} absent du cache Hugging Face")
    except ImportError:
        problems.append("huggingface_hub absent")
    import torch

    if not torch.version.cuda:
        problems.append(f"torch {torch.__version__} sans CUDA")
    return problems


def gpu_busy(settings: Any) -> list[str]:
    reasons: list[str] = []
    used = gpu_memory_used_mib()
    if used is None:
        reasons.append("nvidia-smi indisponible")
    elif used > ARGS.idle_mib:
        reasons.append(f"{used} MiB deja utilises sur le GPU (seuil {ARGS.idle_mib})")
    loaded = ollama_loaded(settings.ollama_base_url)
    if loaded:
        reasons.append(f"Ollama a des modeles charges: {loaded}")
    if llama_server_running():
        reasons.append("llama-server tourne")
    return reasons


def warm_reranker(settings: Any) -> None:
    """Fresh score cache, weights already on the GPU before the timed run."""
    import torch

    rerank_module.clear_rerankers()
    reranker = rerank_module.get_reranker(settings)
    reranker.scorer.score("echauffement", ["echauffement"])
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()


def run_label(mode: str, rerank: bool) -> str:
    return f"rerank-{ARGS.label}-{mode}{'-rerank' if rerank else ''}"


def compare(results: dict[str, dict[str, Any]], modes: list[str]) -> list[str]:
    lines = ["| Suite | Mode | Recall@5 | Δ | Recall@10 | Δ | MRR | Δ | rerank p50 / p95 | requête p50 / p95 |"]
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for mode in modes:
        before, after = results[run_label(mode, False)], results[run_label(mode, True)]
        for suite_before in before["suites"]:
            suite_after = next(s for s in after["suites"] if s["suite"] == suite_before["suite"])
            b, a = suite_before["summary"], suite_after["summary"]

            def cell(key: str, a: dict = a, b: dict = b) -> str:
                return f"{b[key]:.3f} → {a[key]:.3f} | {a[key] - b[key]:+.3f}"

            lines.append(
                f"| {suite_before['suite']} | {mode} | {cell('recall@5')} | {cell('recall@10')} | {cell('mrr')} | "
                f"{a.get('latency_rerank_p50_ms', 0):.0f} / {a.get('latency_rerank_p95_ms', 0):.0f} ms | "
                f"{b['latency_query_p50_ms']:.0f} / {b['latency_query_p95_ms']:.0f} → "
                f"{a['latency_query_p50_ms']:.0f} / {a['latency_query_p95_ms']:.0f} ms |"
            )
    return lines


def main() -> int:
    settings = get_settings()
    modes = [RetrievalMode(mode.strip()).value for mode in ARGS.modes.split(",") if mode.strip()]
    problems = preflight(settings, ARGS.suite)
    busy = gpu_busy(settings)
    print(f"Base: {settings.database_url.rsplit('/', 1)[-1]} · donnees: {settings.data_dir}")
    print(f"Reranker: {settings.rerank_model_name} · {settings.rerank_candidates} candidats")
    for problem in problems:
        print(f"  [entree] {problem}")
    for reason in busy:
        print(f"  [GPU] {reason}")
    if ARGS.dry_run:
        print("Dry run: rien n'a ete lance." + (" Pret." if not problems else ""))
        return 1 if problems else 0
    if problems:
        return 1
    if busy and not ARGS.force:
        print("GPU occupe: relancer quand il est libre, ou --force.")
        return 2

    import torch

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    vram: dict[str, Any] = {"idle_mib": gpu_memory_used_mib()}
    results: dict[str, dict[str, Any]] = {}
    qwen = not ARGS.no_qwen
    started = time.perf_counter()
    try:
        if qwen:
            ollama_keep_alive(settings.ollama_base_url, settings.generation_model, "2h")
            time.sleep(2)
            vram["with_qwen_mib"] = gpu_memory_used_mib()
        # Without rerank first: nothing of ours on the GPU yet.
        for mode in modes:
            label = run_label(mode, False)
            results[label] = run_all(
                label=label, ragas_limit=None, suites=ARGS.suite, retrieval_mode=RetrievalMode(mode)
            )
        with VramSampler() as sampler:
            for mode in modes:
                warm_reranker(settings)
                vram.setdefault("after_load_mib", gpu_memory_used_mib())
                label = run_label(mode, True)
                results[label] = run_all(
                    label=label, ragas_limit=None, suites=ARGS.suite, retrieval_mode=RetrievalMode(mode), rerank=True
                )
                vram[f"torch_peak_allocated_mib_{mode}"] = round(torch.cuda.max_memory_allocated() / 2**20)
                vram[f"torch_peak_reserved_mib_{mode}"] = round(torch.cuda.max_memory_reserved() / 2**20)
        vram["peak_mib"] = sampler.peak
        rerank_module.release_rerankers()
        time.sleep(2)
        vram["after_release_mib"] = gpu_memory_used_mib()
    finally:
        rerank_module.clear_rerankers()
        if qwen:
            try:
                ollama_keep_alive(settings.ollama_base_url, settings.generation_model, 0)
            except requests.RequestException as exc:
                print(f"Ollama: dechargement impossible ({exc})", file=sys.stderr)

    for label, result in results.items():
        (RESULTS_DIR / f"{label}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    gpu = next(iter(results.values()))["environment"]["gpu"]
    report = [
        f"# Re-ranking cross-encoder — {ARGS.label}",
        "",
        f"{settings.rerank_model_name}, fp16, {settings.rerank_candidates} candidats, lots de "
        f"{settings.rerank_batch_size}, {settings.rerank_max_length} tokens max. GPU : {gpu}. "
        f"{'qwen2.5:7b chargé dans Ollama pendant toute la mesure. ' if qwen else ''}"
        "Cache des scores vidé avant chaque run, modèle déjà chargé. Retrieval seul (ni génération ni juge).",
        "",
        "## Avant / après",
        "",
        *compare(results, modes),
        "",
        "## Mémoire GPU (nvidia-smi, MiB)",
        "",
        "| Moment | Utilisée |",
        "|---|---|",
        f"| GPU au repos | {vram.get('idle_mib')} |",
        *([f"| qwen2.5:7b chargé | {vram.get('with_qwen_mib')} |"] if qwen else []),
        f"| + reranker chargé | {vram.get('after_load_mib')} |",
        f"| pic pendant le re-ranking | {vram.get('peak_mib')} |",
        f"| après `release()` | {vram.get('after_release_mib')} |",
        "",
        "Pic alloué par torch (poids + activations) : "
        + ", ".join(f"{m} {vram.get(f'torch_peak_allocated_mib_{m}')} MiB" for m in modes)
        + " ; réservé : "
        + ", ".join(f"{m} {vram.get(f'torch_peak_reserved_mib_{m}')} MiB" for m in modes)
        + ".",
        "",
        "## Détail par run",
        "",
        render_markdown(list(results.values())),
        "",
        f"Durée totale : {(time.perf_counter() - started) / 60:.1f} min.",
    ]
    markdown = "\n".join(report)
    (RESULTS_DIR / f"rerank-{ARGS.label}.md").write_text(markdown + "\n", encoding="utf-8")
    (RESULTS_DIR / f"rerank-{ARGS.label}.json").write_text(
        json.dumps({"label": ARGS.label, "modes": modes, "vram_mib": vram, "runs": list(results)}, indent=2),
        encoding="utf-8",
    )
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
