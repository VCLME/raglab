import importlib
import json
from pathlib import Path

import pytest

from raglab.lexml import getDataFromLexML
from raglab.lexml.getDataFromLexML import GetDataFromLexMLService

SAMPLE_PAGE = """
<div class="results">
  <td class="docHit">
    <div id="main_1" class="docHit">
      <table>
        <tr><td class="col1"><b>1</b></td><td class="col2"><b>Localidade  </b></td><td class="col3">Brasil</td><td class="col4"> </td></tr>
        <tr><td class="col1"> </td><td class="col2"><b>Autoridade  </b></td><td class="col3">Senado Federal</td><td class="col4"> </td></tr>
        <tr><td class="col1"> </td><td class="col2"><b>Título  </b></td><td class="col3"><a href="/urn/urn:lex:br:federal:lei:1990-09-11;8078">Lei nº 8.078, de 11 de setembro de 1990</a></td><td class="col4"> </td></tr>
        <tr><td class="col1"> </td><td class="col2"><b>Data  </b></td><td class="col3">11/09/1990</td><td class="col4"> </td></tr>
        <tr><td class="col1"> </td><td class="col2"><b>Ementa  </b></td><td class="col3">Dispõe sobre a proteção do consumidor.</td><td class="col4"> </td></tr>
        <tr><td class="col1"> </td><td class="col2"><b>URN  </b></td><td class="col3">urn:lex:br:federal:lei:1990-09-11;8078</td><td class="col4"> </td></tr>
      </table>
    </div>
  </td>
</div>
"""


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, pages: list[bytes]):
        self.pages = pages
        self.calls = 0
        self.headers = {}

    def get(self, *args, **kwargs):
        if self.calls >= len(self.pages):
            raise AssertionError("Unexpected extra LexML request")
        page = self.pages[self.calls]
        self.calls += 1
        return FakeResponse(page)


def test_parse_search_page_extracts_expected_fields():
    service = GetDataFromLexMLService(session=FakeSession([]))
    records = service._parse_search_page(
        SAMPLE_PAGE,
        page_number=1,
        search_page_url="https://www.lexml.gov.br/busca/search?f1-tipoDocumento=Legislação",
    )
    assert len(records) == 1
    record = records[0]
    assert record.title == "Lei nº 8.078, de 11 de setembro de 1990"
    assert record.authority == "Senado Federal"
    assert record.urn == "urn:lex:br:federal:lei:1990-09-11;8078"
    assert record.resolution_url.endswith("/urn/urn:lex:br:federal:lei:1990-09-11;8078")


def test_get_data_from_lexml_skips_when_local_data_exists(tmp_path: Path):
    output_dir = tmp_path / "lexml"
    output_dir.mkdir(parents=True)
    (output_dir / "existing.txt").write_text("already here", encoding="utf-8")

    summary = getDataFromLexML(output_dir=output_dir, session=FakeSession([]), page_limit=1)

    assert summary["status"] == "skipped"
    assert summary["downloaded_files"] == 0


def test_get_data_from_lexml_stops_when_download_limit_is_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_dir = tmp_path / "lexml"
    lexml_module = importlib.import_module("raglab.lexml.getDataFromLexML")
    monkeypatch.setattr(lexml_module, "MAX_LEXML_DOWNLOAD_BYTES", 10)
    session = FakeSession([SAMPLE_PAGE.encode("utf-8")])

    summary = getDataFromLexML(output_dir=output_dir, session=session, page_limit=1)

    assert summary["status"] == "limit_hit"
    assert summary["limit_hit"] is True
    assert not list(output_dir.glob("*.txt"))


def test_get_data_from_lexml_writes_text_and_metadata_files(tmp_path: Path):
    output_dir = tmp_path / "lexml"
    session = FakeSession([SAMPLE_PAGE.encode("utf-8")])

    summary = getDataFromLexML(output_dir=output_dir, session=session, page_limit=1)

    text_files = list(output_dir.glob("*.txt"))
    metadata_files = list(output_dir.glob("*.json"))
    assert summary["status"] == "completed"
    assert summary["downloaded_files"] == 1
    assert len(text_files) == 1
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert metadata["urn"] == "urn:lex:br:federal:lei:1990-09-11;8078"
