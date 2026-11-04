"""Multilingual routing study (docs/routage-multilingue.md).

The router decides two things on the question embedding: the corpus (before
retrieval) and the abstention (after it). Both were measured wrong for a
question asked in another language than its corpus (docs/langues-croisees.md).
This study compares fixes without a new LLM in the router.

One GPU pass (`collect`) routes nothing: it retrieves every evaluated
question on **every** candidate corpus, with the production pipeline (hybrid,
re-ranking, citations, query translation), and records each score the
policies read: chunk-centroid and example-centroid similarities (original and
translated question), dense cosine (original and translated), re-ranker
score, whether the expected passage came back, and the stage timings.
Calibration questions, disjoint from the evaluated ones, are retrieved on
their own corpus only. `replay` then applies any routing policy and
abstention policy to those records offline, so every approach is compared on
exactly the same retrievals.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from raglab.benchmarks.compare import mcnemar_exact
from raglab.config import Settings, get_settings
from raglab.domain.enums import ChunkingStrategy
from raglab.experiments.recall import _chunk_covers_span, _percentile
from raglab.experiments.routing import (
    EXTRA_SETS,
    IN_SCOPE_SETS,
    MAX_FALSE_ABSTENTION,
    REPO_ROOT,
    SELECTED_INTENT_MARGIN,
    InScopeSet,
    RoutingCase,
    _read_jsonl,
    load_cases,
    quantile,
)
from raglab.llm.local_server import LocalLLMServer
from raglab.retrieval.service import QueryService
from raglab.retrieval.translation import LANGUAGE_NAMES
from raglab.routing.abstention import best_score
from raglab.routing.citation import cited_text_in_run
from raglab.routing.corpus import index_run_centroid, list_candidate_runs
from raglab.routing.corpus_examples import example_centroids, load_corpus_examples
from raglab.routing.intent import decide_intent, normalize
from raglab.routing.router import QueryRouter
from raglab.routing.schemas import Intent
from raglab.routing.step import translated_dense_score

# The evaluated sets of #76, in the same order (the in-scope draw shares one
# seeded generator across sets, so the order fixes which PIAF questions come).
EVALUATED_SETS: tuple[InScopeSet, ...] = (
    EXTRA_SETS["lexml_fr"],
    EXTRA_SETS["lexml_fr_pt"],
    next(s for s in IN_SCOPE_SETS if s.name == "piaf"),
)


@dataclass(frozen=True)
class CalibrationSet:
    name: str
    path: Path
    corpus_name: str
    language: str
    # Drawn (seeded) from a frozen set, excluding the evaluated ids; None =
    # the whole file, disjoint by construction.
    size: int | None = None


# Calibration questions: per-language abstention thresholds and the example
# questions behind the corpus centroids of approach (c). Never evaluated.
CALIBRATION_SETS: tuple[CalibrationSet, ...] = (
    CalibrationSet("piaf", REPO_ROOT / "benchmarks" / "piaf" / "ground_truth.jsonl", "bench_piaf_fr", "fr", 100),
    CalibrationSet(
        "lexml_fr_calibration", REPO_ROOT / "benchmarks" / "lexml_fr" / "calibration.jsonl", "bench_lexml_pt", "fr"
    ),
    CalibrationSet(
        "lexml_pt_calibration", REPO_ROOT / "benchmarks" / "lexml_fr" / "calibration_pt.jsonl", "bench_lexml_pt", "pt"
    ),
)


def load_calibration_cases(exclude_ids: set[str], seed: int) -> list[RoutingCase]:
    cases: list[RoutingCase] = []
    rng = random.Random(seed)
    for calibration in CALIBRATION_SETS:
        rows = sorted(
            (
                row
                for row in _read_jsonl(calibration.path)
                if row.get("review_status") != "rejected" and row["id"] not in exclude_ids
            ),
            key=lambda row: row["id"],
        )
        if calibration.size is not None:
            rows = rng.sample(rows, min(calibration.size, len(rows)))
        cases.extend(
            RoutingCase(
                id=row["id"],
                question=row["question"],
                category="in_scope",
                language=calibration.language,
                source=calibration.name,
                subtype=row.get("question_type"),
                expected_corpus=calibration.corpus_name,
            )
            for row in rows
        )
    return cases


def write_examples(cases: Iterable[RoutingCase], path: Path) -> None:
    """Calibration questions as corpus examples (`corpus`, `language`, `question`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(
                json.dumps(
                    {
                        "corpus": case.expected_corpus,
                        "language": case.language,
                        "id": case.id,
                        "question": case.question,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _example_scores(centroids: dict[str, dict[str, np.ndarray]], vector: np.ndarray) -> dict[str, dict[str, float]]:
    return {
        corpus: {language: round(float(centroid @ vector), 4) for language, centroid in by_language.items()}
        for corpus, by_language in centroids.items()
    }


class MultilingualRoutingStudy:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()

    def collect(
        self,
        *,
        corpora: list[str],
        strategy: ChunkingStrategy | None = None,
        sample_size: int = 300,
        seed: int = 42,
        top_k: int = 5,
        examples_path: Path | None = None,
    ) -> dict[str, Any]:
        cases = load_cases(in_scope_sets=EVALUATED_SETS, sample_size=sample_size, seed=seed)
        calibration_cases = load_calibration_cases({case.id for case in cases}, seed + 1)
        examples_path = examples_path or self.settings.routing_corpus_examples_path
        write_examples(calibration_cases, examples_path)
        router = QueryRouter(self.session, self.settings)
        retriever = QueryService(self.session, self.settings)
        embedder = router.embedder
        centroids = example_centroids(load_corpus_examples(examples_path), embedder)
        router.route("warm-up", strategy=strategy, candidate_corpora=corpora)
        runs = {
            run.corpus.name: run
            for run in list_candidate_runs(
                self.session,
                provider=self.settings.embedding_provider,
                model_name=self.settings.embedding_model_name,
                query_prefix=self.settings.query_prefix,
                strategy=strategy,
                corpus_names=corpora,
            )
        }
        languages = {name: run.corpus.language for name, run in runs.items()}
        chunk_centroids = {name: index_run_centroid(self.session, run) for name, run in runs.items()}

        def retrieve(case: RoutingCase, corpus: str, citation: Any = None) -> dict[str, Any]:
            run = runs[corpus]
            outcome = retriever.retrieve(question=case.question, index_run_id=run.id, top_k=top_k)
            chunks = [chunk.model_dump() for chunk in outcome.retrieved]
            translation = outcome.query_translation or {}
            entry: dict[str, Any] = {
                "dense": best_score(outcome.retrieved, "dense"),
                "rerank": best_score(outcome.retrieved, "rerank"),
                "hit": any(_chunk_covers_span(chunk, span) for chunk in chunks for span in case.expected_spans),
                "timings_ms": dict(outcome.timings_ms),
                "translated": bool(translation.get("translated")),
                "translation_ms": float(translation.get("elapsed_ms") or 0.0),
                # Same rule as the router: a cited text this index holds is never declined.
                "legal_citation_found": citation is not None and cited_text_in_run(self.session, run, citation),
            }
            if translation.get("translated"):
                started = datetime.now(UTC)
                entry["dense_translated"] = translated_dense_score(retriever, outcome)
                entry["translated_dense_ms"] = round((datetime.now(UTC) - started).total_seconds() * 1000, 3)
                vector = normalize(embedder.embed_query(translation["text"]))
                centroid = chunk_centroids[corpus]
                entry["translation_text"] = translation["text"]
                entry["chunk_centroid_translated"] = (
                    round(float(centroid @ vector), 4) if centroid is not None else None
                )
                entry["examples_translated"] = _example_scores(centroids, vector)
            return entry

        records: list[dict[str, Any]] = []
        calibration: list[dict[str, Any]] = []
        writer = ExitStack()
        if self.settings.query_translation:
            writer.enter_context(LocalLLMServer(self.settings, profile=self.settings.writer_model_profile))
        with writer:
            for case in cases:
                decision = router.route(case.question, strategy=strategy, candidate_corpora=corpora)
                vector = normalize(decision.query_embedding)
                records.append(
                    {
                        **{k: v for k, v in asdict(case).items() if k != "expected_spans"},
                        "language_detected": decision.language.language,
                        "intent_scores": decision.intent.scores,
                        "legal_citation": decision.legal_citation,
                        "chunk_centroid": {c.corpus_name: c.score for c in decision.corpus.candidates},
                        "examples": _example_scores(centroids, vector),
                        "router_ms": decision.timings_ms,
                        "corpora": {corpus: retrieve(case, corpus, decision.citation) for corpus in runs},
                    }
                )
            for case in calibration_cases:
                calibration.append(
                    {
                        "id": case.id,
                        "source": case.source,
                        "language": case.language,
                        "corpus": case.expected_corpus,
                        **{
                            k: v
                            for k, v in retrieve(case, case.expected_corpus or "").items()
                            if k in ("dense", "dense_translated", "rerank", "translated")
                        },
                    }
                )
        report = {
            "kind": "routing_languages",
            "created_at": datetime.now(UTC).isoformat(),
            "config": {
                "corpora": corpora,
                "corpus_languages": languages,
                "sample_size": sample_size,
                "seed": seed,
                "top_k": top_k,
                "in_scope_sets": [s.name for s in EVALUATED_SETS],
                "calibration_sets": [
                    {"name": c.name, "corpus": c.corpus_name, "language": c.language, "size": c.size}
                    for c in CALIBRATION_SETS
                ],
                "calibration_counts": dict(Counter(c.source for c in calibration_cases)),
                "retrieval_mode": self.settings.default_retrieval_mode,
                "rerank": self.settings.default_rerank,
                "citations": self.settings.citation_resolver,
                "query_translation": self.settings.query_translation,
                "intent_margin": self.settings.routing_intent_margin,
                "abstention_thresholds": self.settings.routing_abstention_thresholds,
                "rerank_abstention_thresholds": self.settings.routing_rerank_abstention_thresholds,
                "embedding_model": self.settings.embedding_model_name,
            },
            "records": records,
            "calibration": calibration,
        }
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.reports_dir / f"routing-languages-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["report_path"] = str(path)
        return report


# ---------------------------------------------------------------- replay


@dataclass(frozen=True)
class RoutingPolicy:
    """`centroids`: "chunks" (production) or "examples" (approach c).
    `margin`: cross-language rescoring margin (#76), None = off."""

    centroids: str = "chunks"
    margin: float | None = None

    @property
    def label(self) -> str:
        base = "centroïdes des passages" if self.centroids == "chunks" else "questions exemples"
        return base + (f" + re-notation {self.margin:g}" if self.margin is not None else "")


@dataclass(frozen=True)
class AbstentionPolicy:
    """`score`: dense (original question), dense_xl (better of original and
    translated, #76) or rerank. `thresholds`: "production" (settings),
    "corpus" (calibrated per corpus on questions in the corpus language),
    "language" (per language and corpus, approach a) or "zscore" (approach b)."""

    score: str = "dense_xl"
    thresholds: str = "production"
    # Calibration quantile ("corpus", "language") or z value ("zscore").
    level: float | None = None

    @property
    def label(self) -> str:
        names = {"dense": "dense", "dense_xl": "dense max(orig, trad.)", "rerank": "re-ranker"}
        if self.thresholds == "production":
            return f"{names[self.score]}, seuils de production"
        if self.thresholds == "zscore":
            return f"{names[self.score]}, z-score par (langue, corpus), z = {self.level:g}"
        scope = "par corpus" if self.thresholds == "corpus" else "par (langue, corpus)"
        return f"{names[self.score]}, {scope}, q{self.level:g}"


def _record_score(entry: dict[str, Any], source: str) -> float | None:
    if source == "rerank":
        return entry.get("rerank")
    original = entry.get("dense")
    if source == "dense":
        return original
    translated = entry.get("dense_translated")
    if translated is None:
        return original
    return translated if original is None else max(original, translated)


def corpus_scores(record: dict[str, Any], policy: RoutingPolicy, languages: dict[str, str]) -> dict[str, float]:
    """Score of each candidate corpus under the routing policy (as the router would compute it)."""

    def base(corpus: str, translated: bool = False) -> float | None:
        entry = record["corpora"][corpus]
        if policy.centroids == "chunks":
            return entry.get("chunk_centroid_translated") if translated else record["chunk_centroid"].get(corpus)
        scores = entry.get("examples_translated") if translated else record["examples"]
        by_language = (scores or {}).get(corpus) or {}
        return max(by_language.values()) if by_language else None

    raw = {corpus: base(corpus) for corpus in record["corpora"]}
    scores = {corpus: value for corpus, value in raw.items() if value is not None}
    if policy.margin is None or not scores:
        return scores
    best = max(scores.values())
    language = record["language_detected"]
    rescored = dict(scores)
    for corpus, value in scores.items():
        target = languages.get(corpus)
        entry = record["corpora"][corpus]
        if (
            target in LANGUAGE_NAMES
            and language in LANGUAGE_NAMES
            and target != language
            and value >= best - policy.margin
            and entry.get("translated")
        ):
            translated = base(corpus, translated=True)
            if translated is not None:
                rescored[corpus] = max(value, translated)
    return rescored


def rescored_corpora(record: dict[str, Any], policy: RoutingPolicy, languages: dict[str, str]) -> list[str]:
    """Corpora whose score needed the translated question (the router's writer call)."""
    if policy.margin is None:
        return []
    plain = corpus_scores(record, RoutingPolicy(policy.centroids), languages)
    best = max(plain.values()) if plain else 0.0
    language = record["language_detected"]
    return [
        corpus
        for corpus, value in plain.items()
        if languages.get(corpus) in LANGUAGE_NAMES
        and language in LANGUAGE_NAMES
        and languages.get(corpus) != language
        and value >= best - policy.margin
    ]


def calibrate(
    calibration: list[dict[str, Any]], policy: AbstentionPolicy, languages: dict[str, str], production: dict
) -> Callable[[str, str], float | None]:
    """Threshold lookup (corpus, question language) -> threshold."""
    if policy.thresholds == "production":
        table = production["rerank" if policy.score == "rerank" else "dense"]
        return lambda corpus, language: table.get(corpus)
    groups: dict[tuple[str, str], list[float]] = {}
    for row in calibration:
        value = _record_score(row, policy.score)
        if value is not None:
            groups.setdefault((row["corpus"], row["language"]), []).append(value)

    def value_for(scores: list[float]) -> float:
        if policy.thresholds == "zscore":
            return mean(scores) - (policy.level or 0.0) * pstdev(scores)
        return quantile(scores, policy.level or 0.0)

    table = {key: round(value_for(scores), 4) for key, scores in groups.items()}
    # Per corpus: calibrated on questions in the corpus's own language, as in production.
    per_corpus = {corpus: table.get((corpus, language)) for corpus, language in languages.items()}
    if policy.thresholds == "corpus":
        return lambda corpus, language: per_corpus.get(corpus)
    # As `threshold_for`: a language without its own value keeps the
    # production threshold of the corpus.
    fallback = production["rerank" if policy.score == "rerank" else "dense"]
    return lambda corpus, language: table.get((corpus, language), fallback.get(corpus))


def threshold_table(
    lookup: Callable[[str, str], float | None], languages: dict[str, str]
) -> dict[str, dict[str, float | None]]:
    return {corpus: {language: lookup(corpus, language) for language in ("fr", "pt", "en")} for corpus in languages}


def replay(
    report: dict[str, Any],
    routing: RoutingPolicy,
    abstention: AbstentionPolicy,
    *,
    production: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    languages = report["config"]["corpus_languages"]
    production = production or {
        "dense": report["config"]["abstention_thresholds"],
        "rerank": report["config"]["rerank_abstention_thresholds"],
    }
    lookup = calibrate(report["calibration"], abstention, languages, production)
    # As the router: a (corpus, language) pair without its own threshold
    # keeps the corpus threshold and the translated question's score (#76),
    # which that threshold was calibrated for.
    own = (
        {
            (row["corpus"], row["language"])
            for row in report["calibration"]
            if _record_score(row, abstention.score) is not None
        }
        if abstention.thresholds == "language" and abstention.score == "dense"
        else None
    )
    outcomes: list[dict[str, Any]] = []
    for record in report["records"]:
        scores = corpus_scores(record, routing, languages)
        corpus = max(scores, key=lambda name: scores[name])
        entry = record["corpora"][corpus]
        intent = decide_intent(record["intent_scores"], margin=SELECTED_INTENT_MARGIN)
        source = abstention.score
        if own is not None and (corpus, record["language_detected"]) not in own:
            source = "dense_xl"
        score = _record_score(entry, source)
        threshold = lookup(corpus, record["language_detected"])
        if entry.get("legal_citation_found"):
            refused = False
        elif intent != Intent.DOCUMENTARY or score is None:
            refused = True
        else:
            refused = threshold is not None and score < threshold
        rescored = rescored_corpora(record, routing, languages)
        timings = entry["timings_ms"]
        # Router (embed + dot products) + writer calls for rescored corpora
        # other than the chosen one (the chosen one's is reused by BM25) +
        # retrieval on the chosen corpus (its translation included).
        latency = (
            record["router_ms"]["total"]
            + sum(record["corpora"][other]["translation_ms"] for other in rescored if other != corpus)
            + timings.get("embed", 0.0)
            + timings.get("retrieval", 0.0)
            + timings.get("rerank", 0.0)
            + (entry.get("translated_dense_ms", 0.0) if source == "dense_xl" else 0.0)
        )
        expected = record["expected_corpus"]
        outcomes.append(
            {
                "id": record["id"],
                "source": record["source"],
                "category": record["category"],
                "language": record["language"],
                "corpus": corpus,
                "routed_right": expected is not None and corpus == expected,
                "refused": refused,
                "answered_right": expected is not None and corpus == expected and not refused and entry["hit"],
                "latency_ms": latency,
            }
        )
    return {
        "routing": routing.label,
        "abstention": abstention.label,
        "thresholds": threshold_table(lookup, languages),
        "metrics": outcome_metrics(outcomes),
        "outcomes": outcomes,
    }


def outcome_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    in_scope = [o for o in outcomes if o["category"] == "in_scope"]
    declinable = [o for o in outcomes if o["category"] != "in_scope"]
    by_source: dict[str, dict[str, Any]] = {}
    for source in sorted({o["source"] for o in in_scope}):
        rows = [o for o in in_scope if o["source"] == source]
        latencies = [o["latency_ms"] for o in rows]
        by_source[source] = {
            "questions": len(rows),
            "routed_right": sum(o["routed_right"] for o in rows),
            "refused": sum(o["refused"] for o in rows),
            "answered_right": sum(o["answered_right"] for o in rows),
            "latency_p50_ms": round(_percentile(latencies, 0.5), 1),
            "latency_p95_ms": round(_percentile(latencies, 0.95), 1),
        }
    refused_in_scope = sum(o["refused"] for o in in_scope)
    kept = sum(o["refused"] for o in declinable)
    by_category = Counter(o["category"] for o in declinable if o["refused"])
    return {
        "by_source": by_source,
        "refusals_kept": kept,
        "declinable": len(declinable),
        "abstention_recall": round(kept / len(declinable), 4) if declinable else 0.0,
        "refusals_by_category": dict(sorted(by_category.items())),
        "false_refusals": refused_in_scope,
        "false_refusal_rate": round(refused_in_scope / len(in_scope), 4) if in_scope else 0.0,
    }


def paired(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """McNemar per set (answered from the right passage) and on the refusals kept: b against a."""
    pairs = {(o["id"], o["source"]): o for o in a["outcomes"]}
    result: dict[str, Any] = {}
    groups: dict[str, list[tuple[bool, bool]]] = {}
    for outcome in b["outcomes"]:
        before = pairs[(outcome["id"], outcome["source"])]
        if outcome["category"] == "in_scope":
            groups.setdefault(outcome["source"], []).append((before["answered_right"], outcome["answered_right"]))
        else:
            groups.setdefault("abstention", []).append((before["refused"], outcome["refused"]))
    for name, values in groups.items():
        gained = sum(1 for x, y in values if y and not x)
        lost = sum(1 for x, y in values if x and not y)
        result[name] = {"gained": gained, "lost": lost, "p_value": round(mcnemar_exact(gained, lost), 4)}
    return result


QUANTILES = (0.01, 0.02, 0.03, 0.05, 0.1)
Z_VALUES = (1.5, 2.0, 2.5, 3.0)


def selected(
    report: dict[str, Any], routing: RoutingPolicy, score: str, thresholds: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Owner's rule within one family: the level that keeps the most
    declinable questions refused with false refusals strictly under 5 %."""
    levels = Z_VALUES if thresholds == "zscore" else QUANTILES
    runs = [replay(report, routing, AbstentionPolicy(score, thresholds, level)) for level in levels]
    eligible = [r for r in runs if r["metrics"]["false_refusal_rate"] < MAX_FALSE_ABSTENTION]
    best = max(
        eligible,
        key=lambda r: (r["metrics"]["abstention_recall"], -r["metrics"]["false_refusal_rate"]),
        default=None,
    )
    return best, runs


def strip(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if k != "outcomes"}


# The settings compared, in table order. The first is the production default
# (cross-language routing #76, margin 0.02, point A thresholds), the
# reference of every paired test; "off" is the router before #76.
DEFAULT = (RoutingPolicy("chunks", 0.02), "dense_xl", "production")
SETTINGS: tuple[tuple[str, RoutingPolicy, str, str], ...] = (
    ("default", *DEFAULT),
    ("off", RoutingPolicy("chunks"), "dense", "production"),
    ("a_dense", RoutingPolicy("chunks", 0.02), "dense", "language"),
    ("a_dense_xl", RoutingPolicy("chunks", 0.02), "dense_xl", "language"),
    ("corpus_dense_xl", RoutingPolicy("chunks", 0.02), "dense_xl", "corpus"),
    ("b_zscore", RoutingPolicy("chunks", 0.02), "dense_xl", "zscore"),
    ("d_rerank_corpus", RoutingPolicy("chunks", 0.02), "rerank", "corpus"),
    ("d_rerank_language", RoutingPolicy("chunks", 0.02), "rerank", "language"),
    ("c_examples", RoutingPolicy("examples"), "dense_xl", "production"),
    ("c_examples_a", RoutingPolicy("examples"), "dense", "language"),
    ("ce_examples_xl", RoutingPolicy("examples", 0.02), "dense_xl", "production"),
    ("ce_examples_xl_a", RoutingPolicy("examples", 0.02), "dense_xl", "language"),
    ("ce_examples_xl_rerank", RoutingPolicy("examples", 0.02), "rerank", "language"),
)


def compare(report: dict[str, Any]) -> dict[str, Any]:
    baseline = replay(report, DEFAULT[0], AbstentionPolicy(DEFAULT[1], DEFAULT[2]))
    off = None
    rows: list[dict[str, Any]] = []
    for name, routing, score, thresholds in SETTINGS:
        if thresholds == "production":
            run: dict[str, Any] | None = replay(report, routing, AbstentionPolicy(score, thresholds))
            levels: list[dict[str, Any]] = []
        else:
            run, sweep_runs = selected(report, routing, score, thresholds)
            levels = [
                {"level": r["abstention"], **{k: r["metrics"][k] for k in ("abstention_recall", "false_refusal_rate")}}
                for r in sweep_runs
            ]
        if run is None:
            rows.append({"name": name, "routing": routing.label, "selected": None, "levels": levels})
            continue
        if name == "off":
            off = run
        rows.append(
            {
                "name": name,
                **strip(run),
                "vs_default": paired(baseline, run),
                "vs_off": paired(off, run) if off is not None and name != "off" else None,
                "levels": levels,
            }
        )
    return {
        "summary": {"settings": [{k: v for k, v in row.items() if k != "levels"} for row in rows]},
        "rows": rows,
    }


def _fmt_pair(pair: dict[str, Any] | None) -> str:
    if not pair:
        return ""
    p = pair["p_value"]
    return f" (+{pair['gained']}/−{pair['lost']}, p = {p:.3f})" if pair["gained"] or pair["lost"] else ""


def render_comparison(comparison: dict[str, Any]) -> str:
    lines = [
        "| Réglage | Routage | Abstention | FR→LexML bien routées | Répondues FR | Répondues PT | Répondues PIAF "
        "| Refus gardés /80 | Faux refus | p50 / p95 FR (ms) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in comparison["rows"]:
        if row.get("metrics") is None:
            lines.append(f"| {row['name']} | {row['routing']} | aucun niveau sous 5 % | | | | | | | |")
            continue
        m = row["metrics"]
        s = m["by_source"]
        pair = row["vs_default"]
        lines.append(
            f"| {row['name']} | {row['routing']} | {row['abstention']} | {s['lexml_fr']['routed_right']} "
            f"| {s['lexml_fr']['answered_right']}{_fmt_pair(pair.get('lexml_fr'))} "
            f"| {s['lexml_fr_pt']['answered_right']}{_fmt_pair(pair.get('lexml_fr_pt'))} "
            f"| {s['piaf']['answered_right']}{_fmt_pair(pair.get('piaf'))} "
            f"| {m['refusals_kept']}{_fmt_pair(pair.get('abstention'))} | {m['false_refusal_rate']:.1%} "
            f"| {s['lexml_fr']['latency_p50_ms']:.0f} / {s['lexml_fr']['latency_p95_ms']:.0f} |"
        )
    return "\n".join(lines)
