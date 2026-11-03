"""Resolve legal citations in a question ("art. 49 da Lei nº 8.078").

Dense and lexical retrieval both fail on these questions (baseline-v1 and
hybrid-v1: 9% Recall@5 on LexML questions citing an article). Embeddings
blur identifiers ("art. 49" ≈ "art. 94"), and BM25 finds the right law but
not the article: the law number only appears in the law's title chunk, and
"art. 2" matches every law. A citation is structured data, so it is resolved
as such:

1. parse the law number (and article / year when present) from the question;
2. find the document whose metadata carries that law number (`number`, as
   written by `raglab lexml fulltext`) in the queried index run;
3. put first the chunk where that article starts (and the following chunk,
   since long articles span two), then rank the rest of that law with the
   normal retrieval, restricted to the law.

When the question cites no law, or a law absent from the index, retrieval is
unchanged. Chunking is untouched: this only reads chunk text and order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, Document, IndexRun
from raglab.domain.schemas import RetrievedChunk

# "Lei nº 8.078", "Lei n. 8078/90", "Lei 13.445, de 24 de maio de 2017",
# "Lei Complementar nº 101". The number may carry a thousands dot.
_LAW_RE = re.compile(
    r"\blei(?:\s+complementar)?\s*(?:n(?:[º°o.]|úmero)?\s*)?(\d{1,2}\.?\d{3}|\d{2,3})\b(?:\s*/\s*(\d{2,4}))?",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(r"\bart(?:igo|\.)?\s*(\d{1,4})\s*(?:[º°o]\b|[º°])?(?:\s*-\s*([A-Z])\b)?", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:de\s+)?(?:\d{1,2}/\d{1,2}/)?((?:19|20)\d{2})\b")

# Longest article span pinned (amending articles that quote other laws can
# run over many chunks); the span ends where the next article starts.
MAX_ARTICLE_CHUNKS = 6
_ANY_ARTICLE_START = re.compile(r"(?:^|\n)\s*Art\.\s*\d", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class Citation:
    law_number: str
    article: str | None = None
    year: int | None = None

    def label(self) -> str:
        parts = []
        if self.article:
            parts.append(f"art. {self.article}")
        parts.append(f"Lei nº {self.law_number}" + (f" ({self.year})" if self.year else ""))
        return " — ".join(parts)


def parse_citation(question: str) -> Citation | None:
    law = _LAW_RE.search(question)
    if law is None:
        return None
    number = law.group(1).replace(".", "")
    year: int | None = None
    if law.group(2):
        raw = int(law.group(2))
        year = raw if raw > 999 else (1900 + raw if raw > 30 else 2000 + raw)
    else:
        after = _YEAR_RE.search(question, law.end())
        if after:
            year = int(after.group(1))
    article = None
    article_match = _ARTICLE_RE.search(question)
    if article_match and article_match.start() < law.start():
        article = article_match.group(1) + (f"-{article_match.group(2).upper()}" if article_match.group(2) else "")
    elif article_match:
        article = article_match.group(1)
    return Citation(law_number=number, article=article, year=year)


def article_start_pattern(article: str) -> re.Pattern[str]:
    """Matches the line opening the article: "Art. 49.", "Art. 2º", "Art. 3o"."""
    number, _, letter = article.partition("-")
    suffix = rf"\s*-\s*{letter}" if letter else ""
    return re.compile(rf"(?:^|\n)\s*Art\.\s*{number}{suffix}\s*(?:[º°o]|\.|\s)(?!\d)", re.IGNORECASE)


def find_law_document(session: Session, index_run: IndexRun, citation: Citation) -> str | None:
    """Id of the document of the cited law in this index run's corpus."""
    stmt = select(Document.id, Document.metadata_json).where(
        Document.corpus_id == index_run.corpus_id,
        Document.metadata_json["number"].astext == citation.law_number,
    )
    rows = session.execute(stmt).all()
    if not rows:
        return None
    if citation.year is not None and len(rows) > 1:
        for document_id, metadata in rows:
            if str((metadata or {}).get("year")) == str(citation.year):
                return str(document_id)
    return str(rows[0][0])


def article_chunks(session: Session, index_run: IndexRun, document_id: str, article: str) -> list[RetrievedChunk]:
    """The chunks of the cited article: from the chunk where it starts to
    the chunk before the next article starts (at most MAX_ARTICLE_CHUNKS)."""
    rows = session.execute(
        select(Chunk.id, Chunk.text, Chunk.char_start, Chunk.char_end, Document.file_name, Document.source_path)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.index_run_id == index_run.id, Chunk.document_id == document_id)
        .order_by(Chunk.chunk_order)
    ).all()
    pattern = article_start_pattern(article)
    start = next((index for index, row in enumerate(rows) if pattern.search(row.text)), None)
    if start is None:
        return []
    end = start + 1
    while end < len(rows) and end - start < MAX_ARTICLE_CHUNKS:
        # A chunk that opens another article ends the span; its own text
        # before that opening still belongs to the cited article, so keep it.
        opening = _ANY_ARTICLE_START.search(rows[end].text)
        end += 1
        if opening is not None:
            break
    pinned = rows[start:end]
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=document_id,
            file_name=row.file_name,
            source_path=row.source_path,
            chunk_text=row.text,
            score=1.0,
            rank=position,
            char_start=row.char_start,
            char_end=row.char_end,
            citation_match=True,
        )
        for position, row in enumerate(pinned, start=1)
    ]


def merge_with_citation(pinned: list[RetrievedChunk], ranked: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
    """Article chunks first, then the rest of the law, re-ranked.

    Within the article, chunks the retriever also ranked come first, in its
    order (the most relevant part of a long article leads); the others keep
    the article's reading order.
    """
    position = {chunk.chunk_id: index for index, chunk in enumerate(ranked)}
    article = sorted(pinned, key=lambda chunk: (position.get(chunk.chunk_id, len(ranked)), pinned.index(chunk)))
    seen = {chunk.chunk_id for chunk in pinned}
    merged = [*article, *(chunk for chunk in ranked if chunk.chunk_id not in seen)][:top_k]
    return [chunk.model_copy(update={"rank": rank}) for rank, chunk in enumerate(merged, start=1)]
