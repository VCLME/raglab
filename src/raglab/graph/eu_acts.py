"""EU acts profile of the structured graph (`raglab eurlex fetch` corpora).

Each document of an EU corpus is already one unit (article, recital or
annex) of one act, in one language and one version, with its references
read by rules at collection time (`raglab.eurlex.references`, stored in
`metadata_json`). The profile turns that metadata into graph nodes and
relations, without parsing text again:

    (:Act {celex, key, type, role})                one per CELEX (language-neutral);
                                                   acts cited but not collected: external
    (:Article|:Recital|:Annex)-[:PART_OF]->(:Act)  one node per document
    (:Chunk)-[:PART_OF {first, overlap}]->(unit)   every chunk of the document
    (unit)-[:CITES]->(:Article|:Annex|:Recital)    within or across acts, same language
    (unit)-[:CITES]->(:Act)                        an act outside the corpus, or a unit not found
    (:Recital)-[:EXPLAINS]->(:Article)             the recital names an article of its own act
                                                   ("Article 26(10) of this Regulation")
    (:Act)-[:SUPPLEMENTS {articles}]->(:Article)   a delegated / implementing act and the base
                                                   articles of its legal basis ("Article 15 thereof")
    (:Act)-[:AMENDS {kind}]->(unit)                the consolidated version a later act produced
    (unit)-[:SAME_AS]->(unit)                      the same unit and version in another language

A reference resolves to the target in the same language, in the version
that applied when the citing version did (the version in force for a
version in force). Article nodes keep the laws profile's keys
(`document_id`, `number`, uid `<run>:<document>:art:<number>`), so the graph
retrieval branch follows EU citations with the same Cypher query.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from raglab.eurlex.acts import BY_CELEX, celex_label

UNIT_LABELS = {"article": "Article", "recital": "Recital", "annex": "Annex"}
_UID_PARTS = {"article": "art", "recital": "rct", "annex": "anx"}
PREVIEW_CHARS = 240
SNIPPET_CHARS = 220
MIN_OVERLAP = 20


def looks_like_eu_act(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("celex")) and metadata.get("unit") in UNIT_LABELS


def act_uid(index_run_id: str, celex: str) -> str:
    return f"{index_run_id}:act:{celex}"


def unit_uid(index_run_id: str, document_id: str, unit: str, number: str) -> str:
    return f"{index_run_id}:{document_id}:{_UID_PARTS[unit]}:{number}"


def act_key(celex: str) -> str:
    """Display name of an act: "GDPR", "AI Act", "Regulation (EU) No 1093/2010"."""
    act = BY_CELEX.get(celex)
    return act.short_name("en") if act is not None else celex_label(celex)


def _snippet(text: str, needle: str) -> tuple[str, int]:
    offset = text.find(needle) if needle else -1
    if offset < 0:
        return "", 0
    left = max(text.rfind("\n", 0, offset) + 1, offset - SNIPPET_CHARS // 2)
    right = text.find("\n", offset + len(needle))
    right = min(right if right != -1 else len(text), offset + len(needle) + SNIPPET_CHARS // 2)
    return " ".join(text[left:right].split()), offset


class _Units:
    """Documents by (unit key, language), to resolve references to versions."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.annexes: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in rows:
            self.by_key[(row["unit_key"], row["language"])].append(row)
            if row["unit"] == "annex":
                self.annexes[(row["celex"], row["language"])].add(row["unit_key"])
        for versions in self.by_key.values():
            versions.sort(key=lambda row: (row["valid_from"] or "", row["version"]))

    def target(self, source: dict[str, Any], celex: str, unit: str, number: str | None) -> dict[str, Any] | None:
        language = source["language"]
        if number is None:
            # "the Annex" of an act with a single annex.
            keys = self.annexes.get((celex, language), set())
            if len(keys) != 1:
                return None
            key = next(iter(keys))
        else:
            key = f"{celex}:{unit}:{number}"
        versions = self.by_key.get((key, language))
        if not versions:
            return None
        if source["in_force"]:
            current = [row for row in versions if row["in_force"]]
            return current[-1] if current else versions[-1]
        # A superseded version cites what applied at its own date.
        start = source["valid_from"] or ""
        applicable = [row for row in versions if (row["valid_from"] or "") <= start]
        return applicable[-1] if applicable else versions[0]


def add_eu_structure(
    nodes: dict[str, list[dict[str, Any]]],
    relationships: dict[tuple[str, str, str], list[dict[str, Any]]],
    stats: Counter[str],
    base: dict[str, Any],
    documents: list[Any],
    chunks_by_document: dict[str, list[Any]],
) -> None:
    """Add the EU acts profile for `documents` (DocumentRow) to the payload."""
    run = base["index_run_id"]
    rows: list[dict[str, Any]] = []
    for document in documents:
        metadata = document.metadata or {}
        if not looks_like_eu_act(metadata):
            continue
        rows.append(
            {
                **metadata,
                "document_id": document.id,
                "content": document.content,
                "uid": unit_uid(run, document.id, metadata["unit"], str(metadata.get("unit_number"))),
                "in_force": bool(metadata.get("in_force", True)),
                "version": int(metadata.get("version") or 1),
            }
        )
    units = _Units(rows)
    acts: dict[str, dict[str, Any]] = {}

    def act_node(celex: str) -> str:
        uid = act_uid(run, celex)
        if uid not in acts:
            spec = BY_CELEX.get(celex)
            acts[uid] = {
                **base,
                "uid": uid,
                "celex": celex,
                "key": act_key(celex),
                "label": celex_label(celex),
                "type": spec.kind if spec else None,
                "role": spec.role if spec else None,
                "external": celex not in collected,
                "year": int(celex[1:5]) if celex[1:5].isdigit() else None,
            }
        return uid

    collected = {row["celex"] for row in rows}
    for celex in sorted(collected):
        act_node(celex)

    for order, row in enumerate(sorted(rows, key=lambda row: (row["celex"], row["unit"], row["unit_key"])), start=1):
        label = UNIT_LABELS[row["unit"]]
        text = row["content"]
        nodes[label].append(
            {
                **base,
                "uid": row["uid"],
                "document_id": row["document_id"],
                "celex": row["celex"],
                "act_key": act_key(row["celex"]),
                "law_key": act_key(row["celex"]),
                "number": str(row.get("unit_number")),
                "label": row.get("unit_label"),
                "title": row.get("unit_title"),
                "unit_key": row["unit_key"],
                "language": row.get("language"),
                "version": row["version"],
                "version_kind": row.get("version_kind"),
                "in_force": row["in_force"],
                "valid_from": row.get("valid_from"),
                "valid_to": row.get("valid_to"),
                "order": order,
                "char_start": 0,
                "char_end": len(text),
                "preview": " ".join(text.split())[:PREVIEW_CHARS],
            }
        )
        relationships[("PART_OF", label, "Act")].append(
            {"source": row["uid"], "target": act_uid(run, row["celex"]), "props": {}}
        )
        stats[f"eu_{row['unit']}s"] += 1
        chunks = sorted(chunks_by_document.get(row["document_id"], []), key=lambda chunk: chunk.order)
        for position, chunk in enumerate(chunks):
            overlap = min(chunk.char_end, len(text)) - max(chunk.char_start, 0)
            if overlap >= min(MIN_OVERLAP, len(text)):
                relationships[("PART_OF", "Chunk", label)].append(
                    {"source": chunk.id, "target": row["uid"], "props": {"overlap": overlap, "first": position == 0}}
                )

    cites: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        source_label = UNIT_LABELS[row["unit"]]
        for reference in row.get("references") or []:
            celex = reference.get("celex")
            if celex is None:
                stats["eu_refs_treaty"] += 1
                continue
            number = reference.get("number")
            if (
                reference["unit"] == row["unit"]
                and celex == row["celex"]
                and str(number) == str(row.get("unit_number"))
            ):
                continue  # a unit citing itself
            target = units.target(row, celex, reference["unit"], number) if celex in collected else None
            snippet, offset = _snippet(row["content"], reference.get("text") or "")
            if target is None:
                kind, target_uid, target_label = "CITES", act_node(celex), "Act"
                scope = "outside_corpus" if celex not in collected else "unknown_unit"
            else:
                target_label = UNIT_LABELS[target["unit"]]
                target_uid = target["uid"]
                scope = "within_act" if celex == row["celex"] else "across_acts"
                within_recital = row["unit"] == "recital" and target["unit"] == "article" and scope == "within_act"
                if within_recital and reference.get("implicit"):
                    # A recital rarely cites its own articles: an article
                    # number with no act named is too often another act's
                    # (hand-checked samples, rules v1 to v4).
                    stats["eu_explains_implicit_skipped"] += 1
                    continue
                kind = "EXPLAINS" if within_recital else "CITES"
            stats[f"eu_{kind.lower()}_{scope}"] += 1
            key = (kind, row["uid"], target_uid, target_label)
            edge = cites.get(key)
            detail = {k: reference[k] for k in ("paragraph", "point") if reference.get(k)}
            if edge is None:
                cites[key] = {
                    "source_label": source_label,
                    "source": row["uid"],
                    "target": target_uid,
                    "props": {
                        "mentions": 1,
                        "scope": scope,
                        "ref_scope": reference.get("scope"),
                        "articles": [f"{reference['unit']} {number}"] if target_label == "Act" else [],
                        "details": [f"{detail.get('paragraph') or ''}/{detail.get('point') or ''}"] if detail else [],
                        "snippet": snippet,
                        "offset": offset,
                        "evidence_document": row["document_id"],
                    },
                }
            else:
                props = edge["props"]
                props["mentions"] += 1
                if target_label == "Act" and f"{reference['unit']} {number}" not in props["articles"]:
                    props["articles"].append(f"{reference['unit']} {number}")
    for (kind, _, _, target_label), edge in cites.items():
        relationships[(kind, edge.pop("source_label"), target_label)].append(edge)

    # Legal basis of delegated and implementing acts, per language.
    supplements: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for basis in row.get("legal_basis") or []:
            base_celex = basis.get("celex")
            if base_celex not in collected:
                continue
            for article in basis.get("articles") or []:
                target = units.target({**row, "in_force": True}, base_celex, "article", article)
                if target is None:
                    continue
                pair = (act_uid(run, row["celex"]), target["uid"])
                if pair not in supplements:
                    supplements[pair] = {
                        "source": pair[0],
                        "target": pair[1],
                        "props": {
                            "language": row["language"],
                            "article": article,
                            "evidence_document": row["document_id"],
                        },
                    }
    relationships[("SUPPLEMENTS", "Act", "Article")].extend(supplements.values())
    stats["eu_supplements"] = len(supplements)

    # Amendments read from the consolidated markers.
    for row in rows:
        for amendment in row.get("amended_by") or []:
            celex = amendment.get("celex") or ""
            if not (len(celex) == 10 and celex[0] == "3" and celex[1:5].isdigit()):
                continue  # corrigenda ("32016R0679R(02)") are not acts
            relationships[("AMENDS", "Act", UNIT_LABELS[row["unit"]])].append(
                {
                    "source": act_node(celex),
                    "target": row["uid"],
                    "props": {
                        "kind": ",".join(amendment.get("actions") or []) or "amended",
                        "evidence_document": row["document_id"],
                    },
                }
            )
            stats["eu_amends"] += 1

    # The same unit and version in another language.
    groups: dict[tuple[str, bool, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["unit_key"], row["in_force"], row.get("valid_from") or "")].append(row)
    for members in groups.values():
        members.sort(key=lambda row: row.get("language") or "")
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                if left.get("language") == right.get("language"):
                    continue
                label_left, label_right = UNIT_LABELS[left["unit"]], UNIT_LABELS[right["unit"]]
                relationships[("SAME_AS", label_left, label_right)].append(
                    {"source": left["uid"], "target": right["uid"], "props": {"unit_key": left["unit_key"]}}
                )
                stats["eu_same_as"] += 1

    nodes["Act"].extend(acts.values())
    stats["eu_acts_in_corpus"] = len(collected)
    stats["eu_acts_external"] = sum(1 for row in acts.values() if row["external"])
