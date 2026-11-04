from __future__ import annotations

from raglab.config import Settings


def test_shipped_default_is_the_measured_best_pipeline(monkeypatch):
    monkeypatch.delenv("RAGLAB_DEFAULT_RETRIEVAL_MODE", raising=False)
    monkeypatch.delenv("RAGLAB_DEFAULT_RERANK", raising=False)
    monkeypatch.delenv("RAGLAB_CITATION_RESOLVER", raising=False)
    monkeypatch.delenv("RAGLAB_VERSIONS_DEFAULT", raising=False)
    monkeypatch.delenv("RAGLAB_QUERY_TRANSLATION", raising=False)
    monkeypatch.delenv("RAGLAB_ROUTING_CROSS_LANGUAGE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.default_retrieval_mode == "hybrid"
    assert settings.default_rerank is True
    assert settings.citation_resolver is True
    # Measured in versions-full-v1 (9.10): versions set Recall@5 0.75 -> 0.93.
    assert settings.versions_default == "in_force"
    # Measured in lexml-fr-qt-v1: French questions on LexML Recall@5 0.790 -> 0.890.
    assert settings.query_translation is True
    # router-crosslang-m02-v1: French questions on LexML answered 33 -> 75 of 100.
    assert settings.routing_cross_language is True
    assert settings.routing_translation_margin == 0.02


def test_shipped_writer_is_qwen36_on_llamacpp_with_an_ollama_fallback(monkeypatch):
    monkeypatch.delenv("RAGLAB_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("RAGLAB_DEFAULT_LLM_PROVIDER", raising=False)
    settings = Settings(_env_file=None)
    # gen-qwen36-v1: answer correctness PIAF 0.763 -> 0.935, LexML 0.550 -> 0.710.
    assert settings.default_llm_provider == "llamacpp"
    assert settings.writer_model_profile == "qwen35b-moe-rag"
    assert settings.writer_model == "qwen3.6-35b-a3b"
    assert settings.llm_fallback_provider == "ollama"
    assert settings.generation_model == "qwen2.5:7b"
    assert settings.llamacpp_autostart is True
