"""Check that a RAGAS judge tells good answers from bad ones.

A judge score is only worth reporting if the judge can be trusted. This
module builds answers whose verdict is known in advance, from the frozen
PIAF set (gold paragraph = context, annotated answer = truth), and measures
how often each judge agrees:

* ``faithful``      — the annotated answer, stated from the context → faithful;
* ``fabricated``    — the answer of another paragraph's question, stated as
  if true → not faithful;
* ``embellished``   — the correct answer plus one claim absent from the
  context → not faithful (the subtle case, where weak judges fail);
* ``on_topic``      — answers the question → relevant;
* ``off_topic``     — answers another question about the same paragraph →
  not relevant.

A verdict counts as "positive" when the judge's score is >= 0.5.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raglab.config import Settings, get_settings
from raglab.experiments.ragas import AnswerRelevancyJudge, FaithfulnessJudge, JudgeConfig
from raglab.llm.local_server import LocalLLMServer
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

# Unsupported but plausible additions, written so they never appear in a
# Wikipedia paragraph about the topic.
_EMBELLISHMENTS = (
    "Ce point a été confirmé par une décision du Conseil d'État en 2019.",
    "Selon un rapport de l'UNESCO publié en 1987, ce chiffre a depuis doublé.",
    "Cette information figure aussi dans le traité de Lisbonne.",
    "Un recensement de 2021 a d'ailleurs montré une hausse de 40 %.",
)


@dataclass(slots=True)
class CalibrationItem:
    kind: str  # faithfulness | relevancy
    variant: str
    expected: bool
    question: str
    context: str
    answer: str


def build_items(ground_truth_path: Path, corpus_dir: Path, *, count: int = 30, seed: int = 7) -> list[CalibrationItem]:
    cases = [json.loads(line) for line in ground_truth_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [case for case in cases if case.get("ground_truth_answer")]
    by_file: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_file.setdefault(case["expected_file_names"][0], []).append(case)
    rng = random.Random(seed)
    # Prefer paragraphs with at least two questions: the off-topic variant
    # needs a second question about the same context.
    eligible = sorted(name for name, group in by_file.items() if len(group) >= 2)
    rng.shuffle(eligible)
    items: list[CalibrationItem] = []
    for index, file_name in enumerate(eligible[:count]):
        case, other = by_file[file_name][:2]
        context = (corpus_dir / file_name).read_text(encoding="utf-8")
        answer = case["ground_truth_answer"]
        foreign = cases[(cases.index(case) + len(cases) // 2) % len(cases)]["ground_truth_answer"]
        items += [
            CalibrationItem("faithfulness", "faithful", True, case["question"], context, f"{answer}."),
            CalibrationItem("faithfulness", "fabricated", False, case["question"], context, f"{foreign}."),
            CalibrationItem(
                "faithfulness",
                "embellished",
                False,
                case["question"],
                context,
                f"{answer}. {_EMBELLISHMENTS[index % len(_EMBELLISHMENTS)]}",
            ),
            CalibrationItem("relevancy", "on_topic", True, case["question"], context, f"{answer}."),
            CalibrationItem("relevancy", "off_topic", False, case["question"], context, f"{other['ground_truth_answer']}."),
        ]
    return items


def _judges(settings: Settings, config: JudgeConfig) -> tuple[FaithfulnessJudge, AnswerRelevancyJudge]:
    if config.backend == "llamacpp":
        common: dict[str, Any] = {
            "settings": settings,
            "client": OpenAICompatibleChat(settings),
            "model": config.model or settings.judge_model,
            "json_mode": True,
        }
    else:
        common = {"settings": settings, "model": config.model}
    return FaithfulnessJudge(**common), AnswerRelevancyJudge(**common)


def grade(items: list[CalibrationItem], settings: Settings, config: JudgeConfig) -> dict[str, Any]:
    faithfulness, relevancy = _judges(settings, config)
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.kind == "faithfulness":
            verdict = faithfulness.score(question=item.question, answer=item.answer, retrieved_texts=[item.context])
        else:
            verdict = relevancy.score(question=item.question, answer=item.answer)
        rows.append({"variant": item.variant, "expected": item.expected, "score": verdict.score})
    return summarise(rows) | {"judge": config.label(settings), "rows": rows}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy per variant and per metric; unparsable verdicts count as wrong."""
    per_variant: dict[str, list[bool]] = {}
    unparsed = 0
    for row in rows:
        if row["score"] is None:
            unparsed += 1
            correct = False
        else:
            correct = (row["score"] >= 0.5) == row["expected"]
        per_variant.setdefault(row["variant"], []).append(correct)
    accuracy = {variant: round(sum(flags) / len(flags), 3) for variant, flags in sorted(per_variant.items())}
    groups = {"faithfulness": ("faithful", "fabricated", "embellished"), "answer_relevancy": ("on_topic", "off_topic")}
    by_metric = {}
    for metric, variants in groups.items():
        flags = [flag for variant in variants for flag in per_variant.get(variant, [])]
        if flags:
            by_metric[metric] = round(sum(flags) / len(flags), 3)
    return {"accuracy_by_variant": accuracy, "accuracy_by_metric": by_metric, "unparsed": unparsed}


def calibrate(
    *,
    ground_truth_path: Path,
    corpus_dir: Path,
    judges: list[JudgeConfig],
    count: int = 30,
    seed: int = 7,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    items = build_items(ground_truth_path, corpus_dir, count=count, seed=seed)
    results = []
    for config in judges:
        if config.backend == "llamacpp":
            with LocalLLMServer(settings, profile=config.profile or settings.judge_model_profile):
                results.append(grade(items, settings, config))
        else:
            results.append(grade(items, settings, config))
        log_event(
            LOGGER,
            logging.INFO,
            "judge_calibration.graded",
            judge=results[-1]["judge"],
            accuracy=results[-1]["accuracy_by_metric"],
        )
    return {"items": len(items), "paragraphs": count, "seed": seed, "results": results}
