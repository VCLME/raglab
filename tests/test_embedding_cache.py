from __future__ import annotations

import pytest

from raglab.config import Settings
from raglab.embeddings.factory import build_embedding_provider, clear_embedding_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_embedding_cache()
    yield
    clear_embedding_cache()


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_same_configuration_reuses_the_loaded_provider():
    first = build_embedding_provider(_settings())
    assert build_embedding_provider(_settings()) is first


def test_different_model_or_prefix_gets_its_own_provider():
    base = build_embedding_provider(_settings())
    assert build_embedding_provider(_settings(embedding_model_name="intfloat/multilingual-e5-base")) is not base
    assert build_embedding_provider(_settings(query_prefix="")) is not base


def test_cache_can_be_disabled_to_reproduce_the_v0_baseline():
    settings = _settings(embedding_cache=False)
    assert build_embedding_provider(settings) is not build_embedding_provider(settings)
