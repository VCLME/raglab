"""Build the frozen cross-language set `benchmarks/lexml_fr/`.

French questions answered from the Brazilian LexML corpus: a seeded sample of
the natural questions of `benchmarks/lexml_fulltext/` (types `paraphrase` and
`entity`, not rejected, citing no article, paragraph or law number),
translated into French. The relevance judgments (`expected_file_names`,
`expected_spans`) are those of the source question, unchanged.

    python scripts/build_lexml_fr.py --select            # print the sample (id, type, question)
    python scripts/build_lexml_fr.py --translations t.tsv  # write the two frozen files
    python scripts/build_lexml_fr.py --select-calibration  # print the other candidates
    python scripts/build_lexml_fr.py --calibration c.tsv   # write the two calibration files

`t.tsv` holds one `id<TAB>French question` per line. Two files are written,
with the same ids in the same order:

- `ground_truth.jsonl`: the French question (`question`), the Portuguese one
  kept in `source_question`;
- `ground_truth_pt.jsonl`: the Portuguese question, for the paired pt / fr
  comparison on exactly the same cases.

The candidates left out of the sample (75) form a calibration split,
disjoint from the frozen questions by construction: `calibration.jsonl` /
`calibration_pt.jsonl`, same format. They calibrate the router's
per-language abstention thresholds and corpus examples (docs/routage-multilingue.md),
never evaluated.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

SOURCE = Path("benchmarks/lexml_fulltext/ground_truth.jsonl")
OUTPUT = Path("benchmarks/lexml_fr")
SEED = 42
COUNT = 100

# "art. 2", "artigo 5", "Lei nº 7.689", "§ 2º", "nº 123", "Decreto", "Medida Provisória nº".
CITATION = re.compile(
    r"\bart(?:igo)?s?\.?\s*\d|\blei\s*(?:n[º°o.]*\s*)?\d|§|\bn[º°]\s*\d|\bdecreto\b|medida provis[óo]ria",
    re.IGNORECASE,
)


def candidates() -> list[dict]:
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen: set[str] = set()
    kept = []
    for row in sorted(rows, key=lambda r: r["id"]):
        if row.get("review_status") == "rejected" or row["question_type"] not in ("paraphrase", "entity"):
            continue
        if CITATION.search(row["question"]):
            continue
        # The writer produced a few identical questions on different passages:
        # keep the first, the others have no unique answer.
        if row["question"] in seen:
            continue
        seen.add(row["question"])
        kept.append(row)
    return kept


def sample() -> list[dict]:
    pool = candidates()
    picked = random.Random(SEED).sample(pool, COUNT)
    return sorted(picked, key=lambda r: r["id"])


def calibration_rows() -> list[dict]:
    picked = {row["id"] for row in sample()}
    return [row for row in candidates() if row["id"] not in picked]


def build(translations_path: Path, *, calibration: bool = False) -> None:
    translations = {}
    for line in translations_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case_id, question = line.split("\t", 1)
            translations[case_id] = question.strip()
    picked = calibration_rows() if calibration else sample()
    prefix = "calibration" if calibration else "ground_truth"
    missing = [row["id"] for row in picked if row["id"] not in translations]
    if missing:
        sys.exit(f"Missing translations: {missing}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fields = ("expected_file_names", "ground_truth_answer", "expected_substrings", "expected_urns", "expected_spans")
    with (
        (OUTPUT / f"{prefix}.jsonl").open("w", encoding="utf-8", newline="\n") as fr,
        (OUTPUT / f"{prefix}_pt.jsonl").open("w", encoding="utf-8", newline="\n") as pt,
    ):
        for row in picked:
            base = {field: row[field] for field in fields if field in row}
            common = {"question_type": row["question_type"], "lexical_overlap": row.get("lexical_overlap")}
            fr.write(
                json.dumps(
                    {
                        "id": row["id"],
                        "question": translations[row["id"]],
                        "question_language": "fr",
                        "source_question": row["question"],
                        **base,
                        **common,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            pt.write(
                json.dumps(
                    {"id": row["id"], "question": row["question"], "question_language": "pt", **base, **common},
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"{len(picked)} cases written to {OUTPUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--select", action="store_true")
    group.add_argument("--translations", type=Path)
    group.add_argument("--select-calibration", action="store_true")
    group.add_argument("--calibration", type=Path)
    args = parser.parse_args()
    if args.select or args.select_calibration:
        sys.stdout.reconfigure(encoding="utf-8")
        pool = candidates()
        print(f"# pool: {len(pool)} candidates", file=sys.stderr)
        for row in calibration_rows() if args.select_calibration else sample():
            print(f"{row['id']}\t{row['question_type']}\t{row['question']}")
    elif args.calibration:
        build(args.calibration, calibration=True)
    else:
        build(args.translations)


if __name__ == "__main__":
    main()
