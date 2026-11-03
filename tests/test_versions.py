"""Version awareness (phase 9.10): rules, dates read from questions,
compiled-law markers, the service option, the prompt and the metric."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.dialects import postgresql
from typer.testing import CliRunner

import raglab.retrieval.service as service_module
from raglab.benchmarks.compare import compare_suite, render
from raglab.cli import app as cli_app
from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import ChunkVersion, RetrievedChunk
from raglab.domain.versions import (
    marker_version,
    metadata_version,
    parse_question_date,
    parse_versions_option,
    prompt_line,
    resolve_policy,
    strip_revoked,
    valid_at,
)
from raglab.experiments.metrics import answer_cites_outdated, outdated_hit_at_k
from raglab.experiments.recall import RecallBenchmarkCase, RecallBenchmarkService
from raglab.generation.prompts import build_context
from raglab.retrieval.citations import _version_rank
from raglab.retrieval.service import QueryService
from raglab.retrieval.stages import planned_stages, retrieval_stage_events
from raglab.retrieval.versions import annotate, demote_revoked
from raglab.stores.vector.postgres import valid_at_condition

TODAY = date(2026, 11, 3)

# The five versions of article L. 121-21 of the Code de la consommation:
# fourteen days to withdraw from a contract until 2016, then, under the same
# number, the ban on some debt-collection fees.
L121_21_VERSIONS = [
    {"legi_id": "LEGIARTI000006292081", "etat": "MODIFIE", "date_debut": "1993-07-27", "date_fin": "2014-06-14"},
    {"legi_id": "LEGIARTI000028747427", "etat": "MODIFIE", "date_debut": "2014-06-14", "date_fin": "2014-12-22"},
    {"legi_id": "LEGIARTI000029947703", "etat": "MODIFIE", "date_debut": "2014-12-22", "date_fin": "2015-08-08"},
    {"legi_id": "LEGIARTI000031012885", "etat": "ABROGE", "date_debut": "2015-08-08", "date_fin": "2016-07-01"},
    {"legi_id": "LEGIARTI000032227234", "etat": "VIGUEUR", "date_debut": "2016-07-01", "date_fin": None},
]


def _l121_21(position: int) -> dict:
    row = L121_21_VERSIONS[position]
    return {
        **row,
        "article_number": "L121-21",
        "article_label": "L121-21",
        "code": "consommation",
        "version_count": 5,
        "versions": L121_21_VERSIONS,
        "amended_by": {"title": "LOI n° 2015-990 du 6 août 2015"},
        "ended_by": {"title": "Ordonnance n° 2016-301 du 14 mars 2016"} if row["date_fin"] else None,
    }


# --- Option and dates --------------------------------------------------------


def test_versions_option_values():
    assert parse_versions_option(None) == (None, None)
    assert parse_versions_option("in_force") == ("in_force", None)
    assert parse_versions_option("ALL") == ("all", None)
    assert parse_versions_option("as_of=2015-03-01") == ("as_of", date(2015, 3, 1))
    assert parse_versions_option("as_of:2015-03-01") == ("as_of", date(2015, 3, 1))
    for bad in ("latest", "as_of=2015-13-01", "as_of=yesterday"):
        with pytest.raises(ValueError):
            parse_versions_option(bad)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        # fr
        ("Que prévoyait l'article L. 121-21 avant 2016 ?", date(2015, 12, 31)),
        ("Quel délai avant le 1er juillet 2016 ?", date(2016, 6, 30)),
        ("Dans sa rédaction de 2014, quel délai donnait l'article L. 121-21 ?", date(2014, 12, 31)),
        ("Quelle règle était en vigueur au 1er janvier 2015 ?", date(2015, 1, 1)),
        ("Dans sa version antérieure à 2016, que disait l'article ?", date(2015, 12, 31)),
        ("Avant la réforme de 2016, quel était le délai ?", date(2015, 12, 31)),
        ("À la date du 15/03/2015, que disait l'article ?", date(2015, 3, 15)),
        # pt
        ("Antes de 2016, qual era o prazo?", date(2015, 12, 31)),
        ("O que dizia o art. 49 da Lei nº 8.078, de 1990, na redação de 2010?", date(2010, 12, 31)),
        ("Qual regra era vigente em 1º de janeiro de 2012?", date(2012, 1, 1)),
        # en
        ("What did article L. 121-21 say as of 2015-03-01?", date(2015, 3, 1)),
        ("What was the rule before 2016?", date(2015, 12, 31)),
        ("What did it say as it stood on January 5, 2015?", date(2015, 1, 5)),
    ],
)
def test_question_dates_in_three_languages(question, expected):
    asked = parse_question_date(question, today=TODAY)
    assert asked is not None and asked.on == expected
    assert asked.phrase in question


@pytest.mark.parametrize(
    "question",
    [
        "Que dit l'article L. 221-18 du code de la consommation ?",
        # The date of a text names it; it does not ask about the past.
        "Quel délai prévoit la loi n° 2014-344 du 17 mars 2014 ?",
        "O que dispõe o art. 49 da Lei nº 8.078, de 1990?",
        "Que prévoit l'ordonnance n° 2016-301 ?",
        # A future date is not a past version.
        "Quelle règle sera en vigueur en 2030 ?",
    ],
)
def test_questions_without_a_reference_date(question):
    assert parse_question_date(question, today=TODAY) is None


def test_policy_resolution():
    default = resolve_policy(None, "Quel délai ?", today=TODAY)
    assert (default.mode, default.on, default.source) == ("in_force", TODAY, "default")
    asked = resolve_policy(None, "Quel délai avant 2016 ?", today=TODAY)
    assert (asked.mode, asked.on, asked.source, asked.phrase) == ("as_of", date(2015, 12, 31), "question", "avant 2016")
    # An explicit date wins over the question; `all` reads no date at all.
    explicit = resolve_policy("as_of=2010-01-01", "Quel délai avant 2016 ?", today=TODAY)
    assert (explicit.mode, explicit.on, explicit.source) == ("as_of", date(2010, 1, 1), "request")
    naive = resolve_policy("all", "Quel délai avant 2016 ?", today=TODAY)
    assert (naive.mode, naive.on, naive.filters) == ("all", None, False)
    assert resolve_policy(None, "q", default_mode="all", today=TODAY).mode == "all"


# --- Validity from metadata -------------------------------------------------


def test_validity_follows_the_dates_not_the_frozen_state():
    assert valid_at(_l121_21(4), TODAY)
    assert not valid_at(_l121_21(3), TODAY)
    assert valid_at(_l121_21(1), date(2014, 7, 1))
    # date_fin is exclusive: the new version starts that day.
    assert not valid_at(_l121_21(3), date(2016, 7, 1))
    assert valid_at({"etat": "ABROGE_DIFF", "date_debut": "2020-01-01", "date_fin": "2027-01-01"}, TODAY)
    assert not valid_at({"etat": "VIGUEUR_DIFF", "date_debut": "2027-01-01", "date_fin": None}, TODAY)
    assert not valid_at({"etat": "ANNULE", "date_debut": "2000-01-01", "date_fin": None}, TODAY)


def test_sql_filter_lets_unversioned_documents_through():
    sql = str(valid_at_condition("2015-12-31").compile(dialect=postgresql.dialect()))
    assert "NOT ((documents.metadata_json ? %(metadata_json_1)s))" in sql
    assert "->> %(metadata_json_" in sql
    assert "IS NULL" in sql


def test_metadata_version_says_what_replaced_it():
    old = metadata_version(_l121_21(3), TODAY)
    assert (old.in_force, old.etat, old.date_fin) == (False, "ABROGE", "2016-07-01")
    assert old.replaced_by == {"legi_id": "LEGIARTI000032227234", "date_debut": "2016-07-01"}
    assert old.in_force_version == "LEGIARTI000032227234"
    assert old.ended_by == "Ordonnance n° 2016-301 du 14 mars 2016"
    current = metadata_version(_l121_21(4), TODAY)
    assert current.in_force and current.replaced_by is None and current.in_force_version is None
    # On a past date, the 2014 version is the one in force.
    assert metadata_version(_l121_21(2), date(2015, 1, 1)).in_force


def test_cited_article_resolves_to_the_version_of_the_date():
    rows = [_l121_21(position) for position in range(5)]
    assert max(rows, key=lambda row: _version_rank(row))["legi_id"] == "LEGIARTI000032227234"
    on_2014 = max(rows, key=lambda row: _version_rank(row, date(2014, 12, 31)))
    assert on_2014["legi_id"] == "LEGIARTI000029947703"


# --- LexML markers ----------------------------------------------------------

LEXML_REVOKED = "(Revogado pela Lei nº 11.907, de 2009)\n(Revogado pela Lei nº 11.907, de 2009)"
LEXML_MIXED = (
    "Art. 2º A GDATFA será atribuída em função das metas. (Redação dada pela Lei nº 11.907, de 2009)\n"
    "§ 2º É vedada a inclusão de matrículas já computadas. (Revogado pela Lei nº 14.284, de 2021)\n"
    "§ 3º A GDATFA será paga observado o limite de 100 pontos."
)


def test_markers_of_compiled_laws():
    assert marker_version("Art. 1º Esta Lei dispõe sobre o consumidor.") is None
    revoked = marker_version(LEXML_REVOKED)
    assert revoked is not None and revoked.revoked_only and revoked.in_force is False
    mixed = marker_version(LEXML_MIXED)
    assert mixed is not None and not mixed.revoked_only and mixed.in_force
    assert (mixed.revoked_lines, mixed.rewritten_lines, mixed.last_amended_year) == (1, 1, 2009)
    assert mixed.amended_by == "Redação dada pela Lei nº 11.907, de 2009"
    assert "Revogado pela Lei nº 14.284, de 2021" in mixed.markers
    # "(Vide ...)" and "(Incluído ...)" are not repeals.
    assert marker_version("I - até 20 pontos (Incluído pela Lei nº 11.907, de 2009) (Vide Lei nº 13.043)") is None


def test_repealed_wording_is_not_shown_to_the_model():
    stripped = strip_revoked(LEXML_MIXED)
    assert "É vedada" not in stripped
    assert "§ 2º [disposition abrogée : Revogado pela Lei nº 14.284, de 2021]" in stripped
    assert "Art. 2º A GDATFA será atribuída" in stripped


def _chunk(chunk_id: str, rank: int, text: str = "texte", **extra) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        file_name=f"{chunk_id}.txt",
        source_path=f"/data/{chunk_id}.txt",
        chunk_text=text,
        score=1.0 - rank / 10,
        rank=rank,
        **extra,
    )


def test_revoked_only_chunks_move_last_but_a_cited_article_stays():
    policy = resolve_policy(None, "q", today=TODAY)
    chunks = annotate(
        [
            _chunk("a", 1, LEXML_REVOKED),
            _chunk("b", 2, LEXML_MIXED),
            _chunk("c", 3, LEXML_REVOKED, citation_match=True),
            _chunk("d", 4, "Art. 5º Texto em vigor."),
        ],
        policy,
        {},
    )
    ordered, moved = demote_revoked(chunks)
    assert moved == 1
    assert [chunk.chunk_id for chunk in ordered] == ["b", "c", "d", "a"]
    assert [chunk.rank for chunk in ordered] == [1, 2, 3, 4]
    assert ordered[-1].version.demoted


# --- Prompt -----------------------------------------------------------------


def test_prompt_tells_the_model_the_version_state():
    current = prompt_line(metadata_version(_l121_21(4), TODAY))
    assert current == "Statut : version de l'article L121-21 en vigueur depuis le 1er juillet 2016."
    old = prompt_line(metadata_version(_l121_21(3), TODAY))
    assert "ancienne version de l'article L121-21 (du 8 août 2015 au 1er juillet 2016)" in old
    assert "plus en vigueur" in old
    repealed = prompt_line(
        ChunkVersion(source="metadata", etat="ABROGE", in_force=False, date_fin="2016-07-01", article="L121-25")
    )
    assert repealed == "Statut : version de l'article L121-25 abrogée le 1er juillet 2016 — plus en vigueur."
    past = prompt_line(metadata_version(_l121_21(2), date(2015, 1, 1)))
    assert "(à la date du 1er janvier 2015)" in past


def test_context_carries_the_status_except_for_the_naive_baseline():
    metadata = {"doc-old": _l121_21(3)}
    chunk = _chunk("old", 1, "Le consommateur dispose d'un délai de quatorze jours.")
    in_force = annotate([chunk], resolve_policy(None, "q", today=TODAY), metadata)
    assert "Statut : ancienne version" in build_context(in_force)
    naive = annotate([chunk], resolve_policy("all", "q", today=TODAY), metadata)
    assert naive[0].version is not None and not naive[0].version.in_prompt
    assert "Statut" not in build_context(naive)
    markers = annotate([_chunk("law", 1, LEXML_MIXED)], resolve_policy(None, "q", today=TODAY), {})
    context = build_context(markers)
    assert "É vedada" not in context and "disposition(s) abrogée(s)" in context


# --- Service ----------------------------------------------------------------


class FakeLookup:
    def __init__(self, history: bool, metadata: dict[str, dict]):
        self.history = history
        self.documents = metadata

    def has_history(self, index_run):
        return self.history

    def metadata(self, document_ids):
        return {
            document_id: self.documents[document_id] for document_id in document_ids if document_id in self.documents
        }


def _service(lookup: FakeLookup, chunks: list[RetrievedChunk]) -> QueryService:
    service = QueryService(Mock(), Settings())
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(id="run-1", corpus_id="corpus-1", strategy=ChunkingStrategy.TRADITIONAL.value)
    )
    service._embed_question = Mock(return_value=[0.1, 0.2])
    service.vector_store = Mock()
    service.vector_store.search.return_value = chunks
    service.version_lookup = lookup
    return service


def test_in_force_filters_out_versions_before_ranking_and_tags_chunks():
    service = _service(FakeLookup(True, {"doc-new": _l121_21(4)}), [_chunk("new", 1)])
    response = service.query(question="Que dit l'article L. 121-21 ?", corpus_name="legi", generate_answer=False)

    filters = service.vector_store.search.call_args.kwargs["filters"]
    assert filters.valid_at == date.today().isoformat()
    assert response.versions["mode"] == "in_force" and response.versions["filtered"]
    assert response.versions["scope"] == "metadata"
    assert response.retrieved_chunks[0].version.etat == "VIGUEUR"
    assert "versions" in response.timings_ms


def test_a_question_about_the_past_searches_the_versions_of_that_date(monkeypatch):
    found = Mock(return_value=None)
    monkeypatch.setattr(service_module, "find_code_article", found)
    service = _service(FakeLookup(True, {}), [])
    response = service.query(
        question="Que prévoyait l'article L. 121-21 du code de la consommation avant 2016 ?",
        corpus_name="legi",
        generate_answer=False,
        citations=True,
    )

    assert service.vector_store.search.call_args.kwargs["filters"].valid_at == "2015-12-31"
    assert found.call_args.kwargs["on"] == date(2015, 12, 31)
    assert response.versions == {
        "mode": "as_of",
        "date": "2015-12-31",
        "source": "question",
        "phrase": "avant 2016",
        "scope": "metadata",
        "filtered": True,
        "demoted": 0,
        "outdated": 0,
    }


def test_all_keeps_every_version_and_counts_the_outdated_ones():
    service = _service(
        FakeLookup(True, {"doc-old": _l121_21(3), "doc-new": _l121_21(4)}), [_chunk("old", 1), _chunk("new", 2)]
    )
    response = service.query(question="q", corpus_name="legi", generate_answer=False, versions="all")

    assert service.vector_store.search.call_args.kwargs["filters"] is None
    assert (response.versions["mode"], response.versions["filtered"], response.versions["outdated"]) == (
        "all",
        False,
        1,
    )


def test_corpus_without_versions_is_untouched():
    service = _service(FakeLookup(False, {}), [_chunk("piaf", 1, "Paris est la capitale.")])
    response = service.query(question="q", corpus_name="piaf", generate_answer=False)

    assert service.vector_store.search.call_args.kwargs["filters"] is None
    assert response.versions["scope"] == "none"
    assert "versions" not in response.timings_ms
    assert response.retrieved_chunks[0].version is None


def test_learning_mode_shows_the_versions_stage_on_compiled_laws():
    service = _service(FakeLookup(False, {}), [_chunk("a", 1, LEXML_REVOKED), _chunk("b", 2, LEXML_MIXED)])
    outcome = service.retrieve(question="q", corpus_name="lexml")

    assert [chunk.chunk_id for chunk in outcome.retrieved] == ["b", "a"]
    assert outcome.versions["scope"] == "markers" and outcome.versions["demoted"] == 1
    assert planned_stages(outcome, generate=False)[-1] == "versions"
    end = [event for event in retrieval_stage_events(outcome) if event["stage"] == "versions"][-1]
    assert end["counts"]["demoted"] == 1
    assert end["data"]["policy"]["mode"] == "in_force"
    assert end["data"]["top_chunks"][1]["version"]["revoked_only"] is True


def test_past_date_on_compiled_laws_says_it_cannot_be_honoured():
    service = _service(FakeLookup(False, {}), [_chunk("b", 1, LEXML_MIXED)])
    outcome = service.retrieve(question="Antes de 2016, qual era a regra?", corpus_name="lexml")
    assert outcome.versions["notice"] == "markers_no_history"


# --- API / CLI ----------------------------------------------------------------


def test_api_rejects_an_invalid_versions_option():
    from fastapi.testclient import TestClient

    from raglab.api.main import app

    with TestClient(app) as client:
        response = client.post("/api/query", json={"question": "q", "versions": "latest"})
    assert response.status_code == 422


def test_cli_rejects_an_invalid_versions_option():
    result = CliRunner().invoke(cli_app, ["query", "q", "--corpus", "c", "--versions", "latest"])
    assert result.exit_code != 0
    assert "versions" in result.output.lower()


def test_recall_endpoint_and_cli_forward_the_versions_option():
    from fastapi.testclient import TestClient

    from raglab.api.deps import get_db
    from raglab.api.main import app

    app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
    try:
        with (
            patch("raglab.api.routers.experiments.RecallBenchmarkService") as api_cls,
            TestClient(app) as client,
        ):
            api_cls.return_value.run.return_value = {"ok": True}
            response = client.post(
                "/api/experiments/recall", json={"corpus": "legi", "strategy": "traditional", "versions": "all"}
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert api_cls.return_value.run.call_args.kwargs["versions"] == "all"

    with patch("raglab.cli.RecallBenchmarkService") as cli_cls, patch("raglab.cli.session_scope") as scope:
        scope.return_value.__enter__.return_value = MagicMock()
        cli_cls.return_value.run.return_value = {"ok": True}
        result = CliRunner().invoke(
            cli_app, ["experiment", "recall", "--corpus", "legi", "--strategy", "traditional", "--versions", "all"]
        )
    assert result.exit_code == 0, result.output
    assert cli_cls.return_value.run.call_args.kwargs["versions"] == "all"


# --- Metric -------------------------------------------------------------------


def test_outdated_hit_means_an_outdated_version_above_the_answer():
    assert outdated_hit_at_k([False, True], [True, False], 5)
    assert not outdated_hit_at_k([True, False], [False, True], 5)
    # The answer is missing from the top-k: any outdated version misleads.
    assert outdated_hit_at_k([False, False], [False, True], 5)
    assert not outdated_hit_at_k([False] * 6, [False] * 5 + [True], 5)


def test_answer_citing_the_outdated_version():
    trap = {"answer": "sept jours", "expected_answer": "quatorze jours", "article": "L121-20"}
    assert answer_cites_outdated("Le consommateur dispose de sept jours [Rank 1].", trap)
    assert not answer_cites_outdated("Quatorze jours (et non plus sept jours) [Rank 1].", trap)
    moved = {"article": "L121-21"}
    assert answer_cites_outdated("Selon l'article L. 121-21, quatorze jours.", moved, "L221-18")
    assert not answer_cites_outdated("L'article L. 221-18 (ancien L. 121-21) donne quatorze jours.", moved, "L221-18")
    assert not answer_cites_outdated(None, trap)


def test_case_outdated_by_trap_or_by_date():
    trap_case = RecallBenchmarkCase("q1", "q", ["new.txt"], [], trap={"file_names": ["old.txt"]})
    assert trap_case.is_outdated({"file_name": "old.txt"})
    assert not trap_case.is_outdated({"file_name": "new.txt", "version": {"source": "metadata", "in_force": False}})
    dated = RecallBenchmarkCase("q2", "q", ["v3.txt"], [], context={"as_of": "2015-01-01"})
    version = metadata_version(_l121_21(2), TODAY).model_dump()
    # Out of force today, in force on the date the question asks about.
    assert not dated.is_outdated({"file_name": "v3.txt", "version": version})
    assert RecallBenchmarkCase("q3", "q", [], []).is_outdated({"file_name": "v3.txt", "version": version})


class _RecordingQueryService:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls: list[dict] = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(retrieved_chunks=self.chunks, index_run_id="run-1", answer=None, timings_ms={})


def test_recall_benchmark_reports_outdated_hits(tmp_path):
    dataset = tmp_path / "ground_truth.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "v1",
                "question": "Quel délai pour se rétracter d'un contrat conclu à distance ?",
                "expected_file_names": ["new.txt"],
                "question_type": "moved",
                "trap": {"kind": "moved", "file_names": ["old.txt"], "article": "L121-21"},
                "context": {"article": "L221-18"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    service = RecallBenchmarkService(session=MagicMock(), settings=Settings(reports_dir=tmp_path))
    service.query_service = _RecordingQueryService([_chunk("old", 1), _chunk("new", 2)])
    run = SimpleNamespace(id="exp-1", config_json={})
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=run) as create_run,
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
    ):
        result = service.run(
            corpus_name="legi", strategy=ChunkingStrategy.TRADITIONAL, dataset_path=dataset, versions="all"
        )

    assert service.query_service.calls[0]["versions"] == "all"
    assert create_run.call_args.kwargs["config_json"]["versions"] == "all"
    assert result["summary"]["outdated_hit@5"] == 1.0
    assert result["by_type"]["moved"]["outdated_hit@5"] == 1.0


def test_paired_comparison_of_outdated_hits():
    before = [{"id": f"q{i}", "recall@5": 1, "reciprocal_rank": 0.5, "outdated_hit@5": 1} for i in range(6)]
    after = [{**row, "outdated_hit@5": 0, "reciprocal_rank": 1.0} for row in before]
    entry = compare_suite(before, after)
    assert entry["outdated_hit@5"]["fixed"] == 6 and entry["outdated_hit@5"]["introduced"] == 0
    assert entry["outdated_hit@5"]["significant"]
    text = render({"a": "legi-naive", "b": "legi-versions", "suites": {"legi_versions": entry}})
    assert "Version périmée classée avant la bonne" in text
    assert "1.000 → 0.000" in text
