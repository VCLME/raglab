"""Wall-clock latency of full answers, by cache state (review of #83-#85, lot 4).

One process, production settings (the API's defaults: hybrid, re-ranking,
citations, versions in_force, query translation, llama.cpp writer), dedup off
or on. For a list of questions:

1. `cold`: the first question of the process (embedder, re-ranker and, when
   needed, the writer are loaded);
2. `empty`: every question once (re-ranker and translation caches empty for
   them);
3. `warm`: the same questions again (both caches hold them).

Wall time is measured around `QueryService.query` (retrieval + generation).
GPU memory is sampled every 0.5 s; the report gives the peak and the
memory already used by other programs before the run.

    python scripts/latency_profile.py --suite br_expat --dedup off --out <file>.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path


def _gpu_used() -> int | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return int(output.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))]


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "p50_ms": round(statistics.median(values), 1),
        "p95_ms": round(_percentile(values, 0.95), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="br_expat")
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--limit", type=int, default=38)
    parser.add_argument("--dedup", choices=("off", "on"), default="off")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    from raglab.config import get_settings
    from raglab.db.session import get_session_factory
    from raglab.retrieval.service import QueryService

    settings = get_settings()
    corpus = (
        args.corpus
        or {
            "br_expat": "bench_br_expat_pt",
            "lexml_fulltext": "bench_lexml_pt",
            "legi_versions": "bench_legi_consommation_fr",
            "eurlex_compliance": "bench_eurlex_compliance",
        }[args.suite]
    )
    questions = [
        json.loads(line)["question"]
        for line in (Path("benchmarks") / args.suite / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][: args.limit]

    baseline = _gpu_used()
    samples: list[int] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            used = _gpu_used()
            if used is not None:
                samples.append(used)
            time.sleep(0.5)

    threading.Thread(target=sample, daemon=True).start()
    timings: dict[str, list[float]] = {"cold": [], "empty": [], "warm": []}
    stages: dict[str, list[dict]] = {"empty": [], "warm": []}
    with get_session_factory()() as session:
        service = QueryService(session, settings)

        def ask(question: str) -> tuple[float, dict]:
            started = time.perf_counter()
            response = service.query(question=question, corpus_name=corpus, dedup=args.dedup == "on")
            return (time.perf_counter() - started) * 1000, dict(response.timings_ms)

        wall, _ = ask(questions[0])
        timings["cold"].append(wall)
        for state in ("empty", "warm"):
            for question in questions[1:]:
                wall, stage = ask(question)
                timings[state].append(wall)
                stages[state].append(stage)
    stop.set()
    time.sleep(0.6)
    report = {
        "kind": "latency_profile",
        "created_at": datetime.now(UTC).isoformat(),
        "suite": args.suite,
        "corpus": corpus,
        "dedup": args.dedup,
        "questions": len(questions),
        "settings": {
            "default_retrieval_mode": settings.default_retrieval_mode,
            "default_rerank": settings.default_rerank,
            "rerank_device": settings.rerank_device,
            "citation_resolver": settings.citation_resolver,
            "versions_default": settings.versions_default,
            "query_translation": settings.query_translation,
            "default_llm_provider": settings.default_llm_provider,
            "writer_model_profile": settings.writer_model_profile,
        },
        "cold_ms": round(timings["cold"][0], 1),
        "empty": _summary(timings["empty"]),
        "warm": _summary(timings["warm"]),
        "stage_p50_ms": {
            state: {
                key: round(statistics.median(stage[key] for stage in rows if key in stage), 1)
                for key in sorted({key for stage in rows for key in stage})
            }
            for state, rows in stages.items()
        },
        "gpu_memory_mib": {"before": baseline, "peak": max(samples) if samples else None, "samples": len(samples)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cold_ms", "empty", "warm", "gpu_memory_mib")}))


if __name__ == "__main__":
    main()
