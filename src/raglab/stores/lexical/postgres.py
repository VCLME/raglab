"""BM25 search over the chunks' tsvectors, computed in PostgreSQL.

`ts_rank` has no IDF, so the score is computed explicitly (Okapi BM25 with
the Lucene IDF, always positive):

    idf(t)      = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
    score(d, q) = sum over t in q ∩ d of
                  idf(t) * tf(t, d) * (k1 + 1) / (tf(t, d) + k1 * (1 - b + b * |d| / avgdl))

N, avgdl and df come from lexical_index_stats / lexical_term_stats of the
index run being searched. Query lexemes are OR-ed: a chunk only needs one of
them to be a candidate, which the GIN index on chunks.lexical_tsv finds.

Frequent terms ("lei", "art" in a law corpus) make almost every chunk a
candidate. The search therefore first selects candidates with the rarer
terms only (still scoring them with every query term), MaxScore-style: a
chunk containing none of the rare terms scores strictly less than
sum(idf(t) * (k1 + 1)) over the frequent terms, so when the k-th score of
that first pass reaches this bound the top-k is exact. Otherwise the full OR
query runs. Results are identical either way; only the work differs.
"""

from __future__ import annotations

import math

from sqlalchemy import Float, SmallInteger, Text, bindparam, cast, column, func, literal_column, select, text, true
from sqlalchemy.dialects.postgresql import ARRAY, TSQUERY
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, Document, IndexRun, LexicalIndexStats, LexicalTermStats
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk
from raglab.stores.vector.postgres import PostgresVectorStore


def tsquery_literal(lexeme: str) -> str:
    """Quote a lexeme for tsquery input: no normalisation, exact match."""
    escaped = lexeme.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def build_or_tsquery(lexemes: list[str]) -> str:
    return " | ".join(tsquery_literal(lexeme) for lexeme in lexemes)


def bm25_idf(doc_count: int, doc_freq: int) -> float:
    return math.log(1.0 + (doc_count - doc_freq + 0.5) / (doc_freq + 0.5))


class PostgresLexicalStore:
    # A term present in more than this share of the run's chunks does not
    # select candidates in the first pass (it still counts in the score).
    # 0.2 was the fastest setting on the LexML set (300 questions, 6k
    # chunks): lower values make the bound too loose and force a second pass.
    COMMON_TERM_FRACTION = 0.2

    def __init__(self, *, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b

    @staticmethod
    def get_stats(session: Session, index_run_id: str) -> LexicalIndexStats | None:
        return session.get(LexicalIndexStats, index_run_id)

    @staticmethod
    def query_lexemes(session: Session, *, ts_configs: list[str], question: str) -> list[str]:
        """Lexemes of the question under every config used by the index run."""
        if not ts_configs or not question.strip():
            return []
        rows = session.execute(
            text(
                "SELECT DISTINCT u.lexeme FROM unnest(CAST(:configs AS text[])) AS cfg(name) "
                "CROSS JOIN LATERAL unnest(to_tsvector(cfg.name::regconfig, :question)) u "
                "ORDER BY u.lexeme"
            ),
            {"configs": list(ts_configs), "question": question},
        ).scalars()
        return list(rows)

    def search(
        self,
        session: Session,
        *,
        index_run: IndexRun,
        question: str,
        top_k: int,
        filters: RetrievalFilters | None = None,
        k1: float | None = None,
        b: float | None = None,
    ) -> tuple[list[RetrievedChunk], list[str]]:
        stats = self.get_stats(session, index_run.id)
        if stats is None:
            raise ValueError(
                f"L'index_run {index_run.id} n'a pas d'index lexical. "
                "Lance `raglab db init` pour migrer la base (le backfill BM25 est inclus)."
            )
        lexemes = self.query_lexemes(session, ts_configs=list(stats.ts_configs), question=question)
        if not lexemes or stats.doc_count == 0:
            return [], lexemes

        # Lexemes absent from the run match nothing: they are dropped here.
        doc_freqs: dict[str, int] = {
            lexeme: int(doc_freq)
            for lexeme, doc_freq in session.execute(
                select(LexicalTermStats.lexeme, LexicalTermStats.doc_freq).where(
                    LexicalTermStats.index_run_id == index_run.id,
                    LexicalTermStats.lexeme.in_(lexemes),
                )
            ).all()
        }
        if not doc_freqs:
            return [], lexemes

        k1 = self.k1 if k1 is None else k1
        b = self.b if b is None else b
        idf = {lexeme: bm25_idf(stats.doc_count, doc_freq) for lexeme, doc_freq in doc_freqs.items()}
        common = {
            lexeme for lexeme, doc_freq in doc_freqs.items() if doc_freq > self.COMMON_TERM_FRACTION * stats.doc_count
        }
        rare = sorted(set(doc_freqs) - common)

        def score(candidate_lexemes: list[str]) -> list[RetrievedChunk]:
            return self._score(
                session,
                index_run_id=index_run.id,
                candidate_lexemes=candidate_lexemes,
                idf=idf,
                top_k=top_k,
                filters=filters,
                k1=k1,
                b=b,
                avgdl=stats.avg_length or 1.0,
            )

        if common and rare:
            results = score(rare)
            bound = sum(idf[lexeme] * (k1 + 1.0) for lexeme in common)
            if len(results) >= top_k and results[top_k - 1].score >= bound:
                return results, lexemes
        return score(sorted(doc_freqs)), lexemes

    @staticmethod
    def _score(
        session: Session,
        *,
        index_run_id: str,
        candidate_lexemes: list[str],
        idf: dict[str, float],
        top_k: int,
        filters: RetrievalFilters | None,
        k1: float,
        b: float,
        avgdl: float,
    ) -> list[RetrievedChunk]:
        """BM25 top-k of the chunks holding one of `candidate_lexemes`, scored on every `idf` term."""
        query_lexemes = list(idf)
        candidate_query = select(
            Chunk.id.label("chunk_id"),
            # Keep only the query lexemes before unnesting: setweight marks
            # them 'A' (to_tsvector leaves every lexeme at 'D') and ts_filter
            # drops the rest, so scoring reads a few rows per chunk instead
            # of the whole vector.
            func.ts_filter(
                func.setweight(
                    Chunk.lexical_tsv,
                    literal_column("'A'::\"char\""),
                    cast(bindparam("lexemes", query_lexemes), ARRAY(Text)),
                ),
                literal_column("'{a}'::\"char\"[]"),
            ).label("tsv"),
            Chunk.lexical_length.label("doc_length"),
        ).where(
            Chunk.index_run_id == index_run_id,
            Chunk.lexical_tsv.op("@@")(cast(bindparam("tsq", build_or_tsquery(candidate_lexemes)), TSQUERY)),
        )
        if filters is not None and not filters.is_empty():
            candidate_query = PostgresVectorStore._apply_filters(
                candidate_query.join(Document, Document.id == Chunk.document_id), filters
            )
        candidates = candidate_query.cte("candidates")

        query_terms = select(
            func.unnest(cast(bindparam("term_lexemes", query_lexemes), ARRAY(Text))).label("lexeme"),
            func.unnest(cast(bindparam("term_idf", [idf[lexeme] for lexeme in query_lexemes]), ARRAY(Float))).label(
                "idf"
            ),
        ).cte("query_terms")
        terms = (
            func.unnest(candidates.c.tsv)
            .table_valued(
                column("lexeme", Text),
                column("positions", ARRAY(SmallInteger)),
                column("weights", ARRAY(Text)),
            )
            .lateral("terms")
        )
        tf = cast(func.coalesce(func.array_length(terms.c.positions, 1), 1), Float)
        doc_length = cast(func.coalesce(candidates.c.doc_length, 0), Float)
        norm = k1 * (1.0 - b + b * doc_length / avgdl)
        score = func.sum(query_terms.c.idf * tf * (k1 + 1.0) / (tf + norm)).label("score")

        scored = (
            select(candidates.c.chunk_id, score)
            .select_from(candidates)
            .join(terms, true())
            .join(query_terms, query_terms.c.lexeme == terms.c.lexeme)
            .group_by(candidates.c.chunk_id)
            .order_by(score.desc(), candidates.c.chunk_id)
            .limit(top_k)
            .subquery("scored")
        )
        # Plain columns rather than ORM entities: Document.content is the full
        # document text (a whole law for LexML) and is not needed here.
        rows = session.execute(
            select(
                Chunk.id,
                Chunk.text,
                Chunk.char_start,
                Chunk.char_end,
                Document.id.label("document_id"),
                Document.file_name,
                Document.source_path,
                scored.c.score,
            )
            .join(scored, scored.c.chunk_id == Chunk.id)
            .join(Document, Document.id == Chunk.document_id)
            .order_by(scored.c.score.desc(), Chunk.id)
        ).all()

        results: list[RetrievedChunk] = []
        for rank, row in enumerate(rows, start=1):
            bm25 = float(row.score or 0.0)
            results.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    file_name=row.file_name,
                    source_path=row.source_path,
                    chunk_text=row.text,
                    score=bm25,
                    rank=rank,
                    char_start=row.char_start,
                    char_end=row.char_end,
                    lexical_score=bm25,
                    lexical_rank=rank,
                )
            )
        return results
