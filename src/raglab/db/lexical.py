"""Lexical (BM25) index maintenance: text-search configs, tsvectors, stats.

Each chunk gets a `tsvector` built with the text-search configuration of its
document's language, resolved in this order: `documents.metadata_json.language`,
then `corpora.language`, then the `default_language` setting. The resolution
lives in Python (`resolve_language`, `ts_config_for_language`) and is
rendered to an equivalent SQL CASE (`ts_config_sql`) so that refreshing an
index run is a handful of set-based statements.

Collection statistics for BM25 (N, average length, document frequency per
lexeme) are stored per index run in `lexical_index_stats` and
`lexical_term_stats`, so the IDF of a term only depends on the run it is
searched in.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

LOGGER = logging.getLogger(__name__)

# Copies of the built-in configs with `unaccent` in front of the stemmer, so
# "législation" and "legislacao" meet "legislation" / "legislação".
TS_CONFIGS: dict[str, str] = {
    "fr": "raglab_french",
    "pt": "raglab_portuguese",
}
FALLBACK_TS_CONFIG = "raglab_simple"

_CONFIG_SOURCES: dict[str, tuple[str, str, str | None]] = {
    # name -> (built-in config copied, terminal dictionary, stopword list)
    "raglab_french": ("french", "french_stem", "french"),
    "raglab_portuguese": ("portuguese", "portuguese_stem", "portuguese"),
    "raglab_simple": ("simple", "simple", None),
}

_LANGUAGE_ALIASES: dict[str, set[str]] = {
    "fr": {"fr", "fra", "fre", "french", "francais", "français"},
    "pt": {"pt", "por", "portuguese", "portugues", "português"},
}


def normalize_language(value: Any) -> str | None:
    """Map "fr-FR", "French", "pt_BR"... to "fr" / "pt"; other values pass through lowercased."""
    if not isinstance(value, str):
        return None
    head = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if not head:
        return None
    for code, aliases in _LANGUAGE_ALIASES.items():
        if head in aliases:
            return code
    return head


def resolve_language(
    document_metadata: Mapping[str, Any] | None,
    corpus_language: str | None,
    default_language: str,
) -> str | None:
    """Language of a document: its metadata, else its corpus, else the default."""
    for candidate in ((document_metadata or {}).get("language"), corpus_language, default_language):
        language = normalize_language(candidate)
        if language:
            return language
    return None


def ts_config_for_language(language: str | None) -> str:
    return TS_CONFIGS.get(normalize_language(language) or "", FALLBACK_TS_CONFIG)


def ts_config_sql(document_alias: str, corpus_alias: str, default_param: str = ":default_language") -> str:
    """SQL expression equivalent to ts_config_for_language(resolve_language(...))."""
    raw = (
        f"COALESCE(NULLIF(btrim({document_alias}.metadata_json->>'language'), ''), "
        f"NULLIF(btrim({corpus_alias}.language), ''), {default_param})"
    )
    head = f"split_part(replace(lower(btrim({raw})), '_', '-'), '-', 1)"
    branches = []
    for code, config in TS_CONFIGS.items():
        aliases = ", ".join(f"'{alias}'" for alias in sorted(_LANGUAGE_ALIASES[code]))
        branches.append(f"WHEN {head} IN ({aliases}) THEN '{config}'")
    return f"(CASE {' '.join(branches)} ELSE '{FALLBACK_TS_CONFIG}' END)"


def create_text_search_configs(executor) -> None:
    """Create the unaccent-aware configs (idempotent). Needs the unaccent extension.

    Word tokens go through: stopwords (on the accented form, Accept=false so
    other words fall through), then unaccent, then the stemmer. Stopwords
    must be removed first: once unaccented, "à" or "été" no longer match the
    stemmer's accented stopword list.
    """
    executor.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
    for name, (source, dictionary, stopwords) in _CONFIG_SOURCES.items():
        chain = f"unaccent, {dictionary}"
        create_stop = ""
        if stopwords:
            stop_dictionary = f"{name}_stop"
            create_stop = (
                f"IF NOT EXISTS (SELECT 1 FROM pg_ts_dict WHERE dictname = '{stop_dictionary}') THEN "
                f"CREATE TEXT SEARCH DICTIONARY public.{stop_dictionary} "
                f"(TEMPLATE = pg_catalog.simple, STOPWORDS = {stopwords}, ACCEPT = false); "
                "END IF; "
            )
            chain = f"public.{stop_dictionary}, {chain}"
        executor.execute(
            text(
                "DO $$ BEGIN "
                + create_stop
                + f"IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = '{name}') THEN "
                f"CREATE TEXT SEARCH CONFIGURATION public.{name} (COPY = pg_catalog.{source}); "
                f"ALTER TEXT SEARCH CONFIGURATION public.{name} "
                f"ALTER MAPPING FOR asciihword, asciiword, hword_asciipart, hword, hword_part, word WITH {chain}; "
                "END IF; END $$"
            )
        )


def refresh_lexical_index(executor, index_run_id: str, *, default_language: str) -> dict[str, Any]:
    """(Re)build tsvectors, lengths and BM25 statistics for one index run.

    `executor` is a SQLAlchemy Session or Connection. The caller commits.
    """
    params = {"run": str(index_run_id), "default_language": default_language}
    config_expr = ts_config_sql("d", "co")
    executor.execute(
        text(
            "UPDATE chunks c "
            f"SET lexical_tsv = to_tsvector({config_expr}::regconfig, c.text) "
            "FROM documents d JOIN corpora co ON co.id = d.corpus_id "
            "WHERE d.id = c.document_id AND c.index_run_id = :run"
        ),
        params,
    )
    # |d| counts token occurrences (positions), not distinct lexemes.
    executor.execute(
        text(
            "UPDATE chunks c SET lexical_length = COALESCE("
            "(SELECT sum(COALESCE(array_length(u.positions, 1), 1)) FROM unnest(c.lexical_tsv) u), 0) "
            "WHERE c.index_run_id = :run"
        ),
        params,
    )
    executor.execute(text("DELETE FROM lexical_term_stats WHERE index_run_id = :run"), params)
    executor.execute(
        text(
            "INSERT INTO lexical_term_stats (index_run_id, lexeme, doc_freq) "
            "SELECT c.index_run_id, u.lexeme, count(*) "
            "FROM chunks c CROSS JOIN LATERAL unnest(c.lexical_tsv) u "
            "WHERE c.index_run_id = :run GROUP BY c.index_run_id, u.lexeme"
        ),
        params,
    )
    row = executor.execute(
        text(
            "INSERT INTO lexical_index_stats (index_run_id, doc_count, avg_length, ts_configs, updated_at) "
            "SELECT CAST(:run AS uuid), count(*), COALESCE(avg(c.lexical_length), 0), "
            f"COALESCE(array_agg(DISTINCT {config_expr}), ARRAY[]::text[]), now() "
            "FROM chunks c JOIN documents d ON d.id = c.document_id JOIN corpora co ON co.id = d.corpus_id "
            "WHERE c.index_run_id = :run "
            "ON CONFLICT (index_run_id) DO UPDATE SET doc_count = EXCLUDED.doc_count, "
            "avg_length = EXCLUDED.avg_length, ts_configs = EXCLUDED.ts_configs, updated_at = now() "
            "RETURNING doc_count, avg_length, ts_configs"
        ),
        params,
    ).one()
    stats = {"doc_count": int(row[0]), "avg_length": float(row[1]), "ts_configs": list(row[2])}
    LOGGER.info("lexical.refreshed", extra={"index_run_id": str(index_run_id), **stats})
    return stats
