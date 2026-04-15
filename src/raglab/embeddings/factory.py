from raglab.config import Settings, get_settings
from raglab.embeddings.ollama_provider import OllamaEmbeddingProvider
from raglab.embeddings.transformers_provider import TransformersEmbeddingProvider


def build_embedding_provider(settings: Settings | None = None):
    resolved = settings or get_settings()
    if resolved.embedding_provider == "transformers":
        return TransformersEmbeddingProvider(resolved)
    if resolved.embedding_provider == "ollama":
        return OllamaEmbeddingProvider(resolved)
    raise ValueError(f"Provider d'embeddings inconnu: {resolved.embedding_provider}")
