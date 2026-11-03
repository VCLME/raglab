"""Measure the structured graph: extraction precision and article coverage.

Precision is checked by hand on a seeded random sample of edges, drawn from
the payload built out of PostgreSQL (no Neo4j needed, so anyone can redraw
the same sample): `raglab graph sample` writes the edges with their evidence
and an empty verdict, a reviewer fills `verdict` ("correct" / "incorrect")
and `note`, and `raglab graph report` computes the precision. The reviewed
file is versioned in `benchmarks/graph/`.

Coverage: for each LexML question citing an article ("art. 2 da Lei nº
7.689"), does the graph have that article, and does the article's span hold
the expected answer span?
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from raglab.graph.legal import article_label
from raglab.graph.structure import DocumentRow, GraphPayload, law_label
from raglab.retrieval.citations import parse_citation

SAMPLED = {
    "CITES": [("CITES", "Article", "Article")],
    "AMENDS_REVOKES": [
        ("AMENDS", "Law", "Article"),
        ("AMENDS", "Document", "Article"),
        ("AMENDS", "Document", "Law"),
        ("AMENDS", "Document", "Document"),
        ("REVOKES", "Law", "Article"),
        ("REVOKES", "Document", "Article"),
        ("REVOKES", "Document", "Law"),
        ("REVOKES", "Document", "Document"),
    ],
}
EVIDENCE_CHARS = 320


def draw_sample(
    payload: GraphPayload,
    documents: list[DocumentRow],
    *,
    seed: int = 42,
    cites: int = 60,
    amendments: int = 30,
) -> dict[str, Any]:
    """Seeded random sample of CITES and AMENDS / REVOKES edges to review."""
    texts = {document.id: document.content for document in documents}
    names = _node_names(payload)
    items: list[dict[str, Any]] = []
    for group, count in (("CITES", cites), ("AMENDS_REVOKES", amendments)):
        population: list[tuple[str, dict[str, Any]]] = []
        for key in SAMPLED[group]:
            population.extend((key[0], row) for row in payload.relationships.get(key, []))
        population.sort(
            key=lambda item: (item[0], item[1]["source"], item[1]["target"], item[1]["props"].get("kind") or "")
        )
        picked = random.Random(f"{seed}:{group}").sample(population, min(count, len(population)))
        for relation, row in picked:
            props = row["props"]
            document_id = _evidence_document(row, relation)
            text = texts.get(document_id, "")
            offset = int(props.get("offset") or 0)
            items.append(
                {
                    "id": f"{group.lower()}-{len([i for i in items if i['group'] == group]) + 1:03d}",
                    "group": group,
                    "relation": relation,
                    "kind": props.get("kind") or props.get("scope"),
                    "source": names.get(row["source"], row["source"]),
                    "target": names.get(row["target"], row["target"]),
                    "target_articles": props.get("articles") or [],
                    "scopes": props.get("scopes") or [],
                    "evidence": " ".join(text[max(0, offset - EVIDENCE_CHARS) : offset + EVIDENCE_CHARS].split()),
                    "verdict": None,
                    "note": "",
                }
            )
    return {
        "corpus": payload.corpus,
        "index_run_id": payload.index_run_id,
        "seed": seed,
        "population": {
            group: sum(len(payload.relationships.get(key, [])) for key in keys) for group, keys in SAMPLED.items()
        },
        "items": items,
    }


def _evidence_document(row: dict[str, Any], relation: str) -> str:
    """Document whose text holds the evidence of the edge."""
    if relation == "CITES":
        return row["source"].split(":")[1]
    return row["props"].get("evidence_document") or row["target"].split(":")[1]


def _node_names(payload: GraphPayload) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in payload.nodes.get("Document", []):
        names[row["uid"]] = law_label(row.get("key"), row.get("year")) or row["title"]
    for row in payload.nodes.get("Law", []):
        names[row["uid"]] = law_label(row.get("key"), row.get("year")) + " (hors corpus)"
    laws = {row["document_id"]: names[row["uid"]] for row in payload.nodes.get("Document", [])}
    for row in payload.nodes.get("Article", []):
        names[row["uid"]] = f"{article_label(row['number'])} — {laws.get(row['document_id'], '')}"
    return names


def precision_report(sample: dict[str, Any]) -> dict[str, Any]:
    """Precision per group from a reviewed sample (verdicts filled in)."""
    report: dict[str, Any] = {"corpus": sample.get("corpus"), "seed": sample.get("seed"), "groups": {}}
    for group in SAMPLED:
        items = [item for item in sample["items"] if item["group"] == group]
        reviewed = [item for item in items if item.get("verdict") in {"correct", "incorrect"}]
        correct = sum(item["verdict"] == "correct" for item in reviewed)
        report["groups"][group] = {
            "sampled": len(items),
            "reviewed": len(reviewed),
            "correct": correct,
            "precision": round(correct / len(reviewed), 3) if reviewed else None,
            "population": (sample.get("population") or {}).get(group),
            "errors": [
                {"id": item["id"], "source": item["source"], "target": item["target"], "note": item.get("note", "")}
                for item in reviewed
                if item["verdict"] == "incorrect"
            ],
        }
    return report


def article_coverage(
    payload: GraphPayload, cases: list[dict[str, Any]], documents: list[DocumentRow]
) -> dict[str, Any]:
    """LexML questions citing an article: does the graph have the article,
    and does its span hold the expected answer?"""
    file_to_document = {document.file_name: document.id for document in documents}
    laws: dict[str, str] = {}
    for row in payload.nodes.get("Document", []):
        if row.get("key"):
            laws.setdefault(row["key"], row["document_id"])
    articles = {(row["document_id"], row["number"]): row for row in payload.nodes.get("Article", [])}
    counts = {"questions": 0, "cite_article": 0, "law_in_corpus": 0, "article_node": 0, "span_in_article": 0}
    misses: list[dict[str, Any]] = []
    for case in cases:
        counts["questions"] += 1
        citation = parse_citation(case["question"])
        if citation is None or citation.article is None:
            continue
        counts["cite_article"] += 1
        # A French code article has no law number: not a law of this graph.
        document_id = laws.get(citation.law_number) if citation.law_number else None
        if document_id is None:
            misses.append({"id": case["id"], "reason": "law_not_in_corpus", "question": case["question"]})
            continue
        counts["law_in_corpus"] += 1
        article = articles.get((document_id, citation.article))
        if article is None:
            misses.append({"id": case["id"], "reason": "no_article_node", "question": case["question"]})
            continue
        counts["article_node"] += 1
        spans = [
            span
            for span in case.get("expected_spans") or []
            if file_to_document.get(span.get("file_name")) == document_id
        ]
        if any(article["char_start"] <= span["start"] and span["end"] <= article["char_end"] for span in spans):
            counts["span_in_article"] += 1
        else:
            misses.append({"id": case["id"], "reason": "answer_outside_article", "question": case["question"]})
    return {**counts, "misses": misses}


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
