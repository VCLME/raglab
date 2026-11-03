"""Resolve legal citations in a question ("art. 49 da Lei nº 8.078",
"article L. 221-18 du code de la consommation").

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

French codes (`raglab legifrance fetch`) are stored one article version per
document, with the code and the article number in the metadata (`code`,
`article_number`). A question citing "article L. 221-18 du code de la
consommation", "art. R. 212-1" or "l'article 1240 du code civil" resolves to
the version of that article in force (the latest one for a repealed
article; the one in force on the reference date of the `versions` option
when the question asks about the past), whose chunks are pinned first; the search is restricted to the
cited code, the analogue of restricting to the cited Brazilian law.

EU acts (`raglab eurlex fetch`) are stored one unit (article, recital,
annex) per document and language, with the act's CELEX and the unit in the
metadata (`celex`, `unit`, `unit_number`, `language`). A question citing
"l'article 32 du RGPD", "Article 6(1)(a) GDPR", "o artigo 5.º do Regulamento
(UE) 2016/679" or "considérant 39 du RGPD" resolves to that unit in the
question's language (else another language), the version in force; its
chunks are pinned first and the search is restricted to the cited act.

When the question cites no law, or a law absent from the index, retrieval is
unchanged. Chunking is untouched: this only reads chunk text and order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, Document, IndexRun
from raglab.domain.schemas import RetrievedChunk
from raglab.domain.versions import valid_at
from raglab.eurlex.acts import BY_CELEX, UNIT_NAMES, celex_label
from raglab.eurlex.references import extract_references, find_act_names, find_acts
from raglab.legifrance.codes import CODES, find_code_mentions
from raglab.legifrance.references import article_label, find_plain_article, find_prefixed_article

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
# How far after "article 1240" the code must be named ("du code civil").
_PLAIN_CODE_WINDOW = 12
# Versions that apply when the corpus was frozen (see raglab.legifrance).
_IN_FORCE_STATES = ("VIGUEUR", "ABROGE_DIFF")


@dataclass(slots=True, frozen=True)
class Citation:
    #: Brazilian law number; None for an article of a French code.
    law_number: str | None
    article: str | None = None
    year: int | None = None
    #: French code slug ("consommation", "civil"); None when the question
    #: cites an article ("art. R. 212-1") without naming its code.
    code: str | None = None
    #: EU act CELEX ("32016R0679") when the question cites an EU act; then
    #: `article` is the unit number and `unit` says which kind of unit.
    celex: str | None = None
    #: "article", "recital" or "annex"; None when only the act is named.
    unit: str | None = None
    paragraph: str | None = None
    point: str | None = None
    #: Language of the question ("fr", "en", "pt"), guessed for EU citations.
    language: str | None = None

    def label(self) -> str:
        if self.celex is not None:
            return eu_citation_label(self)
        if self.law_number is None:
            label = f"art. {article_label(self.article or '')}"
            return label + (f" — {CODES[self.code].title}" if self.code in CODES else "")
        parts = []
        if self.article:
            parts.append(f"art. {self.article}")
        parts.append(f"Lei nº {self.law_number}" + (f" ({self.year})" if self.year else ""))
        return " — ".join(parts)


def parse_citation(question: str) -> Citation | None:
    law = _LAW_RE.search(question)
    if law is None:
        return parse_eu_citation(question) or parse_code_citation(question)
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


def parse_code_citation(question: str) -> Citation | None:
    """An article of a French code: "article L. 221-18 du code de la
    consommation", "art. R. 212-1", "l'article 1240 du code civil".

    An article with a part letter (L, R, D, A, LO) is enough on its own; a
    plain number counts only when a code is named right after it, since laws
    and decrees number their articles the same way.
    """
    mentions = find_code_mentions(question)
    prefixed = find_prefixed_article(question)
    if prefixed is not None:
        article, _, end = prefixed
        # The code named after the article, else anywhere in the question.
        candidates = [mention for mention in mentions if mention.start >= end] or mentions
        return Citation(law_number=None, article=article, code=candidates[0].slug if candidates else None)
    plain = find_plain_article(question)
    if plain is None:
        return None
    article, _, end = plain
    named = next((mention for mention in mentions if 0 <= mention.start - end <= _PLAIN_CODE_WINDOW), None)
    if named is None:
        return None
    return Citation(law_number=None, article=article, code=named.slug)


_LANGUAGE_WORDS = {
    "fr": {
        *("le", "la", "les", "du", "des", "de", "quel", "quelle", "quels", "quelles", "est", "que", "dans", "pour"),
        *("selon", "article", "considérant", "annexe", "dit", "prévoit", "doit", "qui", "sur", "une", "au", "aux"),
    },
    "en": {
        *("the", "of", "what", "which", "is", "does", "under", "for", "according", "to", "how", "must", "who"),
        *("recital", "annex", "say", "says", "in", "an", "and", "are"),
    },
    "pt": {
        *("o", "os", "as", "do", "da", "dos", "das", "que", "qual", "quais", "é", "para", "nos", "segundo"),
        *("artigo", "considerando", "anexo", "diz", "prevê", "deve", "um", "uma", "no", "na", "em"),
    },
}
_EU_RECITAL_RE = re.compile(r"\b(?:recitals?|consid[ée]rants?|considerandos?)\s+\(?\d", re.IGNORECASE)


def guess_language(question: str) -> str:
    """ "fr", "en" or "pt" from function words (EU questions only)."""
    words = re.findall(r"[a-zà-ÿ]+", question.lower())
    scores = {language: sum(word in vocabulary for word in words) for language, vocabulary in _LANGUAGE_WORDS.items()}
    return max(scores, key=lambda language: (scores[language], language == "en"))


def parse_eu_citation(question: str) -> Citation | None:
    """A unit of an EU act: "article 32 du RGPD", "Article 6(1)(a) GDPR",
    "artigo 5.º do Regulamento (UE) 2016/679", "considérant 39 du RGPD".

    The act must be named (short name or number), except for a recital,
    which only EU acts have. A unit not qualified by a numbered act belongs
    to the act named right after it ("l'article 5 de DORA"), else to the
    first act named.
    """
    named = [*find_act_names(question), *(m for m in find_acts(question) if m.celex is not None)]
    mentions = sorted({(m.start, m.celex): m for m in named}.values(), key=lambda mention: mention.start)
    if not mentions and not _EU_RECITAL_RE.search(question):
        return None
    language = guess_language(question)
    default = mentions[0].celex if mentions else None
    references = [
        reference
        for reference in extract_references(question, language, own_celex=default or "")
        if reference.celex is not None
    ]
    if not references:
        if default is None:
            return None
        return Citation(law_number=None, celex=default, language=language)
    reference = references[0]
    celex = reference.celex or None
    if reference.scope == "same_act":
        after = next((mention for mention in mentions if 0 <= mention.start - reference.end <= 40), None)
        celex = after.celex if after is not None else default
    if celex is None:
        return None
    return Citation(
        law_number=None,
        article=reference.number,
        celex=celex,
        unit=reference.unit,
        paragraph=reference.paragraph,
        point=reference.point,
        language=language,
    )


def eu_citation_label(citation: Citation) -> str:
    """ "Article 32(1)(b) — GDPR", "Considérant 39 — RGPD"."""
    language = citation.language or "en"
    act = BY_CELEX.get(citation.celex or "")
    act_name = act.short_name(language) if act is not None else celex_label(citation.celex or "", language)
    if citation.unit is None:
        return act_name
    number = citation.article or ""
    if citation.unit == "article":
        number += "".join(f"({part})" for part in (citation.paragraph, citation.point) if part)
    return f"{UNIT_NAMES[language][citation.unit]} {number} — {act_name}"


@dataclass(slots=True, frozen=True)
class EuUnit:
    document_id: str
    celex: str
    language: str | None
    in_force: bool


def find_eu_unit(session: Session, index_run: IndexRun, citation: Citation) -> EuUnit | None:
    """The document of the cited unit in this index run's corpus: in the
    question's language when the corpus has it, the version in force first."""
    if citation.celex is None or citation.unit is None or citation.article is None:
        return None
    rows = session.execute(
        select(Document.id, Document.metadata_json).where(
            Document.corpus_id == index_run.corpus_id,
            Document.metadata_json["celex"].astext == citation.celex,
            Document.metadata_json["unit"].astext == citation.unit,
            Document.metadata_json["unit_number"].astext == citation.article,
        )
    ).all()
    if not rows:
        return None

    def rank(row: Any) -> tuple[int, int, str]:
        metadata = row[1] or {}
        return (
            int(metadata.get("language") == citation.language),
            int(bool(metadata.get("in_force", True))),
            str(metadata.get("valid_from") or ""),
        )

    document_id, metadata = max(rows, key=rank)
    metadata = metadata or {}
    return EuUnit(
        document_id=str(document_id),
        celex=citation.celex,
        language=metadata.get("language"),
        in_force=bool(metadata.get("in_force", True)),
    )


def has_eu_act(session: Session, index_run: IndexRun, celex: str) -> bool:
    """Whether this index run's corpus holds units of the act."""
    row = session.execute(
        select(Document.id)
        .where(Document.corpus_id == index_run.corpus_id, Document.metadata_json["celex"].astext == celex)
        .limit(1)
    ).first()
    return row is not None


@dataclass(slots=True, frozen=True)
class CodeArticle:
    document_id: str
    code: str | None
    etat: str | None


def _version_rank(metadata: dict, on: date | None = None) -> tuple[int, str]:
    if on is not None:
        # The version that applied on that day first, then the latest one
        # that had started by then, then the rest.
        started = str(metadata.get("date_debut") or "") <= on.isoformat()
        return (2 if valid_at(metadata, on) else 1 if started else 0, str(metadata.get("date_debut") or ""))
    etat = metadata.get("etat")
    return (
        2 if etat in _IN_FORCE_STATES else 1 if etat == "VIGUEUR_DIFF" else 0,
        str(metadata.get("date_debut") or ""),
    )


def find_code_article(
    session: Session, index_run: IndexRun, citation: Citation, *, on: date | None = None
) -> CodeArticle | None:
    """The document of the cited article in this index run's corpus: the
    version in force, otherwise the most recent one. With `on` (a question
    about the past, `versions=as_of=...`), the version that applied that day:
    "l'article L. 121-21 dans sa rédaction de 2014" is the 14-day withdrawal
    right, not the debt-collection article that reuses the number since 2016."""
    stmt = select(Document.id, Document.metadata_json).where(
        Document.corpus_id == index_run.corpus_id,
        Document.metadata_json["article_number"].astext == citation.article,
    )
    if citation.code is not None:
        stmt = stmt.where(Document.metadata_json["code"].astext == citation.code)
    rows = session.execute(stmt).all()
    if not rows:
        return None
    document_id, metadata = max(rows, key=lambda row: _version_rank(row[1] or {}, on))
    metadata = metadata or {}
    return CodeArticle(document_id=str(document_id), code=metadata.get("code"), etat=metadata.get("etat"))


def document_chunks(session: Session, index_run: IndexRun, document_id: str) -> list[RetrievedChunk]:
    """Every chunk of a one-article document, in reading order."""
    rows = session.execute(
        select(Chunk.id, Chunk.text, Chunk.char_start, Chunk.char_end, Document.file_name, Document.source_path)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.index_run_id == index_run.id, Chunk.document_id == document_id)
        .order_by(Chunk.chunk_order)
    ).all()
    return [_pinned(row, document_id, position) for position, row in enumerate(rows, start=1)]


def _pinned(row: Any, document_id: str, position: int) -> RetrievedChunk:
    return RetrievedChunk(
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
    return [_pinned(row, document_id, position) for position, row in enumerate(pinned, start=1)]


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
