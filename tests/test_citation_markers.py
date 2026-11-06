import pytest

from raglab.generation.citations import cited_ranks, marker_ranks, normalize_citations


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("A [Rank 2].", "A [Rank 2]."),
        ("A [rank 2].", "A [Rank 2]."),
        # Copied from the context header (Qwen3.6).
        ("A [Source rank=3].", "A [Rank 3]."),
        ("A [Source rank = 3].", "A [Rank 3]."),
        ("A [Source rank 3].", "A [Rank 3]."),
        ("A (Source rank=3).", "A [Rank 3]."),
        ("A [Rank=1].", "A [Rank 1]."),
        ("A [Source rank=1, Source rank=4].", "A [Rank 1][Rank 4]."),
        ("A [Rank 1, Rank 3].", "A [Rank 1][Rank 3]."),
        ("A [Rank 1, 3, 5].", "A [Rank 1][Rank 3][Rank 5]."),
        ("A [Ranks 2 et 4].", "A [Rank 2][Rank 4]."),
        ("A [Ranks 2 and 4].", "A [Rank 2][Rank 4]."),
        ("A [Rank 2-4].", "A [Rank 2][Rank 3][Rank 4]."),
        ("A [Ranks 1 à 3].", "A [Rank 1][Rank 2][Rank 3]."),
    ],
)
def test_normalize_citations_rewrites_every_marker_form_to_rank_n(written, expected):
    assert normalize_citations(written) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Fill in the [Rank X] placeholder.",
        "Article L221-18 (version 2016) applies.",
        "See [Rank 1-A] of the table.",
        "Item (3) of the list.",
    ],
)
def test_normalize_citations_leaves_other_brackets_alone(text):
    assert normalize_citations(text) == text


def test_marker_ranks_reads_a_long_range_as_its_two_ends():
    assert marker_ranks("[Rank 1-40]") == [1, 40]


def test_cited_ranks_reads_every_form_but_not_a_trailing_sources_list():
    answer = "A [Source rank=1]. B [Ranks 2 et 4].\n\nSources : [Rank 5]"
    assert cited_ranks(answer) == {1, 2, 4}
