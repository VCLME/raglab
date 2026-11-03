from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from raglab.graph.entities import (
    DEFAULT_ENTITY_TYPES,
    ExtractedEntity,
    UnsupportedExtractionEngineError,
    build_entity_extractor,
)
from raglab.graph.entities.base import normalise_name, normalise_type
from raglab.graph.entities.llm import LLMEntityExtractor, _parse_entities


def test_build_entity_extractor_rejects_unknown_engine():
    with pytest.raises(UnsupportedExtractionEngineError, match="inconnu"):
        build_entity_extractor("weaviate")


def test_normalise_name_trims_and_lowercases():
    assert normalise_name("  Jakob   Böhme  ") == "jakob böhme"


def test_normalise_type_maps_unknown_to_misc():
    assert normalise_type("Person") == "PERSON"
    assert normalise_type("FRUIT") == "MISC"
    assert normalise_type("") == "MISC"


def test_llm_parse_entities_handles_surrounding_prose():
    answer = (
        "Here you go:\n"
        '{"entities": [{"name": "Jakob Böhme", "type": "PERSON"}, '
        '{"name": "Görlitz", "type": "LOCATION"}]}\n'
        "Done."
    )
    entities = _parse_entities(answer)
    assert len(entities) == 2
    assert entities[0] == ExtractedEntity(name="jakob böhme", type="PERSON", raw_text="Jakob Böhme")
    assert entities[1].type == "LOCATION"


def test_llm_parse_entities_drops_unknown_types():
    answer = '{"entities": [{"name": "Foo", "type": "FRUIT"}]}'
    entities = _parse_entities(answer)
    # Unknown type normalises to MISC, entity still kept.
    assert entities == [ExtractedEntity(name="foo", type="MISC", raw_text="Foo")]


def test_llm_parse_entities_deduplicates_by_name_and_type():
    answer = (
        '{"entities": ['
        '{"name": "Jakob", "type": "PERSON"},'
        '{"name": "jakob", "type": "PERSON"},'
        '{"name": "Jakob", "type": "PERSON"}'
        "]}"
    )
    entities = _parse_entities(answer)
    assert len(entities) == 1
    assert entities[0].name == "jakob"


def test_llm_parse_entities_returns_empty_on_junk():
    assert _parse_entities("") == []
    assert _parse_entities("no json at all") == []
    assert _parse_entities("{malformed") == []


def test_llm_extractor_invokes_ollama_and_returns_entities():
    ollama = MagicMock()
    ollama.chat.return_value = {
        "answer": '{"entities": [{"name": "Neo4j", "type": "ORGANIZATION"}]}',
    }
    extractor = LLMEntityExtractor(ollama=ollama)
    entities = extractor.extract("Neo4j is a graph database.")
    assert entities == [ExtractedEntity(name="neo4j", type="ORGANIZATION", raw_text="Neo4j")]
    ollama.chat.assert_called_once()


def test_llm_extractor_short_circuits_on_empty_text():
    ollama = MagicMock()
    extractor = LLMEntityExtractor(ollama=ollama)
    assert extractor.extract("") == []
    assert extractor.extract("   ") == []
    ollama.chat.assert_not_called()


def test_llm_extractor_returns_empty_on_chat_failure():
    ollama = MagicMock()
    ollama.chat.side_effect = RuntimeError("ollama down")
    extractor = LLMEntityExtractor(ollama=ollama)
    assert extractor.extract("hello") == []


def test_spacy_extractor_uses_injected_nlp():
    # Import inside test to skip when spaCy not installed.
    spacy = pytest.importorskip("spacy")
    del spacy  # only needed to gate the test
    from raglab.graph.entities.spacy import SpacyEntityExtractor

    fake_ent = MagicMock()
    fake_ent.text = "Jakob Böhme"
    fake_ent.label_ = "PERSON"
    fake_ent.start_char = 0
    fake_ent.end_char = 11
    fake_doc = MagicMock()
    fake_doc.ents = [fake_ent]
    fake_nlp = MagicMock()
    fake_nlp.return_value = fake_doc

    extractor = SpacyEntityExtractor(nlp=fake_nlp)
    entities = extractor.extract("Jakob Böhme est né à Görlitz.")
    assert entities[0].name == "jakob böhme"
    assert entities[0].type == "PERSON"
    assert entities[0].span == (0, 11)


def test_default_types_include_expected_coverage():
    # Canonical set must include at least PERSON / ORG / LOCATION
    for key in ("PERSON", "ORGANIZATION", "LOCATION"):
        assert key in DEFAULT_ENTITY_TYPES
