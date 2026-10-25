"""Shared R-multiple aggregates used by the journal and the backtester."""

import pytest

from smc_scanner.rstats import expectancy, hit_rate, mean


def test_empty_lists_give_none() -> None:
    assert mean([]) is None and hit_rate([]) is None and expectancy([]) is None


def test_breakeven_is_not_a_win() -> None:
    assert hit_rate([1.0, 0.0, -1.0, 2.0]) == pytest.approx(0.5)


def test_expectancy_is_the_mean_r() -> None:
    rs = [2.0, -1.0, -1.0, 0.5]

    assert expectancy(rs) == mean(rs) == pytest.approx(0.125)


def test_mean_keeps_precision_on_long_lists() -> None:
    assert mean([0.1] * 10) == pytest.approx(0.1, abs=0)
