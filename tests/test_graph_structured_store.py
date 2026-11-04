"""Neo4j side of the structured graph.

The write path and the service run against a mocked driver. The round trip
through a real Neo4j is skipped unless RAGLAB_TEST_NEO4J_URI is set, e.g.
RAGLAB_TEST_NEO4J_URI=bolt://localhost:7687 (password RAGLAB_NEO4J_PASSWORD).
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from raglab.config import Settings
from raglab.domain.errors import GraphUnavailableError
from raglab.graph.structure import ChunkRow, DocumentRow, build_payload
from raglab.graph.structured import StructuredGraphService, StructuredGraphStore, build_after_index

LAW = """LEI Nº 9.307, DE 23 DE SETEMBRO DE 1996.
Art. 1º As partes poderão valer-se da arbitragem.
Art. 2º Observado o art. 1º desta Lei. (Redação dada pela Lei nº 13.129, de 2015)
"""


def _payload(run: str = "run-1"):
    document = DocumentRow("doc-1", "lei_9307_1996.txt", LAW, {"number": "9307", "year": 1996, "title": "Lei nº 9.307"})
    chunks = [ChunkRow("c0", "doc-1", 0, 0, 90), ChunkRow("c1", "doc-1", 1, 90, len(LAW))]
    return build_payload(index_run_id=run, corpus="laws", documents=[document], chunks=chunks)


@patch("raglab.graph.structured.GraphDatabase.driver")
def test_write_replaces_the_run_and_marks_it_completed(driver_factory):
    session = MagicMock(name="Session")
    driver_factory.return_value.session.return_value.__enter__.return_value = session
    store = StructuredGraphStore(uri="bolt://x:7687", user="u", password="p", settings=Settings())
    store.write(_payload(), duration_ms=12.0)
    statements = [call.args[0] for call in session.run.call_args_list]
    deletes = [index for index, cypher in enumerate(statements) if "DETACH DELETE" in cypher]
    merges = [index for index, cypher in enumerate(statements) if cypher.startswith("UNWIND $rows AS row MERGE")]
    assert deletes and merges and max(deletes) < min(merges)
    # The phase-8 entity store never sets `uid`: deletes cannot reach it.
    assert all("n.uid IS NOT NULL" in statements[index] for index in deletes[:-1])
    assert any("MERGE (a)-[r:CITES]->(b)" in cypher for cypher in statements)
    assert any("SET n:Law" in cypher for cypher in statements)
    assert "r.status = 'completed'" in statements[-1]
    assert any("CREATE CONSTRAINT graph_article_uid" in cypher for cypher in statements)


@patch("raglab.graph.structured.GraphDatabase.driver")
def test_ping_failure_is_reported_not_raised(driver_factory):
    driver_factory.return_value.verify_connectivity.side_effect = OSError("refused")
    assert StructuredGraphStore(settings=Settings()).ping() is False


def _service(store: MagicMock, *, backend: str = "pgvector") -> StructuredGraphService:
    session = MagicMock(name="Session")
    service = StructuredGraphService(session, store=store, settings=Settings())
    run = SimpleNamespace(id="run-1", corpus_id="corpus-1", config_json={"backend": backend})
    service.resolve_index_run = MagicMock(return_value=run)  # type: ignore[method-assign]
    return service


def test_build_without_neo4j_raises_a_typed_error():
    store = MagicMock()
    store.ping.return_value = False
    with pytest.raises(GraphUnavailableError):
        _service(store).build(corpus_name="laws")
    store.write.assert_not_called()


def test_build_writes_the_payload():
    store = MagicMock()
    store.ping.return_value = True
    service = _service(store)
    service.payload = MagicMock(return_value=_payload())  # type: ignore[method-assign]
    result = service.build(corpus_name="laws")
    store.write.assert_called_once()
    assert result["profile"] == "laws"
    assert result["nodes"]["Article"] == 2
    assert result["relationships"]["CITES->Article"] == 1


def test_entity_store_runs_are_refused():
    service = StructuredGraphService(MagicMock(), store=MagicMock(), settings=Settings())
    run = SimpleNamespace(id="run-8", corpus_id="c", config_json={"backend": "neo4j"})
    with patch("raglab.graph.structured.get_index_run", return_value=run), pytest.raises(ValueError, match="phase 8"):
        service.resolve_index_run(corpus_name=None, index_run_id="run-8")


def test_build_after_index_skips_without_neo4j():
    with patch("raglab.graph.structured.StructuredGraphStore") as store_cls:
        store_cls.return_value.ping.return_value = False
        result = build_after_index(MagicMock(), "run-1", settings=Settings(graph_build_on_index=True))
    assert result == {"status": "skipped", "reason": "neo4j_unreachable"}


def test_build_after_index_never_fails_the_indexing():
    with (
        patch("raglab.graph.structured.StructuredGraphStore") as store_cls,
        patch("raglab.graph.structured.StructuredGraphService") as service_cls,
    ):
        store_cls.return_value.ping.return_value = True
        service_cls.return_value.build.side_effect = RuntimeError("boom")
        result = build_after_index(MagicMock(), "run-1", settings=Settings(graph_build_on_index=True))
    assert result == {"status": "failed", "reason": "boom"}


def test_build_after_index_respects_the_setting():
    assert build_after_index(MagicMock(), "run-1", settings=Settings(graph_build_on_index=False)) == {
        "status": "skipped",
        "reason": "disabled",
    }


NEO4J_URI = os.environ.get("RAGLAB_TEST_NEO4J_URI")


@pytest.mark.skipif(not NEO4J_URI, reason="RAGLAB_TEST_NEO4J_URI not set")
def test_round_trip_through_neo4j():
    run = f"test-{uuid.uuid4()}"
    store = StructuredGraphStore(uri=NEO4J_URI, settings=Settings())
    try:
        payload = _payload(run)
        store.write(payload, duration_ms=1.0)
        store.write(payload, duration_ms=1.0)  # idempotent rebuild
        counts = store.counts(run)
        assert counts["nodes"] == {
            "Document": 1,
            "Section": 0,
            "Chunk": 2,
            "Article": 2,
            "Law": 2,
            "Act": 0,
            "Recital": 0,
            "Annex": 0,
        }
        assert counts["relationships"]["CITES->Article"] == 1
        assert counts["relationships"]["AMENDS"] == 1
        assert store.run_info(run)["status"] == "completed"
        laws = store.laws(run)
        assert [law["key"] for law in laws] == ["9307"]
        neighbourhood = store.neighbourhood(run, law_uid=laws[0]["uid"], article="2")
        assert {edge["type"] for edge in neighbourhood["edges"]} == {"PART_OF", "CITES", "AMENDS"}
        chunks = store.chunks_of_articles(run, [f"{run}:doc-1:art:1", f"{run}:doc-1:art:2"])
        assert {uid.rsplit(":", 1)[1]: [row["chunk_id"] for row in rows] for uid, rows in chunks.items()} == {
            "1": ["c0"],
            "2": ["c1"],
        }
    finally:
        store.delete_run(run)
        assert store.run_info(run) is None
        store.close()


def _eu_payload(run: str):
    def unit(doc: str, unit: str, number: str, language: str, references: list[dict], text: str) -> DocumentRow:
        metadata = {
            "celex": "32022R2554",
            "unit": unit,
            "unit_number": number,
            "unit_label": f"{unit.title()} {number}",
            "unit_key": f"32022R2554:{unit}:{number}",
            "language": language,
            "in_force": True,
            "version": 1,
            "valid_from": "2022-12-27",
            "references": references,
        }
        return DocumentRow(doc, f"{doc}.txt", text, metadata)

    cite = [{"unit": "article", "number": "30", "celex": "32022R2554", "scope": "same_act", "text": "Article 30"}]
    explain = [{"unit": "article", "number": "28", "celex": "32022R2554", "scope": "same_act", "text": "Article 28"}]
    documents = [
        unit("a28", "article", "28", "en", cite, "Article 28. In line with Article 30."),
        unit("a30", "article", "30", "en", [], "Article 30. Key contractual provisions."),
        unit("a30fr", "article", "30", "fr", [], "Article 30. Principales dispositions contractuelles."),
        unit("r1", "recital", "1", "en", explain, "(1) As laid down in Article 28 of this Regulation."),
    ]
    chunks = [ChunkRow(f"c-{d.id}", d.id, 0, 0, len(d.content)) for d in documents]
    return build_payload(index_run_id=run, corpus="eu", documents=documents, chunks=chunks)


@pytest.mark.skipif(not NEO4J_URI, reason="RAGLAB_TEST_NEO4J_URI not set")
def test_eu_acts_round_trip_through_neo4j():
    run = f"test-{uuid.uuid4()}"
    store = StructuredGraphStore(uri=NEO4J_URI, settings=Settings())
    try:
        payload = _eu_payload(run)
        assert payload.profile == "eu_acts"
        store.write(payload, duration_ms=1.0)
        counts = store.counts(run)
        assert {label: counts["nodes"][label] for label in ("Act", "Article", "Recital", "Chunk")} == {
            "Act": 1,
            "Article": 3,
            "Recital": 1,
            "Chunk": 4,
        }
        assert counts["relationships"]["CITES->Article"] == 1
        assert counts["relationships"]["EXPLAINS->Article"] == 1
        assert counts["relationships"]["SAME_AS"] == 1
        # The graph retrieval branch follows EU citations with the laws query.
        rows = store.cited_articles(
            run,
            seed_chunks=[{"id": "c-a28", "rank": 1}],
            seed_articles=[],
            max_seeds=5,
            per_seed=3,
            chunks_per_article=2,
        )
        assert [(row["target_number"], row["target_law_key"], row["chunk_ids"]) for row in rows] == [
            ("30", "DORA", ["c-a30"])
        ]
    finally:
        store.delete_run(run)
        assert store.run_info(run) is None
        store.close()


@patch("raglab.graph.structured.GraphDatabase.driver")
def test_unreachable_neo4j_is_not_retried_on_every_query(driver_factory):
    from neo4j.exceptions import ServiceUnavailable

    driver_factory.return_value.session.return_value.__enter__.return_value.run.side_effect = ServiceUnavailable("down")
    store = StructuredGraphStore(settings=Settings(graph_retry_seconds=60))
    with pytest.raises(ServiceUnavailable):
        store.run_info("run-1")
    with pytest.raises(ServiceUnavailable, match="not retried yet"):
        store.run_info("run-1")
    assert driver_factory.return_value.session.return_value.__enter__.return_value.run.call_count == 1
    # A successful ping closes the breaker.
    driver_factory.return_value.verify_connectivity.return_value = None
    assert store.ping() is True
    with pytest.raises(ServiceUnavailable, match="down"):
        store.run_info("run-1")
