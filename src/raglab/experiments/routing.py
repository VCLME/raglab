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
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.experiments.recall import _chunk_covers_span, _percentile
from raglab.retrieval.service import QueryService
from raglab.routing.abstention import best_score, threshold_for
from raglab.routing.citation import cited_text_in_run
from raglab.routing.intent import decide_intent
from raglab.routing.router import QueryRouter
from raglab.routing.schemas import Intent

REPO_ROOT = Path(__file__).resolve().parents[3]
ABSTENTION_PATH = REPO_ROOT / "benchmarks" / "abstention" / "questions.jsonl"


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


def available_sets(in_scope_sets: tuple[InScopeSet, ...], corpora: list[str] | None = None) -> tuple[InScopeSet, ...]:
    """Sets whose questions exist and whose corpus the router may choose.

    With `--corpus` given, only those corpora's sets are evaluated, so
    `--corpus bench_piaf_fr --corpus bench_lexml_pt` keeps measuring exactly
    the PIAF + LexML sample, whatever other corpora are indexed.
    """
    return tuple(s for s in in_scope_sets if s.path.exists() and (not corpora or s.corpus_name in corpora))


def _row_language(in_scope: InScopeSet, row: dict[str, Any]) -> str:
    return row.get("language") or (row.get("context") or {}).get("question_language") or in_scope.language


# Intent margins swept; None = intent ignored (abstention on the score only).
INTENT_MARGINS: tuple[float | None, ...] = (None, -0.05, -0.02, 0.0, 0.02, 0.05, 0.1)
# Per-corpus thresholds: this quantile of the best scores of in-scope
# calibration questions, so about that share of in-scope questions abstain.
CALIBRATION_QUANTILES = (0.01, 0.02, 0.03, 0.05, 0.1, 0.15, 0.2)

# A threshold is global (float) or per corpus (corpus name -> float).
Threshold = float | dict[str, float]


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
                    expected_corpus=in_scope.corpus_name,
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
                    expected_corpus=in_scope.corpus_name,
                )
            )
    return cases


def quantile(values: list[float], fraction: float) -> float:
    """Lower nearest-rank quantile: about `fraction` of the values fall below."""
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(fraction * len(ordered)) - 1))]


def calibrated_thresholds(calibration: dict[str, list[float]], fraction: float) -> dict[str, float]:
    return {corpus: round(quantile(scores, fraction), 4) for corpus, scores in sorted(calibration.items()) if scores}


def _threshold_for(threshold: Threshold, record: dict[str, Any]) -> float:
    if isinstance(threshold, dict):
        return threshold.get(record["corpus_routed"], 0.0)
    return threshold


def predict_abstain(record: dict[str, Any], *, margin: float | None, threshold: Threshold) -> bool:
    # Same rule as the router: a question citing a law is never declined.
    if record.get("legal_citation"):
        return False
    if margin is not None and decide_intent(record["intent_scores"], margin=margin) != Intent.DOCUMENTARY:
        return True
    score = record["best_score"]
    return score is None or score < _threshold_for(threshold, record)


def abstention_metrics(
    records: list[dict[str, Any]],
    *,
    margin: float | None,
    threshold: Threshold,
    calibration_quantile: float | None = None,
) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    by_category: dict[str, list[bool]] = {}
    for record in records:
        predicted = predict_abstain(record, margin=margin, threshold=threshold)
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
    return {
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
    configured_thresholds = {
        corpus: threshold_for(settings, corpus)
        for corpus in sorted({r["corpus_routed"] for r in records if r["corpus_routed"]})
    }
    configured = abstention_metrics(records, margin=settings.routing_intent_margin, threshold=configured_thresholds)
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
        "calibration": {
            corpus: {
                "questions": len(scores),
                **{f"q{fraction:g}": round(quantile(scores, fraction), 4) for fraction in CALIBRATION_QUANTILES},
            }
            for corpus, scores in sorted((calibration or {}).items())
            if scores
        },
        "latency": {
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
        abstention_path: Path = ABSTENTION_PATH,
        in_scope_sets: tuple[InScopeSet, ...] = IN_SCOPE_SETS,
    ) -> dict[str, Any]:
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
        }
        # Warm-up: model weights, example embeddings and corpus centroids are
        # loaded once per process and kept out of the latency figures.
        warm_up = router.route("warm-up", strategy=strategy, candidate_corpora=corpora or None)
        runs = {candidate.corpus_name: candidate.index_run_id for candidate in warm_up.corpus.candidates}

        records: list[dict[str, Any]] = []
        for case in cases:
            decision = router.route(case.question, strategy=strategy, candidate_corpora=corpora or None)
            if decision.corpus.index_run_id is None:
                raise ValueError("Aucun index compatible avec l'embedder du routeur : indexez au moins un corpus.")
            outcome = retriever.retrieve(
                question=case.question,
                index_run_id=decision.corpus.index_run_id,
                top_k=top_k,
                **retrieval_options,
            )
            chunks = [chunk.model_dump() for chunk in outcome.retrieved]
            records.append(
                {
                    **{k: v for k, v in asdict(case).items() if k != "expected_spans"},
                    "language_detected": decision.language.language,
                    "language_method": decision.language.method,
                    "intent_scores": decision.intent.scores,
                    "corpus_routed": decision.corpus.corpus_name,
                    "corpus_margin": decision.corpus.margin,
                    "corpus_scores": {c.corpus_name: c.score for c in decision.corpus.candidates},
                    # Same rule as the router: a cited text the index holds.
                    "legal_citation": decision.citation is not None
                    and cited_text_in_run(self.session, outcome.index_run, decision.citation),
                    "best_score": best_score(outcome.retrieved, self.settings.routing_score_source),
                    "scores": [round(chunk.score, 4) for chunk in outcome.retrieved],
                    "hit": any(_chunk_covers_span(chunk, span) for chunk in chunks for span in case.expected_spans),
                    "timings_ms": decision.timings_ms,
                }
            )

        calibration: dict[str, list[float]] = {}
        calibration_cases = load_calibration(
            in_scope_sets=in_scope_sets,
            exclude_ids={case.id for case in cases},
            size=calibration_size,
            seed=seed + 1,
        )
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
            if score is not None:
                calibration.setdefault(case.expected_corpus, []).append(score)

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
                "retrieval_mode": (retrieval_mode or RetrievalMode(self.settings.default_retrieval_mode)).value,
                "rerank": self.settings.default_rerank if rerank is None else rerank,
                "citations": self.settings.citation_resolver if citations is None else citations,
                "score_source": self.settings.routing_score_source,
                "intent_margin": self.settings.routing_intent_margin,
                "abstention_threshold": self.settings.routing_abstention_threshold,
                "abstention_thresholds": self.settings.routing_abstention_thresholds,
                "embedding_model": self.settings.embedding_model_name,
            },
            "summary": summarize(records, self.settings, calibration),
            "records": records,
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
