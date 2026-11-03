from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from raglab.lexml.fulltext import (
    FederalLaw,
    FullTextCollector,
    extract_planalto_text,
    planalto_candidate_urls,
)

PLANALTO_PAGE = """<html><head><title>L8078</title><style>p {}</style></head><body>
<p>Presidência da República<br>Casa Civil</p>
<p><a href="#">Texto compilado</a></p>
<p align="center">LEI Nº 8.078, DE 11 DE SETEMBRO DE 1990.</p>
<p>Dispõe sobre a proteção do consumidor e dá outras providências.</p>
<p><font>Art. 1° O presente código estabelece
normas de proteção.</font></p>
<p><strike>Art. 2° Texto revogado.</strike></p>
<p><span style="text-decoration: line-through">§ 1º Também revogado.</span></p>
<p>Art. 3° Fornecedor é toda pessoa física.
<p>Art. 4° Parágrafo sem fechamento.
</body></html>"""


def test_extract_keeps_body_drops_masthead_and_revoked_text():
    text = extract_planalto_text(PLANALTO_PAGE)
    lines = text.split("\n")
    assert lines[0] == "LEI Nº 8.078, DE 11 DE SETEMBRO DE 1990."
    assert "Art. 1° O presente código estabelece normas de proteção." in lines  # source wrap joined
    assert "revogado" not in text.lower()
    assert "Art. 3° Fornecedor é toda pessoa física." in lines
    assert "Art. 4° Parágrafo sem fechamento." in lines  # unclosed <p> does not swallow text
    assert "L8078" not in text  # <title>


def test_candidate_urls_follow_planalto_layouts():
    assert planalto_candidate_urls("8078", 1990)[0].endswith("/leis/l8078.htm")
    assert any(url.endswith("/leis/2003/l10.741.htm") for url in planalto_candidate_urls("10741", 2003))
    assert planalto_candidate_urls("14133", 2021) == [
        "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14133.htm"
    ]


def test_urn_and_stem():
    law = FederalLaw(number="8078", year=1990, signed_on="1990-09-11", title="Lei nº 8.078", ementa="")
    assert law.urn == "urn:lex:br:federal:lei:1990-09-11;8078"
    assert law.stem == "lei_8078_1990"


def _response(status: int = 200, *, json_payload=None, content: bytes = b"", url: str = ""):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = json_payload
    response.content = content
    response.url = url
    response.raise_for_status.return_value = None
    return response


def test_collect_keeps_laws_in_length_bounds_and_writes_manifest(tmp_path: Path):
    listing = {
        "ListaDocumento": {
            "documentos": {
                "documento": [
                    {"numero": "8078", "dataassinatura": "11/09/1990", "normaNome": "Lei nº 8.078", "ementa": "CDC"},
                    {"numero": "8001", "dataassinatura": "13/03/1990", "normaNome": "Lei nº 8.001", "ementa": "Curta"},
                ]
            }
        }
    }
    long_page = PLANALTO_PAGE.replace("Art. 3°", "Art. 3° " + "texto " * 200).encode("cp1252")
    short_page = b"<p>LEI N 8.001</p><p>Art. 1 Curta.</p>"

    session = MagicMock()
    session.headers = {}

    def fake_get(url, **kwargs):
        if "dadosabertos" in url:
            return _response(json_payload=listing)
        if "l8078" in url:
            return _response(content=long_page, url=url)
        return _response(content=short_page, url=url)

    session.get.side_effect = fake_get
    collector = FullTextCollector(session=session, delay_seconds=0, sleep=lambda _: None)
    result = collector.collect(output_dir=tmp_path, years=[1990], per_year=5, min_chars=500)

    assert result["documents"] == 1
    assert result["skipped"]["too_short"] == 1
    sidecar = json.loads((tmp_path / "corpus" / "lei_8078_1990.json").read_text(encoding="utf-8"))
    assert sidecar["urn"] == "urn:lex:br:federal:lei:1990-09-11;8078"
    assert "Fornecedor" in (tmp_path / "corpus" / "lei_8078_1990.txt").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [row["file_name"] for row in manifest["documents"]] == ["lei_8078_1990.txt"]
    assert len(manifest["documents"][0]["sha256"]) == 64
