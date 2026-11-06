"""Answer language on cross-language questions: what to do with the quote.

Same method as docs/benchmarks/prompt.md: retrieval runs once, then every
prompt variant writes its answer from exactly the same passages, so the only
difference between two columns is the prompt (or the writer).

    python scripts/answer_language_eval.py retrieve
    python scripts/answer_language_eval.py generate --variant verbatim --provider ollama
    python scripts/answer_language_eval.py generate --variant translate --provider llamacpp
    python scripts/answer_language_eval.py judge [--runs omit-llamacpp verbatim-llamacpp ...]
    python scripts/answer_language_eval.py report

Sets (seeded, frozen): the English questions of `benchmarks/answer_lang_en/`
(LexML, Code de la consommation) and 40 French questions of
`benchmarks/lexml_fr/` (French on the Portuguese corpus). Variants, the
`cross_language` modes of `build_prompt_bundle` (passages in another
language than the question; same-language prompts are identical):

- `verbatim`: the prompt before answer-lang-en (quote copied as written);
- `translate`: the quote is translated into the question's language;
- `omit`: no quote, the answer cites the passages with [Rank X].

Retrieval uses the production defaults (hybrid + re-ranking, top 5). The
judge is the RAGAS judge of the benchmarks (Gemma 4 on llama.cpp, started
and stopped with LocalLLMServer). Results go to
`benchmarks/results/answer-lang-en-v1.json`; the working files (passages,
answers) to `data/answer_language/`.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raglab.config import get_settings
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.prompts import (
    CROSS_LANGUAGE_MODES,
    NO_CONTEXT_ANSWERS,
    build_prompt_bundle,
    context_language,
    presented_passages,
    question_language,
)
from raglab.routing.language import lexical_scores

SETS = {
    "en_lexml": ("benchmarks/answer_lang_en/lexml.jsonl", "bench_lexml_pt", None),
    "en_legi": ("benchmarks/answer_lang_en/legi_consommation.jsonl", "bench_legi_consommation_fr", None),
    "fr_lexml": ("benchmarks/lexml_fr/ground_truth.jsonl", "bench_lexml_pt", 40),
}
SEED = 42
WORK = Path("data/answer_language")
RESULTS = Path("benchmarks/results/answer-lang-en-v1.json")
VARIANTS = CROSS_LANGUAGE_MODES
# Faithfulness and correctness only: the judge reads ~2 answers a minute,
# and relevancy does not tell the variants apart on the answer language.
METRICS = ("faithfulness", "answer_correctness")


def cases(name: str) -> list[dict[str, Any]]:
    path, _, count = SETS[name]
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: row["id"])
    if count is not None:
        rows = sorted(random.Random(SEED).sample(rows, count), key=lambda row: row["id"])
    return rows


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def retrieve() -> None:
    from raglab.db import session_scope
    from raglab.retrieval.service import QueryService

    passages: dict[str, Any] = {}
    for name in SETS:
        corpus = SETS[name][1]
        for case in cases(name):
            with session_scope() as session:
                outcome = QueryService(session).retrieve(question=case["question"], corpus_name=corpus, top_k=5)
            passages[f"{name}/{case['id']}"] = [chunk.model_dump(mode="json") for chunk in outcome.retrieved]
        print(f"{name}: {len(cases(name))} questions retrieved")
    save(WORK / "passages.json", passages)


def generate(variant: str, provider: str) -> None:
    from contextlib import nullcontext

    from raglab.generation.service import build_generator
    from raglab.llm.local_server import LocalLLMServer

    settings = get_settings()
    passages = load(WORK / "passages.json")
    generator = build_generator(settings, provider)
    server = (
        LocalLLMServer(settings, profile=settings.writer_model_profile) if provider == "llamacpp" else nullcontext()
    )
    answers: dict[str, Any] = {}
    with server:
        for name in SETS:
            for case in cases(name):
                key = f"{name}/{case['id']}"
                chunks = [RetrievedChunk.model_validate(chunk) for chunk in passages[key]]
                bundle = build_prompt_bundle(
                    case["question"],
                    chunks,
                    no_context_answer=settings.generation_no_context_answer,
                    cross_language=variant,
                )
                # The generators build the production prompt themselves: the
                # variant is applied by handing them its messages.
                generator.build_messages = lambda _q, _c, bundle=bundle: bundle.as_messages()
                answers[key] = generator.generate_answer(case["question"], chunks)
            print(f"{variant}/{provider} {name}: done")
    save(WORK / f"answers-{variant}-{provider}.json", answers)


# Sentences of an answer, without citation tags; quotes count like the rest:
# the reader sees them.
_RANK = re.compile(r"\[\s*Rank[^\]]*\]", re.IGNORECASE)
_SPLIT = re.compile(r"(?<=[.!?:;])\s+|\n+|[\"“”«»]")


def foreign_sentences(answer: str, language: str) -> list[str]:
    """Sentences clearly written in another of fr / pt / en: at least 3
    markers of that language and more than of the question's language."""
    foreign = []
    for sentence in _SPLIT.split(_RANK.sub(" ", answer)):
        scores = lexical_scores(sentence)
        other = max((lang for lang in scores if lang != language), key=lambda lang: scores[lang])
        if scores[other] >= 3 and scores[other] > scores[language]:
            foreign.append(sentence.strip())
    return foreign


def refused(answer: str, settings_fallback: str) -> bool:
    fallbacks = [settings_fallback, *NO_CONTEXT_ANSWERS.values()]
    return any(fallback.rstrip(".") in answer for fallback in fallbacks)


def judge(runs: list[str]) -> None:
    from raglab.experiments.ragas import JudgeConfig
    from raglab.experiments.recall import _build_judges
    from raglab.llm.local_server import LocalLLMServer

    settings = get_settings()
    passages = load(WORK / "passages.json")
    path = WORK / "judgments.json"
    judgments: dict[str, Any] = load(path) if path.exists() else {}
    judges = _build_judges(settings, JudgeConfig())
    with LocalLLMServer(settings, profile=settings.judge_model_profile):
        for run in runs:
            answers_path = WORK / f"answers-{run}.json"
            grades = judgments.setdefault(run, {})
            for name in SETS:
                for case in cases(name):
                    key = f"{name}/{case['id']}"
                    if key in grades:
                        continue
                    answer = load(answers_path)[key]
                    chunks = [RetrievedChunk.model_validate(chunk) for chunk in passages[key]]
                    verdicts = {
                        "faithfulness": judges["faithfulness"].score(
                            question=case["question"], answer=answer, retrieved_texts=presented_passages(chunks)
                        ),
                        "answer_correctness": judges["answer_correctness"].score(
                            question=case["question"], answer=answer, ground_truth=case["ground_truth_answer"]
                        ),
                    }
                    grades[key] = {metric: verdict.score for metric, verdict in verdicts.items()}
                    save(path, judgments)
            print(f"{run}: judged")


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def paired(runs: dict[str, Any], before: str, after: str) -> dict[str, Any]:
    """`after` minus `before` on the same questions, all sets pooled: mean
    difference per judge metric with its 95% paired-bootstrap interval."""
    from raglab.benchmarks.compare import paired_bootstrap

    result: dict[str, Any] = {"before": before, "after": after}
    for metric in METRICS:
        pairs = [
            (a[metric], b[metric])
            for name in SETS
            for a, b in zip(runs[before][name]["details"], runs[after][name]["details"], strict=True)
            if a.get(metric) is not None and b.get(metric) is not None
        ]
        if pairs:
            low, high = paired_bootstrap([a for a, _ in pairs], [b for _, b in pairs])
            result[metric] = {
                "pairs": len(pairs),
                "delta": round(sum(b - a for a, b in pairs) / len(pairs), 3),
                "ci95": [round(low, 3), round(high, 3)],
            }
    return result


def report() -> None:
    settings = get_settings()
    passages = load(WORK / "passages.json")
    judgments = load(WORK / "judgments.json") if (WORK / "judgments.json").exists() else {}
    runs: dict[str, Any] = {}
    for answers_path in sorted(WORK.glob("answers-*.json")):
        run = answers_path.stem.removeprefix("answers-")
        answers = load(answers_path)
        per_set: dict[str, Any] = {}
        for name in SETS:
            rows = []
            for case in cases(name):
                key = f"{name}/{case['id']}"
                language = question_language(case["question"])
                chunks = [RetrievedChunk.model_validate(chunk) for chunk in passages[key]]
                foreign = foreign_sentences(answers[key], language)
                rows.append(
                    {
                        "id": case["id"],
                        "question_language": language,
                        "context_language": context_language(chunks),
                        "refused": refused(answers[key], settings.generation_no_context_answer),
                        "foreign": foreign,
                        **judgments.get(run, {}).get(key, {}),
                    }
                )
            summary: dict[str, Any] = {
                "questions": len(rows),
                "cross_language_context": sum(
                    row["context_language"] not in (None, row["question_language"]) for row in rows
                ),
                "answers_with_foreign_text": sum(bool(row["foreign"]) for row in rows),
                "refusals": sum(row["refused"] for row in rows),
            }
            for metric in METRICS:
                values = [row[metric] for row in rows if row.get(metric) is not None]
                summary[metric] = _mean(values)
                summary[f"{metric}_judged"] = len(values)
            per_set[name] = {"summary": summary, "details": rows}
        runs[run] = per_set
    payload = {
        "label": "answer-lang-en-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "command": "python scripts/answer_language_eval.py report",
        "sets": {name: {"path": SETS[name][0], "corpus": SETS[name][1], "count": SETS[name][2]} for name in SETS},
        "judge": f"llamacpp:{settings.judge_model}",
        "runs": runs,
        "paired": {
            provider: paired(runs, f"verbatim-{provider}", f"omit-{provider}")
            for provider in ("ollama", "llamacpp")
            if f"verbatim-{provider}" in runs and f"omit-{provider}" in runs
        },
    }
    save(RESULTS, payload)
    sys.stdout.reconfigure(encoding="utf-8")
    header = "| run | set | foreign text | refusals | faithfulness | correctness |"
    print(header + "\n|---|---|---|---|---|---|")
    for run, per_set in runs.items():
        for name, block in per_set.items():
            s = block["summary"]
            print(
                f"| {run} | {name} | {s['answers_with_foreign_text']}/{s['questions']} | {s['refusals']} | "
                f"{s['faithfulness']} | {s['answer_correctness']} |"
            )
    for provider, block in payload["paired"].items():
        for metric in METRICS:
            if metric in block:
                stats = block[metric]
                print(
                    f"{provider} {metric}: omit - verbatim = {stats['delta']} (95% {stats['ci95']}, n={stats['pairs']})"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("retrieve")
    gen = sub.add_parser("generate")
    gen.add_argument("--variant", choices=VARIANTS, required=True)
    gen.add_argument("--provider", choices=("ollama", "llamacpp"), required=True)
    grade = sub.add_parser("judge")
    grade.add_argument(
        "--runs",
        nargs="+",
        default=["omit-llamacpp", "verbatim-llamacpp", "omit-ollama", "verbatim-ollama"],
        help="variant-provider pairs to judge (default: the two compared modes, both writers)",
    )
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "retrieve":
        retrieve()
    elif args.command == "generate":
        generate(args.variant, args.provider)
    elif args.command == "judge":
        judge(args.runs)
    else:
        report()


if __name__ == "__main__":
    main()
