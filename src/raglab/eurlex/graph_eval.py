"""Precision of the EU acts graph, checked by hand on a seeded sample.

The graph payload is built straight from the corpus files (one chunk per
document stands in for the index run's chunks: the EU profile reads
relations from the metadata, chunks only carry PART_OF), so the sample can
be redrawn without PostgreSQL or Neo4j and gives the same edges as a build
from an index run of the same corpus.

`draw_sample` writes the edges with their evidence (the sentence that
carries the reference, the target's opening text) and an empty verdict; a
reviewer fills `verdict` ("correct" / "incorrect") and `note`;
`precision_report` computes the precision per relation. The reviewed file
is versioned in `benchmarks/eurlex_compliance/`.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from raglab.graph.structure import ChunkRow, DocumentRow, GraphPayload, build_payload

# Edges drawn per group (about 40 in all), and the relationship keys of each.
SAMPLE_PLAN: dict[str, tuple[int, list[tuple[str, str, str]]]] = {
    "CITES_within_act": (10, []),
    "CITES_across_acts": (10, []),
    "EXPLAINS": (6, [("EXPLAINS", "Recital", "Article")]),
    "SUPPLEMENTS": (6, [("SUPPLEMENTS", "Act", "Article")]),
    "AMENDS": (4, [("AMENDS", "Act", "Article"), ("AMENDS", "Act", "Annex")]),
    "SAME_AS": (4, []),
}
EVIDENCE_CHARS = 400


def load_documents(corpus_dir: Path) -> list[DocumentRow]:
    documents: list[DocumentRow] = []
    for sidecar in sorted(corpus_dir.glob("*.json")):
        text_path = sidecar.with_suffix(".txt")
        documents.append(
            DocumentRow(
                id=text_path.stem,
                file_name=text_path.name,
                content=text_path.read_text(encoding="utf-8"),
                metadata=json.loads(sidecar.read_text(encoding="utf-8")),
            )
        )
    return documents


def corpus_payload(corpus_dir: Path, *, index_run_id: str = "files") -> tuple[GraphPayload, list[DocumentRow]]:
    """Graph payload of the corpus files, one chunk per document."""
    documents = load_documents(corpus_dir)
    chunks = [
        ChunkRow(id=f"{document.id}#0", document_id=document.id, order=0, char_start=0, char_end=len(document.content))
        for document in documents
    ]
    payload = build_payload(
        index_run_id=index_run_id, corpus=corpus_dir.parent.name, documents=documents, chunks=chunks, profile="eu_acts"
    )
    return payload, documents


def _population(payload: GraphPayload, group: str) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    if group.startswith("CITES_"):
        scope = group.removeprefix("CITES_")
        for (kind, _, target), edges in payload.relationships.items():
            if kind == "CITES" and target != "Act":
                rows.extend((kind, edge) for edge in edges if edge["props"].get("scope") == scope)
    elif group == "SAME_AS":
        for (kind, _, _), edges in payload.relationships.items():
            if kind == "SAME_AS":
                rows.extend((kind, edge) for edge in edges)
    else:
        for key in SAMPLE_PLAN[group][1]:
            rows.extend((key[0], edge) for edge in payload.relationships.get(key, []))
    rows.sort(key=lambda item: (item[0], item[1]["source"], item[1]["target"]))
    return rows


def _names(payload: GraphPayload) -> dict[str, dict[str, Any]]:
    names: dict[str, dict[str, Any]] = {}
    for label, rows in payload.nodes.items():
        if label in {"Act", "Article", "Recital", "Annex"}:
            for row in rows:
                names[row["uid"]] = row
    return names


def _describe(node: dict[str, Any] | None, uid: str) -> str:
    if node is None:
        return uid
    if "unit_key" in node:
        return f"{node['act_key']} — {node.get('label')} ({node.get('language')}, v{node.get('version')})"
    return f"{node['key']} ({node['celex']})" + (" [hors corpus]" if node.get("external") else "")


def draw_sample(payload: GraphPayload, documents: list[DocumentRow], *, seed: int = 42) -> dict[str, Any]:
    texts = {document.id: document.content for document in documents}
    metadata = {document.id: document.metadata for document in documents}
    names = _names(payload)
    items: list[dict[str, Any]] = []
    population_sizes: dict[str, int] = {}
    for group, (count, _) in SAMPLE_PLAN.items():
        population = _population(payload, group)
        population_sizes[group] = len(population)
        picked = random.Random(f"{seed}:{group}").sample(population, min(count, len(population)))
        for index, (relation, edge) in enumerate(picked, start=1):
            props = edge["props"]
            source, target = names.get(edge["source"]), names.get(edge["target"])
            evidence_document = str(props.get("evidence_document") or (source or {}).get("document_id"))
            if relation == "SUPPLEMENTS":
                basis: dict[str, Any] = next(
                    (
                        row
                        for row in metadata[evidence_document].get("legal_basis") or []
                        if props.get("article") in (row.get("articles") or [])
                    ),
                    {},
                )
                evidence = basis.get("citation", "")
            elif relation == "SAME_AS":
                evidence = (target or {}).get("preview", "")
            elif relation == "AMENDS":
                evidence = " ".join(texts.get(evidence_document, "").split())[:EVIDENCE_CHARS]
            else:
                evidence = props.get("snippet") or ""
            items.append(
                {
                    "id": f"{group.lower()}-{index:02d}",
                    "group": group,
                    "relation": relation,
                    "source": _describe(source, edge["source"]),
                    "target": _describe(target, edge["target"]),
                    "detail": {
                        key: props[key]
                        for key in ("ref_scope", "details", "article", "kind", "mentions")
                        if props.get(key)
                    },
                    "evidence": evidence,
                    "source_preview": (source or {}).get("preview", "") if relation == "SAME_AS" else "",
                    "target_preview": (target or {}).get("preview", "") if relation != "SAME_AS" else "",
                    "verdict": None,
                    "note": "",
                }
            )
    return {"corpus": payload.corpus, "seed": seed, "population": population_sizes, "items": items}


def precision_report(sample: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    reviewed_all = correct_all = 0
    for group in SAMPLE_PLAN:
        items = [item for item in sample["items"] if item["group"] == group]
        reviewed = [item for item in items if item.get("verdict") in {"correct", "incorrect"}]
        correct = sum(item["verdict"] == "correct" for item in reviewed)
        reviewed_all += len(reviewed)
        correct_all += correct
        groups[group] = {
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
    return {
        "corpus": sample.get("corpus"),
        "seed": sample.get("seed"),
        "reviewed": reviewed_all,
        "correct": correct_all,
        "precision": round(correct_all / reviewed_all, 3) if reviewed_all else None,
        "groups": groups,
    }
