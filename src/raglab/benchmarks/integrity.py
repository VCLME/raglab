"""What a benchmark actually searches: the documents of its index run.

The frozen manifest pins the corpus files on disk (`verify_manifest`), but
retrieval reads the database. A document written there by a test (a
`pytest-of-…/a.txt` once joined the consumer-code corpus) or left by an
older ingestion would be searched without anyone noticing. Before each
suite, the documents that have chunks in the index run used are compared
with the manifest, through the disk files:

- every indexed file name is in the manifest, once (else `unexpected` or
  `duplicate`);
- every manifest file is indexed (else `missing`);
- each indexed document's checksum (sha256 of the file's bytes, as
  ingestion computes it) equals that of the frozen file on disk, itself
  checked against the manifest (else `changed`);
- the URN, when both the manifest and the document carry one, is the same
  (else `metadata`).

Any problem stops the measurement. The fingerprint (sha256 over the sorted
`file_name:checksum` lines) is recorded with the results.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import text

from raglab.ingestion.readers import compute_checksum


def indexed_documents(session: Any, index_run_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT d.file_name, d.checksum, d.metadata_json->>'urn' AS urn FROM documents d "
            "WHERE d.id IN (SELECT DISTINCT document_id FROM chunks WHERE index_run_id = :run)"
        ),
        {"run": index_run_id},
    ).all()
    return [{"file_name": row[0], "checksum": row[1], "urn": row[2]} for row in rows]


def check_documents(documents: list[dict[str, Any]], manifest_path: Path, corpus_dir: Path) -> dict[str, Any]:
    """Problems between the indexed documents and the frozen manifest."""
    manifest = {row["file_name"]: row for row in json.loads(manifest_path.read_text(encoding="utf-8"))["documents"]}
    counts = Counter(document["file_name"] for document in documents)
    problems: dict[str, list[str]] = {
        "unexpected": sorted(name for name in counts if name not in manifest),
        "duplicate": sorted(name for name, count in counts.items() if count > 1),
        "missing": sorted(name for name in manifest if name not in counts),
        "changed": [],
        "metadata": [],
    }
    for document in documents:
        name = document["file_name"]
        if name not in manifest:
            continue
        path = corpus_dir / name
        if not path.exists() or compute_checksum(path) != document["checksum"]:
            problems["changed"].append(name)
        frozen_urn = manifest[name].get("urn")
        if frozen_urn and document.get("urn") and frozen_urn != document["urn"]:
            problems["metadata"].append(name)
    problems["changed"].sort()
    problems["metadata"].sort()
    lines = sorted(f"{document['file_name']}:{document['checksum']}" for document in documents)
    return {
        "documents": len(documents),
        "manifest_documents": len(manifest),
        "fingerprint": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
        "problems": {key: value for key, value in problems.items() if value},
    }


def describe(check: dict[str, Any]) -> str:
    return "; ".join(f"{key}: {len(names)} (ex. {names[:3]})" for key, names in check["problems"].items())
