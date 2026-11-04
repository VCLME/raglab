from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import requests

from raglab.config import Settings
from raglab.lexml.br_expat import NORMS, BrExpatCollector, Norm, extract_receita_text

DECREE_PAGE = """<html><body>
<p>Presidência da República<br>Casa Civil</p>
<p align="center">DECRETO Nº 9.199, DE 20 DE NOVEMBRO DE 2017</p>
<p>Art. 20. O visto de visita terá prazo de estada de até noventa dias.</p>
<p><strike>§ 1º Redação antiga.</strike></p>
<p>§ 1º A contagem do prazo será suspensa. (Redação dada pelo Decreto nº 1, de 2020)</p>
</body></html>"""

RECEITA_PAYLOAD = {
    "epigrafeCompleta": "Instrução Normativa SRF nº 208, de 27 de setembro de 2002",
    "ementas": [
        {"ordemSegmentoAto": 1, "textoIntegra": "Dispõe sobre a tributação.", "omitir": False, "tachado": False}
    ],
    "outrosSegmentos": [
        {"ordemSegmentoAto": 3, "textoIntegra": "I - que resida no Brasil;", "omitir": False, "tachado": False},
        {
            "ordemSegmentoAto": 2,
            "textoIntegra": "Art. 2<strike>º</strike> Considera-se residente:",
            "omitir": False,
            "tachado": False,
        },
        {"ordemSegmentoAto": 4, "textoIntegra": "II - redação superada;", "omitir": True, "tachado": False},
    ],
}

DECREE = Norm(
    "decreto_9199_2017",
    "decreto",
    "9199",
    2017,
    "2017-11-20",
    "Decreto nº 9.199",
    "immigration",
    "planalto",
    "d9199.htm",
)
INSTRUCTION = Norm(
    "in_srf_208_2002", "in", "208", 2002, "2002-09-27", "IN SRF nº 208", "personal_tax", "receita", receita_id=15079
)


def test_receita_text_keeps_current_segments_in_order_and_ordinals():
    text = extract_receita_text(RECEITA_PAYLOAD)
    assert text.split("\n") == [
        "Instrução Normativa SRF nº 208, de 27 de setembro de 2002",
        "Dispõe sobre a tributação.",
        "Art. 2º Considera-se residente:",  # the <strike> around the ordinal is display only
        "I - que resida no Brasil;",
    ]


def test_norms_have_unique_keys_and_resolver_numbers():
    assert len({norm.key for norm in NORMS}) == len(NORMS) == 19
    assert all(norm.number.isdigit() for norm in NORMS)
    assert (
        next(norm for norm in NORMS if norm.key == "lc_116_2003").urn
        == "urn:lex:br:federal:lei.complementar:2003-07-31;116"
    )


def _response(content: bytes) -> MagicMock:
    response = MagicMock()
    response.content = content
    response.raise_for_status.return_value = None
    return response


def _collector(tmp_path: Path, get) -> BrExpatCollector:
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = get
    return BrExpatCollector(Settings(data_dir=tmp_path / "data"), session=session, sleep=lambda _: None)


def test_collect_writes_texts_sidecars_and_reports_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("raglab.lexml.br_expat.NORMS", (DECREE, INSTRUCTION))

    def get(url, timeout):
        if "receita" in url:
            raise requests.ConnectionError("down")
        return _response(DECREE_PAGE.encode("utf-8"))

    result = _collector(tmp_path, get).collect(output_dir=tmp_path / "br_expat")

    assert result["documents"] == 1
    assert [row["key"] for row in result["missing"]] == ["in_srf_208_2002"]
    corpus = tmp_path / "br_expat" / "corpus"
    text = (corpus / "decreto_9199_2017.txt").read_text(encoding="utf-8")
    assert text.startswith("DECRETO Nº 9.199")  # masthead dropped with the decree heading
    assert "Redação antiga" not in text and "(Redação dada pelo Decreto nº 1, de 2020)" in text
    sidecar = json.loads((corpus / "decreto_9199_2017.json").read_text(encoding="utf-8"))
    assert sidecar["number"] == "9199" and sidecar["kind"] == "decreto" and sidecar["language"] == "pt"
    manifest = json.loads((tmp_path / "br_expat" / "manifest.json").read_text(encoding="utf-8"))
    assert [row["file_name"] for row in manifest["documents"]] == ["decreto_9199_2017.txt"]


def test_collect_reads_the_raw_cache_without_requests(tmp_path, monkeypatch):
    monkeypatch.setattr("raglab.lexml.br_expat.NORMS", (INSTRUCTION,))
    calls = []

    def get(url, timeout):
        calls.append(url)
        return _response(json.dumps(RECEITA_PAYLOAD).encode("utf-8"))

    collector = _collector(tmp_path, get)
    collector.collect(output_dir=tmp_path / "br_expat")
    collector.collect(output_dir=tmp_path / "br_expat")

    assert calls == ["https://normasinternet2.receita.fazenda.gov.br/api/consulta-externa/ato/15079/visao/vigente"]
