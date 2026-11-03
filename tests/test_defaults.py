from __future__ import annotations

from raglab.config import Settings


def test_shipped_default_is_the_measured_best_pipeline(monkeypatch):
    monkeypatch.delenv("RAGLAB_DEFAULT_RETRIEVAL_MODE", raising=False)
    monkeypatch.delenv("RAGLAB_DEFAULT_RERANK", raising=False)
    settings = Settings(_env_file=None)
    assert settings.default_retrieval_mode == "hybrid"
    assert settings.default_rerank is True
