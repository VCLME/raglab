import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_reports_dir(tmp_path, monkeypatch):
    """Keep benchmark reports written by tests out of the real data/reports."""
    from raglab.config import get_settings

    monkeypatch.setenv("RAGLAB_REPORTS_DIR", str(tmp_path / "reports"))
    # Unit tests exercise each retrieval path explicitly; they do not depend
    # on the shipped default (hybrid + rerank), tested in test_defaults.py.
    monkeypatch.setenv("RAGLAB_DEFAULT_RETRIEVAL_MODE", "dense")
    monkeypatch.setenv("RAGLAB_DEFAULT_RERANK", "false")
    monkeypatch.setenv("RAGLAB_CITATION_RESOLVER", "false")
    # Indexing tests never reach Neo4j unless they ask for the graph.
    monkeypatch.setenv("RAGLAB_GRAPH_BUILD_ON_INDEX", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
