"""The percentile every measurement row reports: nearest-rank, so a reported
p95 is always a value that was actually observed, never an interpolation."""

from __future__ import annotations

import pytest

from maipai_body.measure.stats import percentile, summarize


def test_percentile_is_nearest_rank_and_always_an_observed_value():
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 100.0
    assert percentile(values, 10) == 10.0
    assert percentile(values, 0) == 10.0
    assert percentile(values, 100) == 100.0


def test_percentile_does_not_depend_on_input_order():
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0


def test_percentile_of_one_value_is_that_value():
    assert percentile([7.5], 95) == 7.5


def test_percentile_of_nothing_is_an_error_not_a_zero():
    with pytest.raises(ValueError):
        percentile([], 50)


def test_percentile_rejects_a_quantile_outside_zero_to_one_hundred():
    with pytest.raises(ValueError):
        percentile([1.0], 101)


def test_summarize_reports_count_p50_p95_min_max():
    summary = summarize([4.0, 1.0, 3.0, 2.0])
    assert summary == {"n": 4, "p50": 2.0, "p95": 4.0, "min": 1.0, "max": 4.0}


def test_summarize_of_nothing_reports_zero_samples_and_no_numbers():
    assert summarize([]) == {"n": 0, "p50": None, "p95": None, "min": None, "max": None}
