"""Evaluation of the query router (phase 9.4).

Runs the frozen abstention set plus an equal number of in-scope questions
drawn (seeded) from the PIAF and LexML ground truths, routes and retrieves
each one, then scores the decisions offline: thresholds are swept on the
recorded scores, so one pass over the questions gives the whole
precision / recall curve.

Positive class = "should not answer from the documents" (out_of_scope,
near_miss, conversational). The router abstains when the intent is not
documentary or when the best passage scores below the threshold.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.models import Corpus
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.experiments.recall import _chunk_covers_span, _percentile
from raglab.llm.local_server import LocalLLMServer
from raglab.retrieval.service import QueryService
from raglab.retrieval.translation import needs_translation
from raglab.routing.abstention import best_score, threshold_for
from raglab.routing.citation import cited_text_in_run
from raglab.routing.intent import decide_intent
from raglab.routing.router import QueryRouter
from raglab.routing.schemas import Intent
from raglab.routing.step import cross_language_routing, translated_abstention, translated_dense_score

REPO_ROOT = Path(__file__).resolve().parents[3]
ABSTENTION_PATH = REPO_ROOT / "benchmarks" / "abstention" / "questions.jsonl"
# Corpus of a set whose rows each name their own (`expected_corpus`).
MULTI_CORPUS = "multi"


@dataclass(frozen=True)
class InScopeSet:
    name: str
    path: Path
    corpus_name: str
    language: str


IN_SCOPE_SETS = (
    InScopeSet("piaf", REPO_ROOT / "benchmarks" / "piaf" / "ground_truth.jsonl", "bench_piaf_fr", "fr"),
    InScopeSet(
        "lexml_fulltext",
        REPO_ROOT / "benchmarks" / "lexml_fulltext" / "ground_truth.jsonl",
        "bench_lexml_pt",
        "pt",
    ),
    # Used once their frozen questions exist (generated on GPU); the EU set
    # mixes en / fr / pt, each row carries its question's language.
    InScopeSet(
        "legi_consommation",
        REPO_ROOT / "benchmarks" / "legi_consommation" / "ground_truth.jsonl",
        "bench_legi_consommation_fr",
        "fr",
    ),
    InScopeSet(
        "eurlex_compliance",
        REPO_ROOT / "benchmarks" / "eurlex_compliance" / "ground_truth.jsonl",
        "bench_eurlex_compliance",
        "multi",
    ),
)


# Sets measured only when named (`--in-scope`), so the default sample stays
# the one the published thresholds were calibrated on.
EXTRA_SETS = {
    # French questions on the Portuguese LexML corpus (cross-language).
    "lexml_fr": InScopeSet(
        "lexml_fr", REPO_ROOT / "benchmarks" / "lexml_fr" / "ground_truth.jsonl", "bench_lexml_pt", "fr"
    ),
    # The same cases with their Portuguese question: false refusals of the
    # two languages compared under the same per-corpus threshold.
    "lexml_fr_pt": InScopeSet(
        "lexml_fr_pt", REPO_ROOT / "benchmarks" / "lexml_fr" / "ground_truth_pt.jsonl", "bench_lexml_pt", "pt"
    ),
    # French questions of Brazil expats on the Portuguese federal texts.
    "br_expat": InScopeSet(
        "br_expat", REPO_ROOT / "benchmarks" / "br_expat" / "ground_truth.jsonl", "bench_br_expat_pt", "fr"
    ),
    # Independent validation set of the intent work (docs/intentions.md):
    # user-style questions on the four corpora, each row names its corpus.
    "validation": InScopeSet(
        "validation", REPO_ROOT / "benchmarks" / "routing_validation" / "in_scope.jsonl", MULTI_CORPUS, "multi"
    ),
    # Second one, written after the first was read, to test the variant chosen in between.
    "validation_2": InScopeSet(
        "validation_2", REPO_ROOT / "benchmarks" / "routing_validation_2" / "in_scope.jsonl", MULTI_CORPUS, "multi"
    ),
}
VALIDATION_ABSTENTION_PATH = REPO_ROOT / "benchmarks" / "routing_validation" / "abstention.jsonl"


@dataclass(frozen=True)
class CalibrationFile:
    """In-scope questions written or drawn for calibration only (never
    evaluated); a row names its corpus and language, or takes the defaults."""

    name: str
    path: Path
    corpus_name: str | None = None
    language: str | None = None


# Calibration files by name (`--calibration-file`), retrieved on their own corpus.
CALIBRATION_FILES = {
    "lexml_fr": CalibrationFile(
        "lexml_fr", REPO_ROOT / "benchmarks" / "lexml_fr" / "calibration.jsonl", "bench_lexml_pt", "fr"
    ),
    "lexml_pt": CalibrationFile(
        "lexml_pt", REPO_ROOT / "benchmarks" / "lexml_fr" / "calibration_pt.jsonl", "bench_lexml_pt", "pt"
    ),
    "br_expat": CalibrationFile("br_expat", REPO_ROOT / "benchmarks" / "br_expat" / "calibration.jsonl"),
    "eurlex": CalibrationFile("eurlex", REPO_ROOT / "benchmarks" / "eurlex_compliance" / "calibration.jsonl"),
}


def load_calibration_files(names: list[str]) -> list[RoutingCase]:
    unknown = sorted(set(names) - set(CALIBRATION_FILES))
    if unknown:
        raise ValueError(
            f"Calibration inconnue: {', '.join(unknown)}. Fichiers: {', '.join(sorted(CALIBRATION_FILES))}"
        )
    cases: list[RoutingCase] = []
    for name in names:
        calibration = CALIBRATION_FILES[name]
        for row in _read_jsonl(calibration.path):
            if row.get("review_status") == "rejected":
                continue
            cases.append(
                RoutingCase(
                    id=row["id"],
                    question=row["question"],
                    category="in_scope",
                    language=row.get("language") or calibration.language or "",
                    source=f"calibration:{name}",
                    expected_corpus=row.get("corpus") or calibration.corpus_name,
                )
            )
    return cases


def named_sets(names: list[str]) -> tuple[InScopeSet, ...]:
    """In-scope sets by name, among the default ones and `EXTRA_SETS`."""
    known = {s.name: s for s in IN_SCOPE_SETS} | EXTRA_SETS
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise ValueError(f"Jeu inconnu: {', '.join(unknown)}. Jeux: {', '.join(sorted(known))}")
    return tuple(known[name] for name in names)


def available_sets(in_scope_sets: tuple[InScopeSet, ...], corpora: list[str] | None = None) -> tuple[InScopeSet, ...]:
    """Sets whose questions exist and whose corpus the router may choose.

    With `--corpus` given, only those corpora's sets are evaluated, so
    `--corpus bench_piaf_fr --corpus bench_lexml_pt` keeps measuring exactly
    the PIAF + LexML sample, whatever other corpora are indexed.
    """
    return tuple(
        s
        for s in in_scope_sets
        if s.path.exists() and (not corpora or s.corpus_name in corpora or s.corpus_name == MULTI_CORPUS)
    )


def _row_language(in_scope: InScopeSet, row: dict[str, Any]) -> str:
    return row.get("language") or (row.get("context") or {}).get("question_language") or in_scope.language


# Intent margins swept; None = intent ignored (abstention on the score only).
INTENT_MARGINS: tuple[float | None, ...] = (None, -0.05, -0.02, 0.0, 0.02, 0.05, 0.1)
# Per-corpus thresholds: this quantile of the best scores of in-scope
# calibration questions, so about that share of in-scope questions abstain.
CALIBRATION_QUANTILES = (0.01, 0.02, 0.03, 0.05, 0.1, 0.15, 0.2)

# A threshold is global (float) or per corpus (corpus name -> float, None =
# no calibrated threshold, so no abstention on score).
Threshold = float | dict[str, float | None]

# Selection rule set by the owner: intent margin kept at 0.02, thresholds
# calibrated per corpus on the score source being measured, and the best
# point is the one that declines the most out-of-scope questions while
# false abstentions stay strictly under 5%. Recall target: 0.85.
SELECTED_INTENT_MARGIN = 0.02
MAX_FALSE_ABSTENTION = 0.05
TARGET_RECALL = 0.85


@dataclass
class RoutingCase:
    id: str
    question: str
    # in_scope, out_of_scope, near_miss or conversational.
    category: str
    language: str
    source: str
    subtype: str | None = None
    expected_corpus: str | None = None
    expected_spans: list[dict[str, Any]] = field(default_factory=list)

    @property
    def should_abstain(self) -> bool:
        return self.category != "in_scope"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_cases(
    *,
    abstention_path: Path = ABSTENTION_PATH,
    in_scope_sets: tuple[InScopeSet, ...] = IN_SCOPE_SETS,
    sample_size: int | None = None,
    seed: int = 42,
) -> list[RoutingCase]:
    """Abstention set + `sample_size` in-scope questions (default: same size).

    In-scope questions are split evenly between the sets, sorted by id then
    drawn with `seed`, like the other benchmarks. Questions marked
    `rejected` at review are skipped.
    """
    cases = [
        RoutingCase(
            id=row["id"],
            question=row["question"],
            category=row["category"],
            language=row["language"],
            source="abstention",
            subtype=row.get("subtype"),
        )
        for row in _read_jsonl(abstention_path)
    ]
    total = sample_size if sample_size is not None else len(cases)
    rng = random.Random(seed)
    for position, in_scope in enumerate(in_scope_sets):
        count = total // len(in_scope_sets) + (1 if position < total % len(in_scope_sets) else 0)
        rows = sorted(
            (row for row in _read_jsonl(in_scope.path) if row.get("review_status") != "rejected"),
            key=lambda row: row["id"],
        )
        for row in rng.sample(rows, min(count, len(rows))):
            cases.append(
                RoutingCase(
                    id=row["id"],
                    question=row["question"],
                    category="in_scope",
                    language=_row_language(in_scope, row),
                    source=in_scope.name,
                    subtype=row.get("question_type"),
                    expected_corpus=row.get("expected_corpus") or in_scope.corpus_name,
                    expected_spans=row.get("expected_spans") or [],
                )
            )
    return cases


def load_calibration(
    *,
    in_scope_sets: tuple[InScopeSet, ...] = IN_SCOPE_SETS,
    exclude_ids: set[str],
    size: int,
    seed: int,
) -> list[RoutingCase]:
    """In-scope questions disjoint from the evaluated ones, per set.

    Their best scores set the per-corpus thresholds, so the thresholds are
    never fitted on the questions they are evaluated on.
    """
    cases: list[RoutingCase] = []
    rng = random.Random(seed)
    for in_scope in in_scope_sets:
        rows = sorted(
            (
                row
                for row in _read_jsonl(in_scope.path)
                if row.get("review_status") != "rejected" and row["id"] not in exclude_ids
            ),
            key=lambda row: row["id"],
        )
        for row in rng.sample(rows, min(size, len(rows))):
            cases.append(
                RoutingCase(
                    id=row["id"],
                    question=row["question"],
                    category="in_scope",
                    language=_row_language(in_scope, row),
                    source=in_scope.name,
                    expected_corpus=row.get("expected_corpus") or in_scope.corpus_name,
                )
            )
    return cases


def quantile(values: list[float], fraction: float) -> float:
    """Lower nearest-rank quantile: about `fraction` of the values fall below."""
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(fraction * len(ordered)) - 1))]


def calibrated_thresholds(calibration: dict[str, list[float]], fraction: float) -> dict[str, float | None]:
    return {corpus: round(quantile(scores, fraction), 4) for corpus, scores in sorted(calibration.items()) if scores}


def _threshold_for(threshold: Threshold, record: dict[str, Any]) -> float | None:
    if isinstance(threshold, dict):
        value = threshold.get(record["corpus_routed"])
        # Per-language thresholds (routing_language_thresholds): language -> value.
        if isinstance(value, dict):
            return value.get(record.get("language_detected") or "")
        return value
    return threshold


def predict_abstain(record: dict[str, Any], *, margin: float | None, threshold: Threshold) -> bool:
    # Same rule as the router: a question citing a law is never declined.
    if record.get("legal_citation"):
        return False
    if margin is not None and decide_intent(record["intent_scores"], margin=margin) != Intent.DOCUMENTARY:
        return True
    score = record["best_score"]
    if score is None:
        return True
    value = _threshold_for(threshold, record)
    return value is not None and score < value


def abstention_metrics(
    records: list[dict[str, Any]],
    *,
    margin: float | None,
    threshold: Threshold,
    calibration_quantile: float | None = None,
    router_decision: bool = False,
) -> dict[str, Any]:
    """`router_decision`: read the abstention the router itself took
    (`router_abstain`) instead of replaying margin and thresholds; needed
    for rules the sweep cannot replay (kNN intent, joint rule)."""
    tp = fp = fn = tn = 0
    by_category: dict[str, list[bool]] = {}
    for record in records:
        predicted = (
            bool(record["router_abstain"])
            if router_decision
            else predict_abstain(record, margin=margin, threshold=threshold)
        )
        expected = record["category"] != "in_scope"
        tp += predicted and expected
        fp += predicted and not expected
        fn += expected and not predicted
        tn += not predicted and not expected
        by_category.setdefault(record["category"], []).append(predicted)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "intent_margin": margin,
        "threshold_mode": "per_corpus" if isinstance(threshold, dict) else "global",
        "threshold": threshold if isinstance(threshold, dict) else round(threshold, 4),
        "calibration_quantile": calibration_quantile,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_abstention_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "abstention_rate_by_category": {
            category: round(sum(values) / len(values), 4) for category, values in sorted(by_category.items())
        },
    }


def threshold_grid(records: list[dict[str, Any]], step: float = 0.005) -> list[float]:
    scores = [r["best_score"] for r in records if r["best_score"] is not None]
    if not scores:
        return [0.0]
    low = round(min(scores) - step, 3)
    high = round(max(scores) + step, 3)
    count = int(round((high - low) / step)) + 1
    return [0.0] + [round(low + i * step, 4) for i in range(count)]


def sweep(records: list[dict[str, Any]], calibration: dict[str, list[float]] | None = None) -> list[dict[str, Any]]:
    """Global thresholds over the observed score range, then per-corpus ones."""
    grid = threshold_grid(records)
    curve = [
        abstention_metrics(records, margin=margin, threshold=threshold)
        for margin in INTENT_MARGINS
        for threshold in grid
    ]
    if calibration:
        curve += [
            abstention_metrics(
                records,
                margin=margin,
                threshold=calibrated_thresholds(calibration, fraction),
                calibration_quantile=fraction,
            )
            for margin in INTENT_MARGINS
            for fraction in CALIBRATION_QUANTILES
        ]
    return curve


def candidate_points(curve: list[dict[str, Any]], *, max_false_abstention: float = 0.05, min_recall: float = 0.8):
    """Three operating points for the owner to choose from (none is applied)."""

    def best(rows, key):
        return max(rows, key=key) if rows else None

    safe = [p for p in curve if p["false_abstention_rate"] <= max_false_abstention]
    covering = [p for p in curve if p["recall"] >= min_recall]
    selected = [
        p
        for p in curve
        if p["intent_margin"] == SELECTED_INTENT_MARGIN
        and p["threshold_mode"] == "per_corpus"
        and p["false_abstention_rate"] < MAX_FALSE_ABSTENTION
    ]
    return {
        # The rule the owner set (see SELECTED_INTENT_MARGIN); the others are context.
        "selected": best(selected, lambda p: (p["recall"], p["precision"])),
        "max_f1": best(curve, lambda p: (p["f1"], p["precision"])),
        "max_recall_false_abstention_le_5pct": best(safe, lambda p: (p["recall"], p["precision"])),
        "max_precision_recall_ge_80pct": best(covering, lambda p: (p["precision"], p["recall"])),
    }


def intent_confusion(records: list[dict[str, Any]], *, margin: float) -> dict[str, dict[str, int]]:
    """Predicted intent x expected category."""
    matrix: dict[str, Counter[str]] = {}
    for record in records:
        predicted = decide_intent(record["intent_scores"], margin=margin).value
        matrix.setdefault(record["category"], Counter())[predicted] += 1
    intents = [intent.value for intent in Intent]
    return {category: {i: counts.get(i, 0) for i in intents} for category, counts in sorted(matrix.items())}


def _latency(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {"p50_ms": round(_percentile(values, 0.5), 3), "p95_ms": round(_percentile(values, 0.95), 3)}


def summarize(
    records: list[dict[str, Any]],
    settings: Settings,
    calibration: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    language_ok = [r["language_detected"] == r["language"] for r in records]
    in_scope = [r for r in records if r["category"] == "in_scope"]
    routed = [r for r in in_scope if r["expected_corpus"]]
    corpus_ok = [r["corpus_routed"] == r["expected_corpus"] for r in routed]
    by_corpus: dict[str, list[bool]] = {}
    for record, ok in zip(routed, corpus_ok, strict=True):
        by_corpus.setdefault(record["expected_corpus"], []).append(ok)
    curve = sweep(records, calibration)
    languages = sorted({r["language_detected"] for r in records if r.get("language_detected")})
    configured_thresholds: dict[str, Any] = {
        corpus: (
            {
                language: threshold_for(settings, corpus, settings.routing_score_source, language)
                for language in languages
            }
            if settings.routing_language_thresholds
            else threshold_for(settings, corpus, settings.routing_score_source)
        )
        for corpus in sorted({r["corpus_routed"] for r in records if r["corpus_routed"]})
    }
    configured = abstention_metrics(
        records,
        margin=settings.routing_intent_margin,
        threshold=configured_thresholds,
        router_decision=bool(records) and all("router_abstain" in r for r in records),
    )
    return {
        "cases": dict(Counter(r["category"] for r in records)),
        "language_accuracy": round(sum(language_ok) / len(language_ok), 4) if records else 0.0,
        "language_accuracy_by_method": {
            method: round(
                sum(ok for r, ok in zip(records, language_ok, strict=True) if r["language_method"] == method)
                / max(1, sum(r["language_method"] == method for r in records)),
                4,
            )
            for method in sorted({r["language_method"] for r in records})
        },
        "language_errors": [
            {"id": r["id"], "expected": r["language"], "detected": r["language_detected"]}
            for r, ok in zip(records, language_ok, strict=True)
            if not ok
        ],
        "corpus_routing_accuracy": round(sum(corpus_ok) / len(corpus_ok), 4) if corpus_ok else None,
        "corpus_routing_accuracy_by_corpus": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_corpus.items())},
        "in_scope_retrieval_hit_rate": (
            round(sum(r["hit"] for r in in_scope) / len(in_scope), 4) if in_scope else None
        ),
        "intent_confusion": intent_confusion(records, margin=settings.routing_intent_margin),
        "configured": configured,
        "candidates": candidate_points(curve),
        "target_recall": TARGET_RECALL,
        "calibration": {
            corpus: {
                "questions": len(scores),
                **{f"q{fraction:g}": round(quantile(scores, fraction), 4) for fraction in CALIBRATION_QUANTILES},
            }
            for corpus, scores in sorted((calibration or {}).items())
            if scores
        },
        "query_translation_outcomes": dict(
            Counter(
                ("translated" if r["query_translation"].get("translated") else r["query_translation"].get("notice"))
                for r in records
                if r.get("query_translation")
            )
        ),
        "latency": {
            # Router + retrieval (translation, search, re-ranking), generation excluded.
            "request_total": _latency([r["timings_ms"]["total"] + r.get("retrieval_ms", 0.0) for r in records]),
            "translation": _latency(
                [
                    r["retrieval_timings_ms"]["translation"]
                    for r in records
                    if "translation" in r.get("retrieval_timings_ms", {})
                ]
            ),
            "router_total": _latency([r["timings_ms"]["total"] for r in records]),
            "router_without_embed": _latency([r["timings_ms"]["total"] - r["timings_ms"]["embed"] for r in records]),
            "router_embed": _latency([r["timings_ms"]["embed"] for r in records]),
        },
        "curve": curve,
    }


class RoutingExperimentService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()

    def run(
        self,
        *,
        corpora: list[str] | None = None,
        strategy: ChunkingStrategy | None = None,
        sample_size: int | None = None,
        seed: int = 42,
        top_k: int = 5,
        calibration_size: int = 100,
        retrieval_mode: RetrievalMode | None = None,
        rerank: bool | None = None,
        citations: bool | None = None,
        query_translation: bool | None = None,
        abstention_path: Path = ABSTENTION_PATH,
        in_scope_sets: tuple[InScopeSet, ...] = IN_SCOPE_SETS,
        calibration_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """`calibration_files`: names of `CALIBRATION_FILES` retrieved on
        their own corpus, recorded question by question with the default
        calibration draw (`calibration_records`)."""
        in_scope_sets = available_sets(in_scope_sets, corpora)
        cases = load_cases(
            abstention_path=abstention_path, in_scope_sets=in_scope_sets, sample_size=sample_size, seed=seed
        )
        router = QueryRouter(self.session, self.settings)
        retriever = QueryService(self.session, self.settings)
        # None = the production defaults (hybrid + re-ranking + citations).
        retrieval_options: dict[str, Any] = {
            "retrieval_mode": retrieval_mode,
            "rerank": rerank,
            "citations": citations,
            "query_translation": query_translation,
        }
        translate = self.settings.query_translation if query_translation is None else query_translation
        cross_language = cross_language_routing(retriever, query_translation)
        # Warm-up: model weights, example embeddings and corpus centroids are
        # loaded once per process and kept out of the latency figures.
        warm_up = router.route("warm-up", strategy=strategy, candidate_corpora=corpora or None)
        runs = {candidate.corpus_name: candidate.index_run_id for candidate in warm_up.corpus.candidates}

        records: list[dict[str, Any]] = []
        writer = ExitStack()
        corpus_languages = set(
            self.session.execute(select(Corpus.language).where(Corpus.name.in_(list(runs)))).scalars()
        )
        if translate and any(needs_translation(case.question, lang) for case in cases for lang in corpus_languages):
            # The writer translates during retrieval: started only when a
            # question's language differs from a routable corpus's.
            writer.enter_context(LocalLLMServer(self.settings, profile=self.settings.writer_model_profile))
        with writer:
            for case in cases:
                decision = router.route(
                    case.question,
                    strategy=strategy,
                    candidate_corpora=corpora or None,
                    translator=retriever.translator if cross_language else None,
                )
                if decision.corpus.index_run_id is None:
                    raise ValueError("Aucun index compatible avec l'embedder du routeur : indexez au moins un corpus.")
                outcome = retriever.retrieve(
                    question=case.question,
                    index_run_id=decision.corpus.index_run_id,
                    top_k=top_k,
                    **retrieval_options,
                )
                chunks = [chunk.model_dump() for chunk in outcome.retrieved]
                timings = outcome.timings_ms
                original = best_score(outcome.retrieved, self.settings.routing_score_source)
                translated = (
                    translated_dense_score(retriever, outcome)
                    if translated_abstention(
                        retriever, cross_language, decision.corpus.corpus_name, decision.language.language
                    )
                    else None
                )
                legal_citation = decision.citation is not None and cited_text_in_run(
                    self.session, outcome.index_run, decision.citation
                )
                # The router's own decision, as `route_and_retrieve` takes it.
                finished = router.finish(
                    decision.model_copy(update={"legal_citation_found": legal_citation}),
                    outcome.retrieved,
                    translated_score=translated,
                )
                records.append(
                    {
                        **{k: v for k, v in asdict(case).items() if k != "expected_spans"},
                        "language_detected": decision.language.language,
                        "language_method": decision.language.method,
                        "intent_scores": decision.intent.scores,
                        "intent": decision.intent.intent.value,
                        "intent_method": decision.intent.method,
                        "documentary_margin": decision.intent.documentary_margin,
                        "not_documentary_probability": decision.intent.not_documentary_probability,
                        "router_abstain": bool(finished.abstention and finished.abstention.abstain),
                        "router_abstention": finished.abstention.model_dump() if finished.abstention else None,
                        "corpus_routed": decision.corpus.corpus_name,
                        "corpus_margin": decision.corpus.margin,
                        "corpus_scores": {c.corpus_name: c.score for c in decision.corpus.candidates},
                        # Same rule as the router: a cited text the index holds.
                        "legal_citation": legal_citation,
                        # The score the router compares to the threshold: with
                        # cross-language routing, the better of the original and
                        # the translated question (as in `QueryRouter.finish`).
                        "best_score": (
                            original
                            if translated is None or (original is not None and original >= translated)
                            else translated
                        ),
                        "best_score_original": original,
                        # Dense cosine of the original question, whatever the score source.
                        "dense_original": best_score(outcome.retrieved, "dense"),
                        "best_score_translated": translated,
                        "corpus_candidates": [c.model_dump() for c in decision.corpus.candidates],
                        "scores": [round(chunk.score, 4) for chunk in outcome.retrieved],
                        "hit": any(_chunk_covers_span(chunk, span) for chunk in chunks for span in case.expected_spans),
                        "timings_ms": decision.timings_ms,
                        # Embed + search (translation included) + re-ranking.
                        "retrieval_ms": round(
                            timings.get("embed", 0.0) + timings.get("retrieval", 0.0) + timings.get("rerank", 0.0), 3
                        ),
                        "retrieval_timings_ms": dict(timings),
                        "query_translation": outcome.query_translation,
                    }
                )

            # Calibration questions go through the same retrieval (translation included).
            calibration: dict[str, list[float]] = {}
            calibration_cases = load_calibration(
                in_scope_sets=tuple(s for s in in_scope_sets if s.corpus_name != MULTI_CORPUS),
                exclude_ids={case.id for case in cases},
                size=calibration_size,
                seed=seed + 1,
            ) + load_calibration_files(calibration_files or [])
            calibration_records: list[dict[str, Any]] = []
            for case in calibration_cases:
                if case.expected_corpus not in runs:
                    continue
                outcome = retriever.retrieve(
                    question=case.question,
                    index_run_id=runs[case.expected_corpus],
                    top_k=top_k,
                    **retrieval_options,
                )
                score = best_score(outcome.retrieved, self.settings.routing_score_source)
                translated = (
                    translated_dense_score(retriever, outcome)
                    if translated_abstention(retriever, cross_language, case.expected_corpus, case.language)
                    else None
                )
                calibration_records.append(
                    {
                        "id": case.id,
                        "question": case.question,
                        "source": case.source,
                        "corpus": case.expected_corpus,
                        "language": case.language,
                        "dense": best_score(outcome.retrieved, "dense"),
                        "dense_translated": translated,
                        "rerank": best_score(outcome.retrieved, "rerank"),
                    }
                )
                if translated is not None:
                    score = translated if score is None else max(score, translated)
                if score is not None:
                    calibration.setdefault(case.expected_corpus or "", []).append(score)

        report = {
            "kind": "routing",
            "created_at": datetime.now(UTC).isoformat(),
            "config": {
                "corpora": corpora or [],
                "strategy": strategy.value if strategy else None,
                "sample_size": sample_size,
                "seed": seed,
                "top_k": top_k,
                "calibration_size": calibration_size,
                "in_scope_sets": [s.name for s in in_scope_sets],
                "abstention_path": str(abstention_path),
                "calibration_files": calibration_files or [],
                "retrieval_mode": (retrieval_mode or RetrievalMode(self.settings.default_retrieval_mode)).value,
                "rerank": self.settings.default_rerank if rerank is None else rerank,
                "citations": self.settings.citation_resolver if citations is None else citations,
                "query_translation": translate,
                "routing_cross_language": cross_language,
                "routing_corpus_examples": self.settings.routing_corpus_examples,
                "routing_language_thresholds": self.settings.routing_language_thresholds,
                "routing_intent_knn": self.settings.routing_intent_knn,
                "routing_intent_logistic": self.settings.routing_intent_logistic,
                "routing_intent_calibration_path": str(self.settings.routing_intent_calibration_path),
                "language_abstention_thresholds": self.settings.routing_language_abstention_thresholds,
                "rerank_language_abstention_thresholds": self.settings.routing_rerank_language_abstention_thresholds,
                "routing_translation_margin": self.settings.routing_translation_margin,
                "score_source": self.settings.routing_score_source,
                "intent_margin": self.settings.routing_intent_margin,
                "abstention_threshold": self.settings.routing_abstention_threshold,
                "abstention_thresholds": self.settings.routing_abstention_thresholds,
                "rerank_abstention_thresholds": self.settings.routing_rerank_abstention_thresholds,
                "embedding_model": self.settings.embedding_model_name,
            },
            "summary": summarize(records, self.settings, calibration),
            "records": records,
            "calibration_records": calibration_records,
        }
        report["report_path"] = str(self._write_report(report))
        return report

    def _write_report(self, payload: dict[str, Any]) -> Path:
        """JSON report, plus the precision / recall curve as SVG next to it."""
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self.settings.reports_dir / f"routing-{timestamp}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        path.with_suffix(".svg").write_text(render_curve_svg(payload["summary"]["curve"]), encoding="utf-8")
        return path


def render_markdown(summary: dict[str, Any]) -> str:
    """Short French summary: language, corpus, latency and the candidate points."""
    latency = summary["latency"]
    lines = [
        f"- Langue : {summary['language_accuracy']:.1%} de bonnes détections",
        f"- Corpus : {summary['corpus_routing_accuracy']:.1%} des questions in-scope routées vers le bon corpus"
        if summary["corpus_routing_accuracy"] is not None
        else "- Corpus : pas de question in-scope",
        f"- Latence du routeur : p50 {latency['router_total'].get('p50_ms')} ms, "
        f"p95 {latency['router_total'].get('p95_ms')} ms "
        f"(hors embedding : p95 {latency['router_without_embed'].get('p95_ms')} ms)",
        "",
        "| Point | Marge intention | Seuil | Précision | Rappel | F1 | Fausses abstentions |",
        "|---|---|---|---|---|---|---|",
    ]
    selected = summary["candidates"].get("selected")
    target = summary.get("target_recall", TARGET_RECALL)
    if selected is not None:
        verdict = "atteint" if selected["recall"] >= target else "non atteint"
        lines.insert(
            -3,
            f"- Point retenu (marge 0,02, faux refus < 5 %) : rappel {selected['recall']:.3f}, "
            f"objectif {target:.2f} {verdict}",
        )
    for name, point in summary["candidates"].items():
        if point is None:
            lines.append(f"| {name} | — | — | — | — | — | — |")
            continue
        margin = "ignorée" if point["intent_margin"] is None else point["intent_margin"]
        lines.append(
            f"| {name} | {margin} | {format_threshold(point)} | {point['precision']:.3f} | {point['recall']:.3f} "
            f"| {point['f1']:.3f} | {point['false_abstention_rate']:.1%} |"
        )
    return "\n".join(lines)


def format_threshold(point: dict[str, Any]) -> str:
    threshold = point["threshold"]
    if isinstance(threshold, dict):
        values = ", ".join(f"{corpus} {value}" for corpus, value in threshold.items())
        return f"par corpus, q{point['calibration_quantile']:g} ({values})"
    return str(threshold)


def render_curve_svg(curve: list[dict[str, Any]], *, width: int = 520, height: int = 400) -> str:
    """Precision / recall curves (no plotting dependency).

    Solid lines: one global threshold; dashed: per-corpus thresholds from the
    calibration quantiles. A few intent margins only, to stay readable.
    """
    pad = 48
    colors = ["#64748b", "#2563eb", "#0891b2", "#16a34a", "#ca8a04", "#ea580c", "#dc2626"]

    def x(recall: float) -> float:
        return pad + recall * (width - 2 * pad)

    def y(precision: float) -> float:
        return height - pad - precision * (height - 2 * pad)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" '
        'font-size="11">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<line x1="{pad}" y1="{y(0)}" x2="{x(1)}" y2="{y(0)}" stroke="#333"/>',
        f'<line x1="{pad}" y1="{y(0)}" x2="{pad}" y2="{y(1)}" stroke="#333"/>',
        f'<text x="{width / 2}" y="{height - 12}" text-anchor="middle">rappel (abstention)</text>',
        f'<text x="14" y="{height / 2}" transform="rotate(-90 14 {height / 2})" text-anchor="middle">précision</text>',
    ]
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<text x="{x(tick)}" y="{y(0) + 14}" text-anchor="middle">{tick:g}</text>')
        parts.append(f'<text x="{pad - 6}" y="{y(tick) + 4}" text-anchor="end">{tick:g}</text>')
    shown = [margin for margin in (None, 0.0, 0.02, 0.05) if any(p["intent_margin"] == margin for p in curve)]
    line = 0
    for index, margin in enumerate(shown):
        color = colors[index % len(colors)]
        for mode, dash in (("global", ""), ("per_corpus", ' stroke-dasharray="5 3"')):
            # Traced in threshold order (global) or quantile order (per corpus).
            rows = [
                p
                for p in curve
                if p["intent_margin"] == margin
                and p["threshold_mode"] == mode
                and (mode == "per_corpus" or p["threshold"] > 0)
            ]
            if not rows:
                continue
            rows.sort(key=lambda p: p["calibration_quantile"] if mode == "per_corpus" else p["threshold"])
            coords = " ".join(f"{x(p['recall']):.1f},{y(p['precision']):.1f}" for p in rows)
            parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.5"{dash}/>')
            label = "intention ignorée" if margin is None else f"marge {margin:+g}"
            label += ", seuil global" if mode == "global" else ", seuils par corpus"
            parts.append(f'<text x="{x(0.02):.0f}" y="{y(0.02) - 14 * line - 4:.0f}" fill="{color}">{label}</text>')
            line += 1
    parts.append("</svg>")
    return "\n".join(parts)


def live_abstentions(report: dict[str, Any]) -> list[bool]:
    """Abstention of each record of a live report: the router's own decision
    when recorded, else margin and configured thresholds replayed (reports
    written before `router_abstain` existed)."""
    records = report["records"]
    if records and all("router_abstain" in r for r in records):
        return [bool(r["router_abstain"]) for r in records]
    config = report["config"]
    corpus_thresholds = config.get("abstention_thresholds") or {}
    language_thresholds = config.get("language_abstention_thresholds") or {}
    by_language = bool(config.get("routing_language_thresholds"))

    def threshold(record: dict[str, Any]) -> float:
        corpus = record["corpus_routed"] or ""
        value = (language_thresholds.get(corpus) or {}).get(record.get("language_detected") or "")
        if by_language and value is not None:
            return float(value)
        return float(corpus_thresholds.get(corpus, config.get("abstention_threshold") or 0.0))

    return [
        predict_abstain(record, margin=config.get("intent_margin"), threshold=threshold(record)) for record in records
    ]


def paired_live(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Exact McNemar between two live reports on the same questions: per
    in-scope set, answered from the right passage (right corpus, not
    declined, expected passage retrieved); on the abstention set, declined."""
    from raglab.benchmarks.compare import mcnemar_exact

    def outcomes(report: dict[str, Any]) -> dict[tuple[str, str], tuple[str, bool]]:
        result = {}
        for record, declined in zip(report["records"], live_abstentions(report), strict=True):
            if record["category"] == "in_scope":
                ok = record["corpus_routed"] == record["expected_corpus"] and not declined and bool(record["hit"])
                result[(record["id"], record["source"])] = (record["source"], ok)
            else:
                result[(record["id"], record["source"])] = ("abstention", declined)
        return result

    first, second = outcomes(before), outcomes(after)
    groups: dict[str, dict[str, Any]] = {}
    for key, (group, value) in second.items():
        previous = first[key][1]
        entry = groups.setdefault(group, {"before": 0, "after": 0, "gained": 0, "lost": 0})
        entry["before"] += previous
        entry["after"] += value
        entry["gained"] += value and not previous
        entry["lost"] += previous and not value
    for entry in groups.values():
        entry["p_value"] = round(mcnemar_exact(entry["gained"], entry["lost"]), 4)
    return dict(sorted(groups.items()))
