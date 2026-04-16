import json

from raglab.document_metadata import build_document_metadata, normalize_tags


def test_normalize_tags_lowercases_and_deduplicates():
    assert normalize_tags([" LexML ", "justice", "lexml", "", "JUSTICE"]) == ["lexml", "justice"]


def test_build_document_metadata_merges_sidecar_and_tags(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    document_path = root / "law.txt"
    document_path.write_text("Conteudo legal", encoding="utf-8")
    (root / "law.json").write_text(
        json.dumps({"authority": "Senado Federal", "tags": ["Legal", "Brasil"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    metadata = build_document_metadata(document_path, root=root, extra_tags=["Urgent", "legal"])

    assert metadata["relative_path"] == "law.txt"
    assert metadata["authority"] == "Senado Federal"
    assert metadata["tags"] == ["legal", "brasil", "urgent"]
    assert metadata["metadata_sidecar_path"] == "law.json"
    assert metadata["size_bytes"] > 0


def test_build_document_metadata_without_sidecar_keeps_base_fields(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    document_path = root / "note.txt"
    document_path.write_text("texte", encoding="utf-8")

    metadata = build_document_metadata(document_path, root=root, extra_tags=None)

    assert metadata == {
        "relative_path": "note.txt",
        "size_bytes": 5,
        "tags": [],
    }
