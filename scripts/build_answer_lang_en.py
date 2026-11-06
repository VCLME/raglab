"""Build the frozen cross-language set `benchmarks/answer_lang_en/`.

English questions on the two non-English legal corpora, to check that the
answer is written in the question's language even when the passages are not
(docs/benchmarks/prompt.md, "Question et corpus de langues différentes").
A seeded sample of each source set (all question types, rejected cases left
out), translated into English; the relevance judgments and the reference
answer are those of the source question, unchanged.

    python scripts/build_answer_lang_en.py --select                 # print the sample (set, id, type, question)
    python scripts/build_answer_lang_en.py --translations t.tsv     # write the frozen files

`t.tsv` holds one `id<TAB>English question` per line. One file per corpus:
`lexml.jsonl` (bench_lexml_pt) and `legi_consommation.jsonl`
(bench_legi_consommation_fr), each line with the English `question`, the
source one in `source_question`.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

SOURCES = {
    "lexml": Path("benchmarks/lexml_fulltext/ground_truth.jsonl"),
    "legi_consommation": Path("benchmarks/legi_consommation/ground_truth.jsonl"),
}
OUTPUT = Path("benchmarks/answer_lang_en")
SEED = 42
COUNT = 40


def sample(name: str) -> list[dict]:
    rows = [json.loads(line) for line in SOURCES[name].read_text(encoding="utf-8").splitlines() if line.strip()]
    pool = sorted((row for row in rows if row.get("review_status") != "rejected"), key=lambda r: r["id"])
    picked = random.Random(SEED).sample(pool, COUNT)
    return sorted(picked, key=lambda r: r["id"])


def build(translations_path: Path) -> None:
    translations = {}
    for line in translations_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case_id, question = line.split("\t", 1)
            translations[case_id] = question.strip()
    fields = ("expected_file_names", "ground_truth_answer", "expected_substrings", "expected_urns", "expected_spans")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        picked = sample(name)
        missing = [row["id"] for row in picked if row["id"] not in translations]
        if missing:
            sys.exit(f"Missing translations: {missing}")
        with (OUTPUT / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for row in picked:
                case = {
                    "id": row["id"],
                    "question": translations[row["id"]],
                    "question_language": "en",
                    "source_question": row["question"],
                    **{field: row[field] for field in fields if field in row},
                    "question_type": row["question_type"],
                }
                out.write(json.dumps(case, ensure_ascii=False) + "\n")
        print(f"{len(picked)} cases written to {OUTPUT / f'{name}.jsonl'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--select", action="store_true")
    group.add_argument("--translations", type=Path)
    args = parser.parse_args()
    if args.select:
        sys.stdout.reconfigure(encoding="utf-8")
        for name in SOURCES:
            for row in sample(name):
                print(f"{name}\t{row['id']}\t{row['question_type']}\t{row['question']}")
    else:
        build(args.translations)


if __name__ == "__main__":
    main()
