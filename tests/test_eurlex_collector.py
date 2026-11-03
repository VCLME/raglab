from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eurlex_fixtures import consolidated_act, consolidated_paragraph, oj_act, oj_paragraph
from raglab.eurlex.cellar import Download
from raglab.eurlex.collector import EurlexCollector
from raglab.eurlex.graph_eval import corpus_payload, draw_sample, precision_report
from raglab.graph.structure import DocumentRow, resolve_profile

DORA = "32022R2554"
RTS = "32024R1774"


def _dora() -> str:
    return oj_act(
        title="REGULATION (EU) 2022/2554",
        date="27.12.2022",
        citations=[
            "Having regard to the Treaty on the Functioning of the European Union, and in particular Article 114"
        ],
        recitals=[
            "Financial entities should manage ICT third-party risk as laid down in Article 28 of this Regulation."
        ],
        articles=[
            (
                "28",
                "Article 28",
                "General principles",
                oj_paragraph("1", "Financial entities shall manage ICT third-party risk in line with Article 30."),
            ),
            (
                "30",
                "Article 30",
                "Key contractual provisions",
                oj_paragraph("1", "The rights and obligations shall be clearly allocated and set out in writing."),
            ),
        ],
    )


def _dora_consolidated() -> str:
    return consolidated_act(
        [
            (
                "28",
                "Article 28",
                "General principles",
                consolidated_paragraph(
                    "1", "Financial entities shall manage ICT third-party risk in line with Article 30."
                ),
                None,
            ),
            (
                "30",
                "Article 30",
                "Key contractual provisions",
                consolidated_paragraph(
                    "1", "The rights and obligations shall be clearly allocated and set out in a written contract."
                ),
                "32022R2554R(01): REPLACED",
            ),
        ]
    )


def _rts() -> str:
    return oj_act(
        title="COMMISSION DELEGATED REGULATION (EU) 2024/1774",
        date="25.6.2024",
        citations=[
            "Having regard to Regulation (EU) 2022/2554 of the European Parliament and of the Council amending "
            "Regulations (EC) No 1060/2009 and (EU) 2016/1011, and in particular Article 28(10), third subparagraph, thereof,"
        ],
        recitals=["Article 28 of Regulation (EU) 2022/2554 requires a policy."],
        articles=[
            (
                "1",
                "Article 1",
                "Policy",
                oj_paragraph(
                    "1", "The policy referred to in Article 28(2) of Regulation (EU) 2022/2554 shall cover Article 30."
                ),
            ),
        ],
    )


class FakeCellar:
    """Serves the fixtures, like CellarClient would from its cache."""

    def __init__(self, root: Path, files: dict[tuple[str, str], str]) -> None:
        self.root = root
        self.files = files
        self.calls: list[tuple[str, str]] = []

    def fetch(self, celex: str, language: str, *, missing_ok: bool = False) -> Download | None:
        self.calls.append((celex, language))
        markup = self.files.get((celex, language))
        if markup is None:
            assert missing_ok
            return None
        path = self.root / f"{celex}.{language}.xhtml"
        path.write_text(markup, encoding="utf-8")
        return Download(celex, language, path, None, hashlib.sha256(markup.encode()).hexdigest(), cached=True)


def _collect(tmp_path: Path) -> dict:
    files = {
        (DORA, "en"): _dora(),
        ("02022R2554-20221227", "en"): _dora_consolidated(),
        (RTS, "en"): _rts(),
    }
    (tmp_path / "raw").mkdir()
    client = FakeCellar(tmp_path / "raw", files)
    return EurlexCollector(client=client).collect(
        acts=["dora", "dora_rts_ict_risk"], languages=["en"], output_dir=tmp_path
    )


def _sidecar(tmp_path: Path, name: str) -> dict:
    return json.loads((tmp_path / "corpus" / name).with_suffix(".json").read_text(encoding="utf-8"))


def test_one_document_per_unit_language_and_version(tmp_path: Path):
    result = _collect(tmp_path)
    names = sorted(path.name for path in (tmp_path / "corpus").glob("*.txt"))
    assert names == [
        "dora_en_art028_oj.txt",
        "dora_en_art030_c20221227.txt",
        "dora_en_art030_oj.txt",
        "dora_en_rct001_oj.txt",
        "dora_rts_ict_risk_en_art001_oj.txt",
        "dora_rts_ict_risk_en_rct001_oj.txt",
    ]
    assert result["documents"] == 6
    text = (tmp_path / "corpus" / "dora_en_art030_c20221227.txt").read_text(encoding="utf-8")
    assert text.splitlines()[:2] == ["Regulation (EU) 2022/2554 (DORA) — Article 30", "Key contractual provisions"]

    old, new = _sidecar(tmp_path, "dora_en_art030_oj"), _sidecar(tmp_path, "dora_en_art030_c20221227")
    assert (old["in_force"], old["valid_from"], old["valid_to"], old["version_kind"]) == (
        False,
        "2022-12-27",
        "2022-12-27",
        "original",
    )
    assert (new["in_force"], new["version"], new["version_count"], new["version_kind"]) == (True, 2, 2, "corrigendum")
    assert new["amended_by"] == [{"celex": "32022R2554R(01)", "actions": ["replaced"]}]
    assert new["unit_key"] == f"{DORA}:article:30" and new["consolidation_date"] == "2022-12-27"
    # Unchanged by the consolidation: one version only.
    assert _sidecar(tmp_path, "dora_en_art028_oj")["version_count"] == 1


def test_references_legal_basis_and_inferred_base(tmp_path: Path):
    _collect(tmp_path)
    rts = _sidecar(tmp_path, "dora_rts_ict_risk_en_art001_oj")
    assert rts["legal_basis"][0]["celex"] == DORA and rts["legal_basis"][0]["articles"] == ["28"]
    refs = [(ref["number"], ref["celex"], ref["scope"]) for ref in rts["references"]]
    # "Article 30" alone: the RTS has no Article 30, its base act has one.
    assert refs == [("28", DORA, "other_act"), ("30", DORA, "inferred")]
    recital = _sidecar(tmp_path, "dora_en_rct001_oj")
    assert recital["references"][0]["celex"] == DORA and recital["references"][0]["scope"] == "same_act"


def test_manifest_and_stats(tmp_path: Path):
    _collect(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [row["file_name"] for row in manifest["documents"]] == sorted(
        row["file_name"] for row in manifest["documents"]
    )
    assert {"celex": "02024R1774-20240625", "language": "en", "missing": True, "bytes": 0} in manifest["downloads"]
    assert manifest["rules_version"] >= 3
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["by_act"]["dora"]["units"] == {"recital": 1, "article": 2, "annex": 0}
    assert stats["references_in_force"]["in_corpus_pairs"]["article->article:across_acts"] == 2
    assert stats["references_in_force"]["recital_to_article_links"] == 1


def test_eu_graph_from_the_corpus_files(tmp_path: Path):
    _collect(tmp_path)
    payload, documents = corpus_payload(tmp_path / "corpus")
    assert payload.profile == "eu_acts"
    assert {row["celex"] for row in payload.nodes["Act"] if not row["external"]} == {DORA, RTS}
    articles = {row["uid"]: row for row in payload.nodes["Article"]}

    def name(uid: str) -> str:
        row = articles.get(uid)
        return f"{row['celex']}:{row['number']}:v{row['version']}" if row else uid

    cites = {
        (name(edge["source"]), name(edge["target"])) for edge in payload.relationships[("CITES", "Article", "Article")]
    }
    # The version in force of Article 30 is cited, not the corrected one.
    assert cites == {
        (f"{DORA}:28:v1", f"{DORA}:30:v2"),
        (f"{RTS}:1:v1", f"{DORA}:28:v1"),
        (f"{RTS}:1:v1", f"{DORA}:30:v2"),
    }
    explains = payload.relationships[("EXPLAINS", "Recital", "Article")]
    assert [name(edge["target"]) for edge in explains] == [f"{DORA}:28:v1"]
    supplements = payload.relationships[("SUPPLEMENTS", "Act", "Article")]
    assert [(edge["source"].rsplit(":", 1)[1], name(edge["target"])) for edge in supplements] == [
        (RTS, f"{DORA}:28:v1")
    ]
    # Chunks are part of their unit; the unit of its act.
    assert len(payload.relationships[("PART_OF", "Chunk", "Article")]) == 4

    sample = draw_sample(payload, documents, seed=1)
    assert {item["group"] for item in sample["items"]} >= {
        "CITES_within_act",
        "CITES_across_acts",
        "EXPLAINS",
        "SUPPLEMENTS",
    }
    for item in sample["items"]:
        item["verdict"] = "correct"
    report = precision_report(sample)
    assert report["precision"] == 1.0 and report["reviewed"] == len(sample["items"])


def test_auto_profile_picks_eu_acts():
    metadata = {"celex": DORA, "unit": "article", "unit_number": "1"}
    documents = [DocumentRow(id=str(i), file_name=f"{i}.txt", content="Article 1", metadata=metadata) for i in range(3)]
    assert resolve_profile("auto", documents) == "eu_acts"
    assert resolve_profile("auto", [DocumentRow("1", "a.txt", "texte", {})]) == "generic"
