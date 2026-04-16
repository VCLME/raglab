import pytest

from raglab.experiments.metrics import first_relevant_rank, hit_at_k, precision_at_k, reciprocal_rank


def test_metrics_compute_expected_values():
    flags = [False, True, False, True]

    assert first_relevant_rank(flags) == 2
    assert reciprocal_rank(flags) == 0.5
    assert hit_at_k(flags, 1) is False
    assert hit_at_k(flags, 2) is True
    assert precision_at_k(flags, 2) == 0.5
    assert precision_at_k(flags, 4) == 0.5


def test_metrics_reject_invalid_k():
    with pytest.raises(ValueError):
        hit_at_k([True], 0)
    with pytest.raises(ValueError):
        precision_at_k([True], 0)
