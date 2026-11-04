"""Tables of the "Brazil expat" measurement, from `raglab bench` detailed reports.

`raglab bench all --suite br_expat` scores Recall@1/5/10 and MRR over every
question, Q30 included (it has no passage to find, so it always counts as a
miss). This script reads the detailed reports (`data/reports/*.json`, path in
`benchmarks/results/<label>.json`) and prints, per theme:

- Recall@3, Recall@5 and MRR at article level (`expected_spans`), Q30 left out;
- Recall@5 at provision level (`context.provision_spans`, the lines that carry
  the answer);
- for a judged run: answer correctness and faithfulness, the trap verdicts
  (Q29 must cite art. 20 §2º and say the list of countries is missing, Q30
  must say it does not find it), and the failure analysis: a wrong answer with
  the article in the writer's context vs. the article missing.

Usage: python scripts/br_expat_report.py brexpat-naive-v1 brexpat-full-v1 [--answers brexpat-answers-v1]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

THEMES = ("immigration", "company_tax", "inss_personal_tax", "trap", "paraphrase")
THEME_LABELS = {
    "immigration": "Immigration",
    "company_tax": "Société et impôts",
    "inss_personal_tax": "INSS et fiscalité perso.",
    "trap": "Pièges (Q29)",
    "paraphrase": "Paraphrases",
}
OUT_OF_SCOPE = "brx-30"
GENERATION_TOP_K = 5
WRONG = 0.5  # answer_correctness below this is a wrong answer

_REFUSAL = re.compile(
    r"je ne trouve pas|ne (?:se )?trouve pas|n'(?:est|apparaît|figure) pas dans les documents|"
    r"pas (?:dans|mentionn\w+ dans) les (?:documents|passages|extraits)|ne permettent? pas|"
    r"aucun(?:e)? (?:information|passage|mention)|ne contien\w+ pas|ne précisent? pas|ne fourni\w+ pas",
    re.IGNORECASE,
)
_RECIPROCITY = re.compile(r"r[ée]ciprocit", re.IGNORECASE)
_ART20 = re.compile(r"art(?:\.|igo|icle)?\s*20", re.IGNORECASE)


def _overlaps(chunk: dict[str, Any], span: dict[str, Any]) -> bool:
    return (
        chunk["file_name"] == span["file_name"]
        and chunk.get("char_start") is not None
        and chunk["char_start"] < span["end"]
        and span["start"] < chunk["char_end"]
    )


def _first_rank(chunks: list[dict[str, Any]], spans: list[dict[str, Any]]) -> int | None:
    for rank, chunk in enumerate(chunks, start=1):
        if any(_overlaps(chunk, span) for span in spans):
            return rank
    return None


def load_run(label: str, results_dir: Path) -> dict[str, Any]:
    result = json.loads((results_dir / f"{label}.json").read_text(encoding="utf-8"))
    suite = next(s for s in result["suites"] if s["suite"] == "br_expat")
    report = json.loads(Path(suite["report_path"]).read_text(encoding="utf-8"))
    return {"label": label, "result": result, "suite": suite, "details": {d["id"]: d for d in report["details"]}}


def case_outcomes(run: dict[str, Any], truth: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    outcomes = {}
    for case_id, case in truth.items():
        detail = run["details"][case_id]
        chunks = detail["retrieved_chunks"]
        rank = _first_rank(chunks, case["expected_spans"])
        provision_rank = _first_rank(chunks, case["context"]["provision_spans"])
        metrics = detail.get("metrics", {})
        outcomes[case_id] = {
            "theme": case["question_type"],
            "rank": rank,
            "provision_rank": provision_rank,
            "top": [f"{c['file_name'].removesuffix('.txt')}@{c.get('char_start')}" for c in chunks[:5]],
            "answer": detail.get("answer"),
            "correctness": metrics.get("answer_correctness"),
            "faithfulness": metrics.get("faithfulness"),
            "correctness_reason": metrics.get("answer_correctness_reason"),
        }
    return outcomes


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}".replace(".", ",")


def retrieval_table(runs: list[dict[str, Any]], outcomes: list[dict[str, dict[str, Any]]]) -> str:
    lines = [
        "| Thème | n | " + " | ".join(f"R@3 {r['label']} | R@5 {r['label']} | MRR {r['label']}" for r in runs) + " |",
        "|---|---|" + "---|---|---|" * len(runs),
    ]
    groups = [(THEME_LABELS[t], t) for t in THEMES] + [("**Total (37, sans Q30)**", None)]
    for name, theme in groups:
        cells = []
        count = 0
        for rows in outcomes:
            selected = [o for cid, o in rows.items() if cid != OUT_OF_SCOPE and (theme is None or o["theme"] == theme)]
            count = len(selected)
            for k in (3, 5):
                cells.append(_fmt(_mean([float(o["rank"] is not None and o["rank"] <= k) for o in selected])))
            cells.append(_fmt(_mean([1 / o["rank"] if o["rank"] else 0.0 for o in selected])))
        lines.append(f"| {name} | {count} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def provision_table(runs: list[dict[str, Any]], outcomes: list[dict[str, dict[str, Any]]]) -> str:
    lines = [
        "| Thème | " + " | ".join(f"R@5 article {r['label']} | R@5 disposition {r['label']}" for r in runs) + " |",
        "|---|" + "---|---|" * len(runs),
    ]
    for name, theme in [(THEME_LABELS[t], t) for t in THEMES] + [("**Total**", None)]:
        cells = []
        for rows in outcomes:
            selected = [o for cid, o in rows.items() if cid != OUT_OF_SCOPE and (theme is None or o["theme"] == theme)]
            cells.append(_fmt(_mean([float(o["rank"] is not None and o["rank"] <= 5) for o in selected])))
            cells.append(
                _fmt(_mean([float(o["provision_rank"] is not None and o["provision_rank"] <= 5) for o in selected]))
            )
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def per_question_table(runs: list[dict[str, Any]], outcomes: list[dict[str, dict[str, Any]]], truth) -> str:
    lines = [
        "| id | Références | " + " | ".join(f"rang {r['label']}" for r in runs) + " |",
        "|---|---|" + "---|" * len(runs),
    ]
    for case_id, case in truth.items():
        ranks = [str(rows[case_id]["rank"] or "—") for rows in outcomes]
        lines.append(f"| {case_id} | {', '.join(case['context']['references']) or 'aucune'} | " + " | ".join(ranks) + " |")
    return "\n".join(lines)


def trap_verdicts(rows: dict[str, dict[str, Any]]) -> dict[str, str]:
    q29 = rows.get("brx-29", {}).get("answer") or ""
    q30 = rows.get(OUT_OF_SCOPE, {}).get("answer") or ""
    return {
        "brx-29": (
            f"cite l'art. 20 : {'oui' if _ART20.search(q29) else 'non'} ; réciprocité : "
            f"{'oui' if _RECIPROCITY.search(q29) else 'non'} ; dit que la liste manque : "
            f"{'oui' if _REFUSAL.search(q29) else 'non'}"
        ),
        OUT_OF_SCOPE: f"refuse : {'oui' if _REFUSAL.search(q30) else 'non'}",
    }


def answers_table(rows: dict[str, dict[str, Any]]) -> str:
    lines = ["| Thème | n jugées | Exactitude | Fidélité |", "|---|---|---|---|"]
    for name, theme in [(THEME_LABELS[t], t) for t in THEMES] + [("**Total**", None)]:
        selected = [o for o in rows.values() if (theme is None or o["theme"] == theme) and o["correctness"] is not None]
        lines.append(
            f"| {name} | {len(selected)} | {_fmt(_mean([o['correctness'] for o in selected]))} | "
            f"{_fmt(_mean([o['faithfulness'] for o in selected if o['faithfulness'] is not None]))} |"
        )
    return "\n".join(lines)


def failure_table(rows: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| id | Exactitude | Article dans le contexte (top 5) | Disposition dans le contexte | Cause |",
        "|---|---|---|---|---|",
    ]
    for case_id, o in rows.items():
        if case_id == OUT_OF_SCOPE or o["correctness"] is None or o["correctness"] >= WRONG:
            continue
        in_context = o["rank"] is not None and o["rank"] <= GENERATION_TOP_K
        provision = o["provision_rank"] is not None and o["provision_rank"] <= GENERATION_TOP_K
        cause = "bon passage, mauvaise réponse" if in_context else "passage manquant"
        lines.append(
            f"| {case_id} | {_fmt(o['correctness'])} | {'oui' if in_context else 'non'} | "
            f"{'oui' if provision else 'non'} | {cause} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("labels", nargs="+", help="Runs to compare on retrieval (benchmarks/results/<label>.json).")
    parser.add_argument("--answers", help="Judged run (answers, traps, failure analysis).")
    parser.add_argument("--truth", type=Path, default=Path("benchmarks/br_expat/ground_truth.jsonl"))
    parser.add_argument("--results-dir", type=Path, default=Path("benchmarks/results"))
    parser.add_argument("--dump", type=Path, help="Write per-question outcomes as JSON here.")
    args = parser.parse_args()

    truth = {
        row["id"]: row
        for row in (json.loads(line) for line in args.truth.read_text(encoding="utf-8").splitlines() if line.strip())
    }
    runs = [load_run(label, args.results_dir) for label in args.labels]
    outcomes = [case_outcomes(run, truth) for run in runs]
    print("## Recherche, niveau article\n")
    print(retrieval_table(runs, outcomes))
    print("\n## Article contre disposition (Recall@5)\n")
    print(provision_table(runs, outcomes))
    print("\n## Rang du premier passage pertinent, par question\n")
    print(per_question_table(runs, outcomes, truth))
    dump: dict[str, Any] = {run["label"]: rows for run, rows in zip(runs, outcomes, strict=True)}
    if args.answers:
        judged = case_outcomes(load_run(args.answers, args.results_dir), truth)
        dump[args.answers] = judged
        print(f"\n## Réponses ({args.answers})\n")
        print(answers_table(judged))
        print("\n## Pièges\n")
        for case_id, verdict in trap_verdicts(judged).items():
            print(f"- {case_id} : {verdict}")
        print("\n## Échecs (exactitude < 0,5)\n")
        print(failure_table(judged))
    if args.dump:
        args.dump.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
