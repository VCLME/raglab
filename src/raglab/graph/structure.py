"""Structured graph of an index run (phase 9.9a): what goes into Neo4j.

PostgreSQL stays the source of truth for documents, chunks, vectors and BM25;
the graph only holds structure and relations, rebuilt from the chunks of one
index run. Every node carries `index_run_id` (and `corpus`), so runs and
corpora live side by side in Neo4j Community's single database.

Common base, every corpus:

    (:Document)<-[:PART_OF]-(:Section)<-[:PART_OF]-(:Chunk)-[:NEXT]->(:Chunk)

Sections are read from markdown headings (generic profile) or legal headings
(laws profile); a chunk without a section is PART_OF its document.

Laws profile (Brazilian federal laws, LexML-like text), rules in
`raglab.graph.legal`:

    (:Document:Law {number, year, title})<-[:PART_OF]-(:Article {law_number, number, label})
    (:Chunk)-[:PART_OF]->(:Article)
    (:Article)-[:CITES]->(:Article)      same law or another law of the corpus
    (:Article)-[:CITES]->(:Law)          a law outside the corpus, or an article not found
    (:Law)-[:AMENDS|REVOKES]->(:Article|:Law)

Laws outside the corpus are `(:Law {external: true})` stubs, so "rewritten by
Lei nº 14.026" stays visible even when that law is not indexed.

This module is pure: rows in, a `GraphPayload` out. `raglab.graph.structured`
writes it to Neo4j.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from raglab.graph.legal import (
    LawMention,
    LawStructure,
    LegalSection,
    article_label,
    format_law_number,
    looks_like_law,
    parse_law,
    parse_markdown_sections,
)

PROFILES = ("auto", "laws", "generic")
# Share of a corpus' documents that must look like laws for "auto" to pick
# the laws profile.
AUTO_LAWS_SHARE = 0.5
PREVIEW_CHARS = 240
SNIPPET_CHARS = 220
MIN_OVERLAP = 20


@dataclass(slots=True, frozen=True)
class DocumentRow:
    id: str
    file_name: str
    content: str
    metadata: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ChunkRow:
    id: str
    document_id: str
    order: int
    char_start: int
    char_end: int


@dataclass(slots=True)
class GraphPayload:
    """Nodes and relationships of one index run, ready for UNWIND writes.

    `nodes` maps a label to its rows (each with a `uid`); `relationships`
    maps (type, source label, target label) to rows with `source`, `target`
    and `props`.
    """

    index_run_id: str
    corpus: str
    profile: str
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    relationships: dict[tuple[str, str, str], list[dict[str, Any]]] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    def node_counts(self) -> dict[str, int]:
        return {label: len(rows) for label, rows in self.nodes.items()}

    def relationship_counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for (kind, _, target), rows in self.relationships.items():
            counts[kind if kind not in {"PART_OF", "CITES"} else f"{kind}->{target}"] += len(rows)
        return dict(sorted(counts.items()))


def resolve_profile(profile: str, documents: list[DocumentRow]) -> str:
    """ "laws" or "generic"; "auto" looks at the documents."""
    if profile not in PROFILES:
        raise ValueError(f"Profil de graphe inconnu: {profile} (attendu: {', '.join(PROFILES)})")
    if profile != "auto":
        return profile
    if not documents:
        return "generic"
    laws = sum(1 for document in documents if looks_like_law(document.content))
    return "laws" if laws / len(documents) >= AUTO_LAWS_SHARE else "generic"


def document_uid(index_run_id: str, document_id: str) -> str:
    return f"{index_run_id}:{document_id}"


def article_uid(index_run_id: str, document_id: str, article: str) -> str:
    return f"{index_run_id}:{document_id}:art:{article}"


def external_law_uid(index_run_id: str, key: str) -> str:
    return f"{index_run_id}:law:{key}"


class _LawIndex:
    """In-corpus laws by number, to resolve "Lei nº X" mentions."""

    def __init__(self, index_run_id: str):
        self.index_run_id = index_run_id
        self.by_key: dict[str, list[tuple[str, int | None]]] = defaultdict(list)
        self.external: dict[str, dict[str, Any]] = {}

    def add(self, key: str, document_id: str, year: int | None) -> None:
        self.by_key[key].append((document_id, year))

    def document_for(self, mention: LawMention) -> str | None:
        candidates = self.by_key.get(mention.key, [])
        if not candidates:
            return None
        if mention.year is not None:
            for document_id, year in candidates:
                if year == mention.year:
                    return document_id
            # Same number, another year: not this law (numbers restart
            # across law kinds and eras).
            if all(year is not None for _, year in candidates):
                return None
        return candidates[0][0]

    def law_uid(self, mention: LawMention) -> tuple[str, bool]:
        """(node uid, in corpus) for a law mention; external stubs are kept."""
        document_id = self.document_for(mention)
        if document_id is not None:
            return document_uid(self.index_run_id, document_id), True
        uid = external_law_uid(self.index_run_id, mention.key)
        if uid not in self.external:
            self.external[uid] = {
                "uid": uid,
                "key": mention.key,
                "number": mention.number,
                "year": mention.year,
                "complementar": mention.complementar,
                "title": mention.label().split("/")[0],
                "external": True,
            }
        return uid, False


def build_payload(
    *,
    index_run_id: str,
    corpus: str,
    documents: list[DocumentRow],
    chunks: list[ChunkRow],
    profile: str = "auto",
) -> GraphPayload:
    resolved = resolve_profile(profile, documents)
    payload = GraphPayload(index_run_id=index_run_id, corpus=corpus, profile=resolved)
    base = {"index_run_id": index_run_id, "corpus": corpus}
    nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relationships: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    stats: Counter[str] = Counter()

    chunks_by_document: dict[str, list[ChunkRow]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_document[chunk.document_id].append(chunk)
    laws = _LawIndex(index_run_id)
    structures: dict[str, LawStructure] = {}
    if resolved == "laws":
        for document in documents:
            structures[document.id] = parse_law(document.content)
            key, year = _law_identity(document)
            if key is not None:
                laws.add(key, document.id, year)

    for document in documents:
        doc_uid = document_uid(index_run_id, document.id)
        structure = structures.get(document.id)
        key, year = _law_identity(document) if structure is not None else (None, None)
        node = {
            **base,
            "uid": doc_uid,
            "document_id": document.id,
            "file_name": document.file_name,
            "title": str(document.metadata.get("title") or document.file_name),
            "is_law": key is not None,
        }
        if key is not None:
            node.update(
                {
                    "key": key,
                    "number": key.removeprefix("LC"),
                    "year": year,
                    "external": False,
                    "ementa": str(document.metadata.get("ementa") or "")[:PREVIEW_CHARS],
                }
            )
        nodes["Document"].append(node)

        sections = structure.sections if structure is not None else parse_markdown_sections(document.content)
        section_uids = _add_sections(nodes, relationships, base, doc_uid, sections)
        stats["sections"] += len(sections)

        ordered = sorted(chunks_by_document.get(document.id, []), key=lambda chunk: chunk.order)
        previous: str | None = None
        for chunk in ordered:
            nodes["Chunk"].append(
                {
                    **base,
                    "uid": chunk.id,
                    "id": chunk.id,
                    "document_id": document.id,
                    "order": chunk.order,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                }
            )
            section = _deepest_section(sections, chunk.char_start)
            if section is not None:
                relationships[("PART_OF", "Chunk", "Section")].append(
                    {"source": chunk.id, "target": section_uids[section.key], "props": {}}
                )
            else:
                relationships[("PART_OF", "Chunk", "Document")].append(
                    {"source": chunk.id, "target": doc_uid, "props": {}}
                )
            if previous is not None:
                relationships[("NEXT", "Chunk", "Chunk")].append({"source": previous, "target": chunk.id, "props": {}})
            previous = chunk.id

        if structure is not None:
            _add_law_structure(
                nodes, relationships, stats, base, laws, document, structure, ordered, key=key, year=year
            )

    nodes["Law"].extend({**base, **row} for row in laws.external.values())
    payload.nodes = dict(nodes)
    payload.relationships = dict(relationships)
    _redirect_missing_articles(payload)
    stats["documents"] = len(documents)
    stats["chunks"] = len(chunks)
    stats["laws_in_corpus"] = sum(len(entries) for entries in laws.by_key.values())
    stats["laws_external"] = len(laws.external)
    payload.stats = dict(sorted(stats.items()))
    return payload


def _law_identity(document: DocumentRow) -> tuple[str | None, int | None]:
    """Law key ("8078", "LC101") and year from the LexML metadata."""
    number = document.metadata.get("number")
    if number is None or not str(number).isdigit():
        return None, None
    raw_year = document.metadata.get("year")
    year = int(raw_year) if raw_year is not None and str(raw_year).isdigit() else None
    urn = str(document.metadata.get("urn") or "")
    prefix = "LC" if ":lei.complementar:" in urn else ""
    return f"{prefix}{int(number)}", year


def _add_sections(
    nodes: dict[str, list[dict[str, Any]]],
    relationships: dict[tuple[str, str, str], list[dict[str, Any]]],
    base: dict[str, Any],
    doc_uid: str,
    sections: list[LegalSection],
) -> dict[str, str]:
    uids: dict[str, str] = {}
    for order, section in enumerate(sections, start=1):
        uid = f"{doc_uid}:sec:{order}"
        uids[section.key] = uid
        nodes["Section"].append(
            {
                **base,
                "uid": uid,
                "document_id": doc_uid.split(":", 1)[1],
                "kind": section.kind,
                "label": section.label,
                "title": section.title[:PREVIEW_CHARS],
                "level": section.level,
                "order": order,
                "path": section.key,
                "char_start": section.start,
                "char_end": section.end,
            }
        )
        if section.parent is not None and section.parent in uids:
            relationships[("PART_OF", "Section", "Section")].append(
                {"source": uid, "target": uids[section.parent], "props": {}}
            )
        else:
            relationships[("PART_OF", "Section", "Document")].append({"source": uid, "target": doc_uid, "props": {}})
    return uids


def _deepest_section(sections: list[LegalSection], offset: int) -> LegalSection | None:
    found: LegalSection | None = None
    for section in sections:
        if section.start <= offset < section.end and (found is None or section.level >= found.level):
            found = section
    return found


def _add_law_structure(
    nodes: dict[str, list[dict[str, Any]]],
    relationships: dict[tuple[str, str, str], list[dict[str, Any]]],
    stats: Counter[str],
    base: dict[str, Any],
    laws: _LawIndex,
    document: DocumentRow,
    structure: LawStructure,
    chunks: list[ChunkRow],
    *,
    key: str | None,
    year: int | None,
) -> None:
    run = base["index_run_id"]
    doc_uid = document_uid(run, document.id)
    text = document.content
    law_number = key.removeprefix("LC") if key else None
    for name, value in structure.stats.items():
        stats[name] += value
    own: set[str] = set()
    for article in structure.articles:
        uid = article_uid(run, document.id, article.number)
        own.add(article.number)
        nodes["Article"].append(
            {
                **base,
                "uid": uid,
                "document_id": document.id,
                "law_number": law_number,
                "law_key": key,
                "number": article.number,
                "label": article_label(article.number),
                "heading": article.label,
                "order": article.order,
                "section": article.section,
                "revoked": article.revoked,
                "vetoed": article.vetoed,
                "char_start": article.start,
                "char_end": article.end,
                "preview": " ".join(text[article.start : article.end].split())[:PREVIEW_CHARS],
            }
        )
        relationships[("PART_OF", "Article", "Document")].append({"source": uid, "target": doc_uid, "props": {}})
        stats["revoked_articles"] += int(article.revoked)
        stats["vetoed_articles"] += int(article.vetoed)
        for chunk in chunks:
            overlap = min(chunk.char_end, article.end) - max(chunk.char_start, article.start)
            # A chunk sharing only a line break or a few characters with
            # the article is not part of it; a short article ("Art. 8º
            # (VETADO).") is part of the chunk that holds it.
            if overlap >= min(MIN_OVERLAP, article.end - article.start):
                relationships[("PART_OF", "Chunk", "Article")].append(
                    {
                        "source": chunk.id,
                        "target": uid,
                        "props": {
                            "overlap": overlap,
                            # The chunk where the article heading sits.
                            "first": chunk.char_start <= article.start < chunk.char_end,
                        },
                    }
                )

    cites: dict[tuple[str, str, str], dict[str, Any]] = {}
    for citation in structure.citations:
        source = article_uid(run, document.id, citation.source)
        if citation.law is None or citation.law.key == key:
            target_document: str | None = document.id
        else:
            target_document = laws.document_for(citation.law)
        if target_document is None:
            assert citation.law is not None
            scope = "external"
            target, _ = laws.law_uid(citation.law)
            target_label = "Law"
        else:
            # An article missing from its law is redirected to the law by
            # `finalize_targets`, once every law's articles are known.
            scope = "same_law" if target_document == document.id else "cross_law"
            target = article_uid(run, target_document, citation.target_article)
            target_label = "Article"
        stats[f"cites_{scope}"] += 1
        stats["cites_relative"] += int(citation.relative)
        edge_key = (source, target, target_label)
        edge = cites.get(edge_key)
        snippet = _snippet(text, citation.start, citation.end)
        if edge is None:
            cites[edge_key] = {
                "source": source,
                "target": target,
                "label": target_label,
                "props": {
                    "mentions": 1,
                    "scope": scope,
                    "relative": citation.relative,
                    "articles": [citation.target_article] if target_label == "Law" else [],
                    "snippet": snippet,
                    "offset": citation.start,
                },
            }
        else:
            edge["props"]["mentions"] += 1
            if target_label == "Law" and citation.target_article not in edge["props"]["articles"]:
                edge["props"]["articles"].append(citation.target_article)
    for edge in cites.values():
        relationships[("CITES", "Article", edge.pop("label"))].append(edge)

    amendments: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for amendment in structure.amendments:
        if amendment.by is not None:
            source, in_corpus = laws.law_uid(amendment.by)
            source_label = "Document" if in_corpus else "Law"
            if source == doc_uid:
                continue
        else:
            source, source_label = doc_uid, "Document"
        if amendment.target_law is None or amendment.target_law.key == key:
            target_document = document.id
        else:
            target_document = laws.document_for(amendment.target_law)
        if target_document == document.id and amendment.by is None:
            # This law amending itself: not an amendment relation.
            continue
        if amendment.target_article is not None and target_document is not None:
            target = article_uid(run, target_document, amendment.target_article)
            target_label = "Article"
        elif target_document is not None:
            target, target_label = document_uid(run, target_document), "Document"
        else:
            assert amendment.target_law is not None
            target, _ = laws.law_uid(amendment.target_law)
            target_label = "Law"
        stats[f"{amendment.relation.lower()}_{amendment.kind}"] += 1
        amendment_key = (amendment.relation, source, target, amendment.kind)
        edge = amendments.get(amendment_key)
        if edge is None:
            amendments[amendment_key] = {
                "relation": amendment.relation,
                "source_label": source_label,
                "source": source,
                "target": target,
                "label": target_label,
                "props": {
                    "kind": amendment.kind,
                    "count": 1,
                    "scopes": [amendment.scope],
                    "via": article_label(amendment.via_article) if amendment.via_article else None,
                    "articles": [amendment.target_article]
                    if amendment.target_article and target_label != "Article"
                    else [],
                    "snippet": _snippet(text, amendment.start, amendment.end),
                    "offset": amendment.start,
                    "evidence_document": document.id,
                },
            }
        else:
            props = edge["props"]
            props["count"] += 1
            if amendment.scope not in props["scopes"]:
                props["scopes"].append(amendment.scope)
    for edge in amendments.values():
        relationships[(edge.pop("relation"), edge.pop("source_label"), edge.pop("label"))].append(edge)


def _snippet(text: str, start: int, end: int) -> str:
    """The sentence around a match, on one line."""
    left = max(text.rfind("\n", 0, start) + 1, start - SNIPPET_CHARS // 2)
    right = text.find("\n", end)
    right = min(right if right != -1 else len(text), end + SNIPPET_CHARS // 2)
    return " ".join(text[left:right].split())


def _redirect_missing_articles(payload: GraphPayload) -> None:
    """Point CITES / AMENDS / REVOKES edges at the law when the article is
    missing from it (segmentation miss, wrong number in the text), keeping
    the article number as a property."""
    articles = {row["uid"] for row in payload.nodes.get("Article", [])}
    for (kind, source_label, target_label), rows in list(payload.relationships.items()):
        if target_label != "Article" or kind not in {"CITES", "AMENDS", "REVOKES"}:
            continue
        kept: list[dict[str, Any]] = []
        moved: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if row["target"] in articles:
                kept.append(row)
                continue
            law_uid, _, article = row["target"].partition(":art:")
            fallback = moved.get((row["source"], law_uid))
            if fallback is None:
                props = {**row["props"], "articles": [article], "unresolved": True}
                moved[(row["source"], law_uid)] = {"source": row["source"], "target": law_uid, "props": props}
            elif article not in fallback["props"]["articles"]:
                fallback["props"]["articles"].append(article)
            payload.stats["unresolved_article_targets"] = payload.stats.get("unresolved_article_targets", 0) + 1
        payload.relationships[(kind, source_label, target_label)] = kept
        if moved:
            payload.relationships.setdefault((kind, source_label, "Document"), []).extend(moved.values())


def law_label(key: str | None, year: int | None) -> str:
    """ "Lei nº 8.078/1990", "Lei Complementar nº 101" from a law key."""
    if not key:
        return ""
    kind = "Lei Complementar" if key.startswith("LC") else "Lei"
    return f"{kind} nº {format_law_number(key.removeprefix('LC'))}" + (f"/{year}" if year else "")
