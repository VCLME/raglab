"""Intent generalization study (docs/intentions.md, second part).

PR #80's kNN + logistic intent kept 70 of the 80 frozen refusals but
declined first-person questions of real users (BR Expat). This study
compares intent variants on live `experiment routing` reports: routing and
retrieval do not depend on the intent, so each record keeps its corpus,
passages and scores, and only the decision is replayed (the replay of the
default and of #80's option is checked against the recorded live decisions).

Three roles, kept apart:
- training: labelled examples (`examples.py`, `benchmarks/routing/
  intent_training.jsonl`) and calibration questions as documentary
  neighbours / positives;
- calibration: per (corpus, language) in-scope questions and their dense
  scores (thresholds, joint rule, logistic cut), out of fold when they are
  also training data;
- evaluation: development reports (frozen sets) choose the variant;
  the independent validation report (`benchmarks/routing_validation/`) is
  read once, with the variant already fixed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from raglab.benchmarks.compare import mcnemar_exact
from raglab.experiments.recall import _percentile
from raglab.experiments.routing import (
    CALIBRATION_FILES,
    MAX_FALSE_ABSTENTION,
    REPO_ROOT,
    SELECTED_INTENT_MARGIN,
    load_calibration_files,
    quantile,
)
from raglab.routing.examples import iter_examples
from raglab.routing.intent import IntentClassifier, decide_intent, normalize
from raglab.routing.intent_knn import build_joint_calibration, fit_logistic, joint_score, parse_joint_calibration
from raglab.routing.schemas import Intent

TRAINING_PATH = REPO_ROOT / "benchmarks" / "routing" / "intent_training.jsonl"
LOGISTIC_SCALE = 20.0
LOGISTIC_FOLDS = 5
# Pairs calibrated by #78, the only ones #80's joint rule used.
FIRST_PAIRS = frozenset({("bench_piaf_fr", "fr"), ("bench_lexml_pt", "fr"), ("bench_lexml_pt", "pt")})


def load_training(path: Path = TRAINING_PATH) -> list[tuple[str, str, str]]:
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [(row["intent"], row["language"], row["text"]) for row in rows]


@dataclass(frozen=True)
class CalibrationRow:
    corpus: str
    language: str
    question: str
    dense: float | None


def calibration_rows(
    collect_report: dict[str, Any], examples_path: Path, live_reports: Iterable[dict[str, Any]] = ()
) -> list[CalibrationRow]:
    """#78's calibration (PIAF and LexML, from its collection pass) plus the
    per-question calibration records of live reports (other pairs)."""
    texts = {}
    for line in examples_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            texts[(row["id"], row["language"])] = row["question"]
    rows = [
        CalibrationRow(
            row["corpus"], row["language"], row.get("question") or texts[(row["id"], row["language"])], row.get("dense")
        )
        for row in collect_report["calibration"]
    ]
    known = {(row.corpus, row.language) for row in rows}
    # A calibration file may have lost rows since the run (overlap checks):
    # only questions still in the file count.
    current = {case.question for case in load_calibration_files(list(CALIBRATION_FILES))}
    for report in live_reports:
        for row in report.get("calibration_records") or []:
            if str(row.get("source", "")).startswith("calibration:") and row["question"] not in current:
                continue
            if (row["corpus"], row["language"]) not in known:
                rows.append(CalibrationRow(row["corpus"], row["language"], row["question"], row.get("dense")))
    return rows


class Embeddings:
    """Embedding of every text once (CPU, e5-small)."""

    def __init__(self, embedder: Any):
        self.embedder = embedder
        self.cache: dict[str, np.ndarray] = {}

    def __call__(self, text: str) -> np.ndarray:
        if text not in self.cache:
            self.cache[text] = normalize(self.embedder.embed_query(text))
        return self.cache[text]

    def matrix(self, texts: list[str]) -> np.ndarray:
        return np.stack([self(text) for text in texts])


# ---------------------------------------------------------------- variants


@dataclass(frozen=True)
class Variant:
    """One way to decide. `examples`: "base", "more" (#80) or "first_person"
    (+ intent_training.jsonl). `pairs`: calibrated (corpus, language) pairs
    used as documentary neighbours and by the joint rule ("first" = #78's
    three, "all")."""

    name: str
    intent: str = "centroids"  # centroids | knn | knn_logistic | logistic
    examples: str = "base"
    pairs: str = "first"
    k: int = 20
    logistic_cut: float | None = None
    joint: float | None = None
    # Per-language dense thresholds (quantile) for calibrated pairs without one in production.
    new_thresholds: float | None = None

    def label(self) -> str:
        parts = [self.intent, f"exemples {self.examples}", f"couples {self.pairs}"]
        if self.intent.startswith("knn"):
            parts.append(f"k={self.k}")
        if self.logistic_cut is not None:
            parts.append(f"logistique q{self.logistic_cut:g}")
        if self.joint is not None:
            parts.append(f"jointe q{self.joint:g}")
        if self.new_thresholds is not None:
            parts.append(f"seuils nouveaux couples q{self.new_thresholds:g}")
        return ", ".join(parts)


DEFAULT = Variant("default")
PR80 = Variant("pr80", "knn_logistic", "more", "first", 20, 0.97, 0.03)


def variant_grid() -> list[Variant]:
    """Small grid; the development reports pick one variant per family."""
    grid = [DEFAULT, PR80, Variant("pr80_no_logistic", "knn", "more", "first", 20, None, 0.03)]
    grid += [Variant(f"thresholds_q{q:g}", new_thresholds=q) for q in (0.02, 0.03)]
    grid += [Variant(f"centroids_first_person_{p}", "centroids", "first_person", p) for p in ("first", "all")]
    for pairs in ("first", "all"):
        for k in (10, 20):
            grid.append(Variant(f"knn_fp_{pairs}_k{k}", "knn", "first_person", pairs, k))
            for joint in (0.02, 0.03):
                grid.append(Variant(f"knn_fp_{pairs}_k{k}_j{joint:g}", "knn", "first_person", pairs, k, None, joint))
                for cut in (0.97, 0.98, 0.99):
                    grid.append(
                        Variant(
                            f"knn_lr_fp_{pairs}_k{k}_c{cut:g}_j{joint:g}",
                            "knn_logistic",
                            "first_person",
                            pairs,
                            k,
                            cut,
                            joint,
                        )
                    )
        for cut in (0.97, 0.98, 0.99):
            grid.append(Variant(f"lr_fp_{pairs}_c{cut:g}", "logistic", "first_person", pairs, 20, cut))
    return grid


@dataclass
class Model:
    """Everything a variant needs, fitted on training and calibration only."""

    variant: Variant
    intent: Callable[[np.ndarray], bool]
    # (corpus, language) -> (calibration margins, dense, joint threshold) for the joint rule.
    joint: dict[tuple[str, str], Any] = field(default_factory=dict)
    margin: Callable[[np.ndarray], float] | None = None
    thresholds: dict[tuple[str, str], float] = field(default_factory=dict)
    # Logistic regression as the router reads it (`intent_logistic.json`).
    logistic: dict[str, Any] | None = None


def _examples(kind: str) -> list[tuple[str, str, str]]:
    rows = list(iter_examples(extended=kind != "base"))
    if kind == "first_person":
        rows += load_training()
    return rows


def build_model(variant: Variant, calibration: list[CalibrationRow], embed: Embeddings) -> Model:
    pairs = (
        [row for row in calibration if (row.corpus, row.language) in FIRST_PAIRS]
        if variant.pairs == "first"
        else calibration
    )
    examples = _examples(variant.examples)
    margin_of = SELECTED_INTENT_MARGIN
    if variant.intent == "centroids":
        classifier = IntentClassifier(embed.embedder, examples) if variant.examples != "base" else None
        base = IntentClassifier(embed.embedder) if classifier is None else classifier
        model = Model(variant, lambda v: decide_intent(base.intent_scores(v), margin=margin_of) != Intent.DOCUMENTARY)
    else:
        texts = [text for _, _, text in examples] + [row.question for row in pairs]
        labels = np.array([intent for intent, _, _ in examples] + [Intent.DOCUMENTARY.value] * len(pairs))
        matrix = embed.matrix(texts)
        documentary = labels == Intent.DOCUMENTARY.value
        k = variant.k

        def knn_margin(v: np.ndarray, exclude: int | None = None) -> float:
            sims = matrix @ v
            keep = np.ones(len(texts), dtype=bool)
            if exclude is not None:
                keep[exclude] = False
            doc = np.sort(sims[documentary & keep])[-k:].mean()
            other = np.sort(sims[~documentary & keep])[-k:].mean()
            return float(doc - other)

        refuse_knn = (lambda v: knn_margin(v) < -margin_of) if variant.intent.startswith("knn") else (lambda v: False)
        refuse_logistic: Callable[[np.ndarray], bool] = lambda v: False  # noqa: E731
        if variant.logistic_cut is not None:
            y = (~documentary).astype(float)
            weights, bias = fit_logistic(matrix, y, scale=LOGISTIC_SCALE)
            n_examples = len(examples)
            folds = np.arange(len(pairs)) % LOGISTIC_FOLDS
            oof = np.zeros(len(pairs))
            for fold in range(LOGISTIC_FOLDS):
                keep = np.concatenate([np.ones(n_examples, dtype=bool), folds != fold])
                w, b = fit_logistic(matrix[keep], y[keep], scale=LOGISTIC_SCALE)
                held = matrix[n_examples:][folds == fold]
                oof[folds == fold] = 1 / (1 + np.exp(-(held * LOGISTIC_SCALE @ w + b)))
            cut = quantile(list(oof), variant.logistic_cut)
            refuse_logistic = lambda v: float(1 / (1 + np.exp(-(LOGISTIC_SCALE * float(v @ weights) + bias)))) > cut  # noqa: E731
        model = Model(variant, lambda v: refuse_knn(v) or refuse_logistic(v), margin=knn_margin)
        if variant.logistic_cut is not None:
            model.logistic = {
                "k": k,
                "quantile": variant.joint or 0.0,
                "score": "dense",
                "groups": {},
                "examples": variant.examples,
                "pairs": variant.pairs,
                "logistic": {
                    "weights": [round(float(w), 6) for w in weights],
                    "bias": round(float(bias), 6),
                    "scale": LOGISTIC_SCALE,
                    "threshold": round(float(cut), 4),
                    "quantile": variant.logistic_cut,
                },
            }
        if variant.joint is not None:
            offset = len(examples)
            rows = [
                (row.corpus, row.language, knn_margin(embed(row.question), exclude=offset + j), row.dense)
                for j, row in enumerate(pairs)
                if row.dense is not None
            ]
            payload = build_joint_calibration(rows, k=k, quantile=variant.joint, rank_quantile=quantile)
            calibrated = parse_joint_calibration(payload)
            model.joint = {
                (corpus, language): group
                for corpus, by_language in calibrated.groups.items()
                for language, group in by_language.items()
            }
    if variant.new_thresholds is not None:
        groups: dict[tuple[str, str], list[float]] = {}
        for row in calibration:
            if (row.corpus, row.language) not in FIRST_PAIRS and row.dense is not None:
                groups.setdefault((row.corpus, row.language), []).append(row.dense)
        model.thresholds = {key: quantile(values, variant.new_thresholds) for key, values in groups.items()}
    return model


def decide(model: Model, record: dict[str, Any], vector: np.ndarray) -> bool:
    """Abstention of one live record under a variant (same order as the router)."""
    if record.get("legal_citation"):
        return False
    if model.intent(vector):
        return True
    production = record.get("router_abstention") or {}
    score = production.get("best_score", record.get("best_score"))
    if score is None:
        return True
    pair = (record["corpus_routed"], record["language_detected"])
    dense = record.get("dense_original", record.get("best_score_original"))
    group = model.joint.get(pair)
    if group is not None and dense is not None and model.margin is not None:
        return joint_score(group, model.margin(vector), dense) < group.threshold
    if pair in model.thresholds and dense is not None:
        return dense < model.thresholds[pair]
    threshold = production.get("threshold", None)
    return threshold is not None and score < threshold


def answered(record: dict[str, Any], declined: bool) -> bool:
    return record["corpus_routed"] == record["expected_corpus"] and not declined and bool(record["hit"])


def evaluate(model: Model, report: dict[str, Any], embed: Embeddings) -> list[bool]:
    return [decide(model, record, embed(record["question"])) for record in report["records"]]


def metrics(report: dict[str, Any], decisions: list[bool], reference: list[bool] | None = None) -> dict[str, Any]:
    records = report["records"]
    in_scope = [(r, d) for r, d in zip(records, decisions, strict=True) if r["category"] == "in_scope"]
    declinable = [(r, d) for r, d in zip(records, decisions, strict=True) if r["category"] != "in_scope"]
    by_set: dict[str, dict[str, Any]] = {}
    for record, declined in in_scope:
        key = (
            f"{record['source']}:{record['expected_corpus']}"
            if record["source"].startswith("validation")
            else record["source"]
        )
        entry = by_set.setdefault(key, {"questions": 0, "refused": 0, "answered": 0})
        entry["questions"] += 1
        entry["refused"] += declined
        entry["answered"] += answered(record, declined)
    by_language: dict[str, dict[str, int]] = {}
    for record, declined in in_scope:
        entry = by_language.setdefault(record["language"], {"questions": 0, "refused": 0})
        entry["questions"] += 1
        entry["refused"] += declined
    result = {
        "refusals_kept": sum(d for _, d in declinable),
        "declinable": len(declinable),
        "recall": round(sum(d for _, d in declinable) / len(declinable), 4) if declinable else 0.0,
        "by_category": dict(sorted(Counter(r["category"] for r, d in declinable if d).items())),
        "false_refusals": sum(d for _, d in in_scope),
        "in_scope": len(in_scope),
        "false_refusal_rate": round(sum(d for _, d in in_scope) / len(in_scope), 4) if in_scope else 0.0,
        "answered": sum(answered(r, d) for r, d in in_scope),
        "by_set": dict(sorted(by_set.items())),
        "by_language": dict(sorted(by_language.items())),
    }
    if reference is not None:
        result["paired"] = paired(report, reference, decisions)
    return result


def paired(report: dict[str, Any], before: list[bool], after: list[bool]) -> dict[str, dict[str, Any]]:
    """McNemar per in-scope set (answered from the right passage) and on refusals."""
    groups: dict[str, list[tuple[bool, bool]]] = {}
    for record, b, a in zip(report["records"], before, after, strict=True):
        if record["category"] == "in_scope":
            key = (
                f"{record['source']}:{record['expected_corpus']}"
                if record["source"].startswith("validation")
                else record["source"]
            )
            groups.setdefault(key, []).append((answered(record, b), answered(record, a)))
        else:
            groups.setdefault("abstention", []).append((b, a))
    result = {}
    for key, values in sorted(groups.items()):
        gained = sum(1 for x, y in values if y and not x)
        lost = sum(1 for x, y in values if x and not y)
        result[key] = {"gained": gained, "lost": lost, "p_value": round(mcnemar_exact(gained, lost), 4)}
    return result


def eligible(result: dict[str, Any]) -> bool:
    """Owner's rule on one report: false refusals strictly under 5 % and no
    significant loss of answered questions on any set."""
    losses = [
        pair
        for key, pair in (result.get("paired") or {}).items()
        if key != "abstention" and pair["lost"] > pair["gained"] and pair["p_value"] < 0.05
    ]
    return result["false_refusal_rate"] < MAX_FALSE_ABSTENTION and not losses


def intent_latency_ms(model: Model, vectors: np.ndarray, repeat: int = 3) -> dict[str, float]:
    """Time of the intent decision alone, per question (embedding excluded)."""
    from time import perf_counter

    times = []
    for _ in range(repeat):
        for vector in vectors:
            started = perf_counter()
            model.intent(vector)
            if model.margin is not None and model.joint:
                model.margin(vector)
            times.append((perf_counter() - started) * 1000)
    return {"p50_ms": round(_percentile(times, 0.5), 3), "p95_ms": round(_percentile(times, 0.95), 3)}


# ---------------------------------------------------------------- study


def family(variant: Variant) -> str:
    """Variants differing only by a level (k, cut, quantile) share a family."""
    if variant.name in ("default", "pr80", "pr80_no_logistic"):
        return variant.name
    parts = [variant.intent, variant.examples, variant.pairs]
    parts.append("jointe" if variant.joint is not None else "seuils")
    if variant.new_thresholds is not None:
        parts.append("seuils_nouveaux_couples")
    return "/".join(parts)


def study(
    dev: dict[str, dict[str, Any]],
    test: dict[str, dict[str, Any]],
    calibration: list[CalibrationRow],
    embedder: Any,
    grid: list[Variant] | None = None,
) -> dict[str, Any]:
    """Pick on `dev` (report name -> report), then read `test` once.

    Selection (owner's rule, on every development report): false refusals
    strictly under 5 % and no significant loss of answered questions; among
    those, the most refusals kept on the worst report, then the fewest false
    refusals. The best variant of each family is also read on `test`, so
    the chosen one is compared with its alternatives there too."""
    embed = Embeddings(embedder)
    grid = grid or variant_grid()
    default_model = build_model(DEFAULT, calibration, embed)
    reference = {name: evaluate(default_model, report, embed) for name, report in dev.items()}
    rows: list[dict[str, Any]] = []
    models: dict[str, Model] = {}
    for variant in grid:
        model = build_model(variant, calibration, embed)
        models[variant.name] = model
        results = {
            name: metrics(report, evaluate(model, report, embed), reference[name]) for name, report in dev.items()
        }
        rows.append(
            {
                "name": variant.name,
                "family": family(variant),
                "label": variant.label(),
                "eligible": all(eligible(result) for result in results.values()),
                "dev": results,
            }
        )

    def key(row: dict[str, Any]) -> tuple[float, float]:
        results = row["dev"].values()
        return (min(r["refusals_kept"] for r in results), -sum(r["false_refusal_rate"] for r in results))

    eligible_rows = [row for row in rows if row["eligible"]]
    selected = max(eligible_rows, key=key) if eligible_rows else None
    best_by_family: dict[str, dict[str, Any]] = {}
    for row in eligible_rows:
        current = best_by_family.get(row["family"])
        if current is None or key(row) > key(current):
            best_by_family[row["family"]] = row
    read_on_test = ["default", "pr80"] + [row["name"] for row in best_by_family.values()]
    read_on_test = list(dict.fromkeys(read_on_test + ([selected["name"]] if selected else [])))
    test_results: dict[str, Any] = {}
    for name in read_on_test:
        model = models[name]
        test_results[name] = {}
        for report_name, report in test.items():
            baseline = evaluate(models["default"], report, embed)
            test_results[name][report_name] = metrics(report, evaluate(model, report, embed), baseline)
    latency_vectors = embed.matrix([r["question"] for report in dev.values() for r in report["records"]][:200])
    return {
        "selected": selected["name"] if selected else None,
        "grid": rows,
        "best_by_family": {k: v["name"] for k, v in best_by_family.items()},
        "test": test_results,
        "intent_latency": {name: intent_latency_ms(models[name], latency_vectors) for name in read_on_test},
    }


def render(result: dict[str, Any]) -> str:
    """French table: development then validation, per variant read on validation."""
    lines = []
    for name in result["test"]:
        row = next(r for r in result["grid"] if r["name"] == name)
        lines.append(f"### {name}{' (retenu)' if name == result['selected'] else ''} : {row['label']}")
        for scope, results in (("dev", row["dev"]), ("validation", result["test"][name])):
            for report_name, m in results.items():
                pair = (m.get("paired") or {}).get("abstention") or {}
                lines.append(
                    f"- {scope} {report_name} : refus {m['refusals_kept']}/{m['declinable']} "
                    f"(+{pair.get('gained', 0)}/-{pair.get('lost', 0)}), faux refus {m['false_refusals']}/{m['in_scope']} "
                    f"({m['false_refusal_rate']:.1%}), répondues {m['answered']}"
                )
    return "\n".join(lines)


def export_logistic(name: str, calibration: list[CalibrationRow], embedder: Any) -> dict[str, Any]:
    """Model file of a logistic variant of the grid, as the router reads it
    (`routing_intent_logistic_path`)."""
    variant = next((v for v in variant_grid() if v.name == name), None)
    if variant is None or variant.logistic_cut is None:
        raise ValueError(f"Variante logistique inconnue: {name}")
    model = build_model(variant, calibration, Embeddings(embedder))
    assert model.logistic is not None
    return {"variant": name, **model.logistic}
