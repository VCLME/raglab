"""Score the citation reference set (benchmarks/citation_refs/cases.jsonl).

For each case: the parsed reference, what the queried index holds of it,
and the router rule that follows (exempt: never declined; decline: declined
with an explicit answer; normal: intent and score decide). Deterministic: no
embedding, no GPU, only the parser and the database.

Runs against whichever `raglab` is on PYTHONPATH, so the same script scores
the code before the change (act-level check, `cited_text_in_run`) and after
it (`resolve_cited_text`). Two reports are compared with --compare.

    python scripts/citation_refs_eval.py --out before.json   # PYTHONPATH=<old>/src
    python scripts/citation_refs_eval.py --out after.json    # PYTHONPATH=src
    python scripts/citation_refs_eval.py --compare before.json after.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

CASES = Path(__file__).resolve().parent.parent / "benchmarks" / "citation_refs" / "cases.jsonl"


def run(out: Path) -> None:
    from raglab.db.session import get_session_factory
    from raglab.retrieval.citations import parse_citation
    from raglab.retrieval.service import QueryService
    from raglab.routing import citation as routing_citation

    resolve = getattr(routing_citation, "resolve_cited_text", None)
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    with get_session_factory()() as session:
        service = QueryService(session)
        runs: dict[str, object] = {}
        for case in cases:
            corpus = case["corpus"]
            if corpus not in runs:
                runs[corpus] = service._resolve_index_run(corpus_name=corpus, strategy=None, index_run_id=None)
            index_run = runs[corpus]
            citation = parse_citation(case["question"])
            status = version = None
            if citation is None:
                rule = "normal"
            elif resolve is not None:
                resolution = resolve(session, index_run, citation)
                status, version = resolution.status, resolution.version
                rule = "exempt" if resolution.exempt else "decline" if status == "unit_not_found" else "normal"
            else:
                # Before the change: the act alone exempts (a French code article
                # had to be found); nothing is declined for a missing unit.
                rule = "exempt" if routing_citation.cited_text_in_run(session, index_run, citation) else "normal"
            parsed_unit = citation.article if citation is not None else None
            rows.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "question": case["question"],
                    "recognised": citation is not None,
                    "label": citation.label() if citation is not None else None,
                    "parsed_unit": parsed_unit,
                    "unit_correct": parsed_unit == case["expected_unit"],
                    "status": status,
                    "status_correct": status == case["expected_status"] if resolve is not None else None,
                    "version": version,
                    "router_rule": rule,
                    "expected_router_rule": case["expected_router_rule"],
                    "rule_correct": rule == case["expected_router_rule"],
                    # Without the router nothing is declined; the response
                    # carries the status (and the UI shows it).
                }
            )
    by_category: dict[str, Counter] = {}
    for row in rows:
        counts = by_category.setdefault(row["category"], Counter())
        counts["cases"] += 1
        counts["rule_correct"] += row["rule_correct"]
        counts["unit_correct"] += row["unit_correct"]
    report = {
        "kind": "citation_refs",
        "created_at": datetime.now(UTC).isoformat(),
        "code": "resolve_cited_text" if resolve is not None else "cited_text_in_run",
        "cases_file": str(CASES.relative_to(CASES.parent.parent.parent)).replace("\\", "/"),
        "summary": {
            "cases": len(rows),
            "rule_correct": sum(row["rule_correct"] for row in rows),
            "unit_correct": sum(row["unit_correct"] for row in rows),
            "status_correct": (sum(bool(row["status_correct"]) for row in rows) if resolve is not None else None),
            "by_category": {key: dict(value) for key, value in sorted(by_category.items())},
        },
        "rows": rows,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = report["summary"]
    print(f"{report['code']}: rule {summary['rule_correct']}/{summary['cases']}, unit {summary['unit_correct']}")
    for row in rows:
        if not row["rule_correct"] or not row["unit_correct"]:
            print(
                f"  {row['id']}: rule {row['router_rule']} (expected {row['expected_router_rule']}),"
                f" unit {row['parsed_unit']!r}, status {row['status']}"
            )


def compare(before_path: Path, after_path: Path) -> None:
    from raglab.benchmarks.compare import mcnemar_exact

    before = {row["id"]: row for row in json.loads(before_path.read_text(encoding="utf-8"))["rows"]}
    after = {row["id"]: row for row in json.loads(after_path.read_text(encoding="utf-8"))["rows"]}
    if set(before) != set(after):
        sys.exit("the two reports do not cover the same cases")
    for key in ("rule_correct", "unit_correct"):
        won = sorted(i for i in before if after[i][key] and not before[i][key])
        lost = sorted(i for i in before if before[i][key] and not after[i][key])
        print(
            f"{key}: {sum(r[key] for r in before.values())} -> {sum(r[key] for r in after.values())}"
            f" of {len(before)}, won {len(won)} lost {len(lost)}, p = {mcnemar_exact(len(won), len(lost)):.4f}"
        )
        if won:
            print("  won:", ", ".join(won))
        if lost:
            print("  lost:", ", ".join(lost))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
    elif args.out:
        run(args.out)
    else:
        parser.error("--out or --compare")


if __name__ == "__main__":
    main()
