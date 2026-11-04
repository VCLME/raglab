from __future__ import annotations

from raglab.config import Settings


def test_shipped_default_is_the_measured_best_pipeline(monkeypatch):
    monkeypatch.delenv("RAGLAB_DEFAULT_RETRIEVAL_MODE", raising=False)
    monkeypatch.delenv("RAGLAB_DEFAULT_RERANK", raising=False)
    monkeypatch.delenv("RAGLAB_CITATION_RESOLVER", raising=False)
    monkeypatch.delenv("RAGLAB_VERSIONS_DEFAULT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.default_retrieval_mode == "hybrid"
    assert settings.default_rerank is True
    assert settings.citation_resolver is True
    # Measured in versions-full-v1 (9.10): versions set Recall@5 0.75 -> 0.93.
    assert settings.versions_default == "in_force"
