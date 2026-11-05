import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest  # noqa: E402

UNREACHABLE_TEST_DATABASE = "postgresql+psycopg://raglab:raglab@127.0.0.1:1/raglab_test"


@pytest.fixture(autouse=True)
def _isolated_reports_dir(tmp_path, monkeypatch):
    """Keep benchmark reports written by tests out of the real data/reports."""
    from raglab.config import get_settings

    monkeypatch.setenv("RAGLAB_REPORTS_DIR", str(tmp_path / "reports"))
    # Never the working database: a *_test database when one is given, else
    # an address nothing listens on, so a stray write fails at once. The
    # engine also refuses any database not named *_test.
    monkeypatch.setenv("RAGLAB_DATABASE_URL", os.environ.get("RAGLAB_TEST_DATABASE_URL") or UNREACHABLE_TEST_DATABASE)
    monkeypatch.setenv("RAGLAB_REQUIRE_TEST_DATABASE", "true")
    from raglab.db import session as db_session

    db_session.reset_engine()
    # Unit tests exercise each retrieval path explicitly; they do not depend
    # on the shipped default (hybrid + rerank), tested in test_defaults.py.
    monkeypatch.setenv("RAGLAB_DEFAULT_RETRIEVAL_MODE", "dense")
    monkeypatch.setenv("RAGLAB_DEFAULT_RERANK", "false")
    monkeypatch.setenv("RAGLAB_CITATION_RESOLVER", "false")
    # Query translation calls the llama.cpp writer: tested explicitly in
    # test_query_translation.py, the shipped default in test_defaults.py.
    monkeypatch.setenv("RAGLAB_QUERY_TRANSLATION", "false")
    monkeypatch.setenv("RAGLAB_ROUTING_CROSS_LANGUAGE", "false")
    # Indexing tests never reach Neo4j unless they ask for the graph.
    monkeypatch.setenv("RAGLAB_GRAPH_BUILD_ON_INDEX", "false")
    # Answers go to (mocked) Ollama: the shipped llama.cpp writer would probe
    # and start a real server. Writer selection is tested in test_llm_writer.py.
    monkeypatch.setenv("RAGLAB_LLM_PROVIDERS", "ollama")
    monkeypatch.setenv("RAGLAB_DEFAULT_LLM_PROVIDER", "ollama")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    db_session.reset_engine()


class NoVersionLookup:
    """A corpus without version metadata: services built on mock sessions
    skip the versions option's two reads (tests/test_versions.py fakes them)."""

    def __init__(self, session=None):
        self.session = session

    def has_history(self, index_run):
        return False

    def metadata(self, document_ids):
        return {}


@pytest.fixture(autouse=True)
def _no_version_lookup(monkeypatch):
    import raglab.retrieval.service as service_module

    monkeypatch.setattr(service_module, "VersionLookup", NoVersionLookup)
