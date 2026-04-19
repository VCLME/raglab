from __future__ import annotations

import pytest

from raglab.benchmarks import AVAILABLE_LOADERS, BenchmarkLoader, FQuADLoader, get_loader


def test_registry_exposes_fquad_loader():
    assert "fquad" in AVAILABLE_LOADERS
    assert AVAILABLE_LOADERS["fquad"] is FQuADLoader


def test_get_loader_returns_class_by_name():
    loader_cls = get_loader("fquad")
    assert loader_cls is FQuADLoader


def test_get_loader_raises_for_unknown_name():
    with pytest.raises(ValueError) as exc:
        get_loader("does_not_exist")
    assert "does_not_exist" in str(exc.value)
    assert "fquad" in str(exc.value)


def test_all_loaders_declare_required_metadata():
    for loader_cls in AVAILABLE_LOADERS.values():
        assert issubclass(loader_cls, BenchmarkLoader)
        assert loader_cls.name, f"{loader_cls.__name__} missing name"
        assert loader_cls.language, f"{loader_cls.__name__} missing language"
        assert loader_cls.licence, f"{loader_cls.__name__} missing licence"
        assert loader_cls.description, f"{loader_cls.__name__} missing description"
        assert loader_cls.default_corpus_name, f"{loader_cls.__name__} missing default_corpus_name"
