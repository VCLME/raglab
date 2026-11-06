from __future__ import annotations

import hashlib
import json

import pytest

from raglab.benchmarks.integrity import check_documents
from raglab.config import get_settings
from raglab.db import session as db_session
from raglab.ingestion.readers import compute_checksum


def _corpus(tmp_path, files: dict[str, str]):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    rows = []
    for name, body in files.items():
        (corpus / name).write_text(body, encoding="utf-8")
        rows.append(
            {"file_name": name, "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "urn": f"urn:{name}"}
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": rows}), encoding="utf-8")
    return corpus, manifest


def _indexed(corpus, name, **extra):
    return {"file_name": name, "checksum": compute_checksum(corpus / name), "urn": f"urn:{name}", **extra}


def test_the_indexed_documents_match_the_manifest(tmp_path):
    corpus, manifest = _corpus(tmp_path, {"a.txt": "Art. 1", "b.txt": "Art. 2"})
    check = check_documents([_indexed(corpus, "a.txt"), _indexed(corpus, "b.txt")], manifest, corpus)
    assert check["problems"] == {}
    assert check["documents"] == check["manifest_documents"] == 2
    assert len(check["fingerprint"]) == 64


def test_an_extra_missing_changed_or_relabelled_document_is_reported(tmp_path):
    corpus, manifest = _corpus(tmp_path, {"a.txt": "Art. 1", "b.txt": "Art. 2", "c.txt": "Art. 3"})
    documents = [
        _indexed(corpus, "a.txt"),
        _indexed(corpus, "a.txt"),  # indexed twice
        {"file_name": "b.txt", "checksum": "0" * 64, "urn": "urn:b.txt"},  # not the frozen file
        {"file_name": "pytest-a.txt", "checksum": "1" * 64, "urn": None},  # written by a test
    ]
    documents.append(_indexed(corpus, "a.txt", urn="urn:other"))
    check = check_documents(documents, manifest, corpus)
    problems = check["problems"]
    assert problems["unexpected"] == ["pytest-a.txt"]
    assert problems["duplicate"] == ["a.txt"]
    assert problems["missing"] == ["c.txt"]
    assert problems["changed"] == ["b.txt"]
    assert problems["metadata"] == ["a.txt"]


def test_a_document_whose_frozen_file_is_gone_counts_as_changed(tmp_path):
    corpus, manifest = _corpus(tmp_path, {"a.txt": "Art. 1"})
    document = _indexed(corpus, "a.txt")
    (corpus / "a.txt").unlink()
    assert check_documents([document], manifest, corpus)["problems"]["changed"] == ["a.txt"]


def test_the_test_suite_never_reaches_the_working_database(monkeypatch):
    """conftest points every test at a *_test database (or nowhere) and the
    engine refuses any other name."""
    assert get_settings().require_test_database is True
    assert get_settings().database_url.rsplit("/", 1)[-1].endswith("_test")
    monkeypatch.setenv("RAGLAB_DATABASE_URL", "postgresql+psycopg://raglab:raglab@localhost:5432/raglab")
    get_settings.cache_clear()
    db_session.reset_engine()
    with pytest.raises(RuntimeError, match="_test"):
        db_session.get_engine()
