from __future__ import annotations

from raglab.experiments.recall import RecallBenchmarkCase, RecallBenchmarkService

SPAN = {"file_name": "loi.txt", "start": 1000, "end": 1040, "text": "art. 5º"}


def _case(**overrides) -> RecallBenchmarkCase:
    values = {
        "case_id": "c1",
        "question": "Que dit l'article 5 ?",
        "expected_file_names": ["loi.txt"],
        "expected_urns": [],
        "expected_spans": [SPAN],
    }
    values.update(overrides)
    return RecallBenchmarkCase(**values)


def _chunk(start: int | None, end: int | None, *, file_name: str = "loi.txt", text: str = "...") -> dict:
    return {"file_name": file_name, "chunk_text": text, "char_start": start, "char_end": end}


def test_chunk_overlapping_the_span_is_relevant():
    assert RecallBenchmarkService._is_relevant(_case(), _chunk(900, 1800))
    assert RecallBenchmarkService._is_relevant(_case(), _chunk(1030, 1900))  # partial overlap


def test_chunk_from_right_file_but_wrong_place_is_not_relevant():
    assert not RecallBenchmarkService._is_relevant(_case(), _chunk(0, 900))
    assert not RecallBenchmarkService._is_relevant(_case(), _chunk(1040, 1900))  # end is exclusive


def test_chunk_from_another_file_is_not_relevant_even_if_offsets_match():
    assert not RecallBenchmarkService._is_relevant(_case(), _chunk(900, 1800, file_name="autre.txt"))


def test_without_offsets_falls_back_to_gold_text():
    assert RecallBenchmarkService._is_relevant(_case(), _chunk(None, None, text="Selon o art. 5º, todos..."))
    assert not RecallBenchmarkService._is_relevant(_case(), _chunk(None, None, text="art. 6º"))


def test_cases_without_spans_keep_file_level_relevance():
    case = _case(expected_spans=[])
    assert RecallBenchmarkService._is_relevant(case, _chunk(0, 900))
