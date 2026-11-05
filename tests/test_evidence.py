from __future__ import annotations

from raglab.benchmarks.evidence import score_case

ARTICLE = [{"file_name": "lei.txt", "start": 0, "end": 1000}]
OFFENCE_LAW = {"file_name": "lei.txt", "start": 100, "end": 160}
AMOUNT_LAW = {"file_name": "lei.txt", "start": 700, "end": 780}
OFFENCE_DECREE = {"file_name": "dec.txt", "start": 50, "end": 110}
AMOUNT_DECREE = {"file_name": "dec.txt", "start": 400, "end": 480}
# Q4: the offence and the amount are both needed; the law or the decree gives them.
EVIDENCE = {
    "groups": [
        {"label": "lei", "spans": [OFFENCE_LAW, AMOUNT_LAW]},
        {"label": "dec", "spans": [OFFENCE_DECREE, AMOUNT_DECREE]},
    ]
}


def _chunk(file_name, start, end):
    return {"file_name": file_name, "char_start": start, "char_end": end}


def test_article_found_without_the_provision():
    levels = score_case([_chunk("lei.txt", 300, 600)], ARTICLE, EVIDENCE)
    assert levels == {"article": True, "provision": False, "complete": False}


def test_one_provision_of_a_cumulative_group_is_not_enough():
    levels = score_case([_chunk("lei.txt", 90, 400)], ARTICLE, EVIDENCE)
    assert levels == {"article": True, "provision": True, "complete": False}


def test_every_span_of_one_group_completes_the_evidence():
    chunks = [_chunk("lei.txt", 90, 400), _chunk("lei.txt", 650, 900)]
    assert score_case(chunks, ARTICLE, EVIDENCE)["complete"] is True


def test_alternatives_are_not_mixed_across_groups():
    """The law's offence and the decree's amount do not make a complete group."""
    chunks = [_chunk("lei.txt", 90, 400), _chunk("dec.txt", 380, 500)]
    assert score_case(chunks, ARTICLE, EVIDENCE)["complete"] is False
    chunks.append(_chunk("dec.txt", 0, 200))
    assert score_case(chunks, ARTICLE, EVIDENCE)["complete"] is True


def test_a_provision_cut_in_half_by_a_chunk_still_counts():
    assert score_case([_chunk("lei.txt", 130, 400)], ARTICLE, EVIDENCE)["provision"] is True
    assert score_case([_chunk("lei.txt", 150, 400)], ARTICLE, EVIDENCE)["provision"] is False


def test_a_question_without_evidence_annotation_is_not_scored():
    assert score_case([_chunk("lei.txt", 0, 10)], ARTICLE, None) == {
        "article": True,
        "provision": None,
        "complete": None,
    }
