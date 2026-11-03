from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from raglab.db.lexical import (
    FALLBACK_TS_CONFIG,
    create_text_search_configs,
    normalize_language,
    resolve_language,
    ts_config_for_language,
    ts_config_sql,
)
from raglab.stores.lexical.postgres import build_or_tsquery, tsquery_literal


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("fr", "fr"),
        ("FR-fr", "fr"),
        ("french", "fr"),
        ("Français", "fr"),
        ("pt_BR", "pt"),
        ("Portuguese", "pt"),
        ("de", "de"),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_normalize_language(raw, expected):
    assert normalize_language(raw) == expected


def test_resolve_language_prefers_document_then_corpus_then_default():
    assert resolve_language({"language": "pt"}, "fr", "fr") == "pt"
    assert resolve_language({}, "pt", "fr") == "pt"
    assert resolve_language({"language": "  "}, None, "fr") == "fr"
    assert resolve_language(None, None, "pt-BR") == "pt"


@pytest.mark.parametrize(
    ("language", "config"),
    [
        ("fr", "raglab_french"),
        ("pt", "raglab_portuguese"),
        ("pt-BR", "raglab_portuguese"),
        ("en", FALLBACK_TS_CONFIG),
        (None, FALLBACK_TS_CONFIG),
    ],
)
def test_ts_config_for_language(language, config):
    assert ts_config_for_language(language) == config


def test_ts_config_sql_follows_the_python_resolution_order():
    sql = ts_config_sql("d", "co")
    document_pos = sql.index("d.metadata_json->>'language'")
    corpus_pos = sql.index("co.language")
    default_pos = sql.index(":default_language")
    assert document_pos < corpus_pos < default_pos
    assert "THEN 'raglab_french'" in sql
    assert "THEN 'raglab_portuguese'" in sql
    assert f"ELSE '{FALLBACK_TS_CONFIG}'" in sql
    assert "'pt'" in sql and "'portuguese'" in sql


def test_create_text_search_configs_removes_stopwords_before_unaccent():
    executor = MagicMock()
    create_text_search_configs(executor)
    statements = [str(call.args[0]) for call in executor.execute.call_args_list]
    assert "CREATE EXTENSION IF NOT EXISTS unaccent" in statements[0]
    french = next(sql for sql in statements if "raglab_french " in sql or "raglab_french (" in sql)
    assert "STOPWORDS = french" in french
    assert "WITH public.raglab_french_stop, unaccent, french_stem" in french
    simple = next(sql for sql in statements if "raglab_simple" in sql)
    assert "WITH unaccent, simple" in simple


def test_tsquery_literal_escapes_quotes_and_backslashes():
    assert tsquery_literal("lei") == "'lei'"
    assert tsquery_literal("d'eau") == "'d''eau'"
    assert tsquery_literal("a\\b") == "'a\\\\b'"
    assert build_or_tsquery(["lei", "8.666"]) == "'lei' | '8.666'"
