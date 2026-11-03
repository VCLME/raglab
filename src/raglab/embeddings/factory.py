from threading import Lock

from raglab.config import Settings, get_settings
from raglab.embeddings.ollama_provider import OllamaEmbeddingProvider
from raglab.embeddings.transformers_provider import TransformersEmbeddingProvider

# Providers load their model lazily and keep it in memory. Building a new one
# per query reloaded the transformers weights from disk on every request;
# reusing one per configuration keeps the model resident.
_CACHE: dict[tuple, object] = {}
_CACHE_LOCK = Lock()


def _cache_key(settings: Settings) -> tuple:
    return (
        settings.embedding_provider,
        settings.embedding_model_name,
        settings.embedding_dimension,
        settings.embedding_device,
        settings.embedding_max_tokens,
        settings.query_prefix,
        settings.passage_prefix,
        settings.ollama_base_url,
    )


def _create(settings: Settings):
    if settings.embedding_provider == "transformers":
        return TransformersEmbeddingProvider(settings)
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingProvider(settings)
    raise ValueError(f"Provider d'embeddings inconnu: {settings.embedding_provider}")


def build_embedding_provider(settings: Settings | None = None):
    resolved = settings or get_settings()
    if not resolved.embedding_cache:
        return _create(resolved)
    key = _cache_key(resolved)
    with _CACHE_LOCK:
        provider = _CACHE.get(key)
        if provider is None:
            provider = _create(resolved)
            _CACHE[key] = provider
    return provider


def clear_embedding_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
