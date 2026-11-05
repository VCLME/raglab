"""Build benchmarks/br_expat/evidence_v1.jsonl from the frozen set's provision spans.

First proposal, not a human annotation: the provision spans checked by hand
when the set was built are grouped by text. All the spans of one law or
decree form a group (cumulatively needed); two texts giving the same rule
are alternatives (Q4: the offence and the amount, in Decreto 9.199 or in
Lei 13.445). Rows are marked `annotation: "auto-by-file"`, `reviewed_by:
null`: a human must confirm or split the groups before the "complete" level
is published as a result. The frozen ground truth is not modified.

    python scripts/br_expat_evidence.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "benchmarks" / "br_expat" / "ground_truth.jsonl"
TARGET = ROOT / "benchmarks" / "br_expat" / "evidence_v1.jsonl"


def main() -> None:
    lines = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        spans = (row.get("context") or {}).get("provision_spans") or []
        groups: dict[str, list[dict]] = {}
        for span in spans:
            groups.setdefault(span["file_name"], []).append(span)
        lines.append(
            {
                "id": row["id"],
                "groups": [{"label": name, "spans": items} for name, items in groups.items()],
                "annotation": "auto-by-file",
                "reviewed_by": None,
                "note": "one group per text: every span of a text is needed; texts are alternatives (unreviewed)",
            }
        )
    TARGET.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n", encoding="utf-8")
    print(
        f"{TARGET.relative_to(ROOT)}: {len(lines)} questions, {sum(1 for item in lines if item['groups'])} with evidence"
    )


if __name__ == "__main__":
    main()
