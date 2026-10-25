"""Backtest statistics on hand-made R lists: ratios, drawdown and the bootstrap interval."""

import math
from collections.abc import Sequence

import pytest
from backtest_support import make_outcome

from smc_scanner.backtest.outcome import Outcome
from smc_scanner.backtest.stats import bootstrap_ci, max_drawdown, profit_factor, summarise


def _outcomes(rs: Sequence[float | None]) -> list[Outcome]:
    return [make_outcome(r, bars_held=i + 1, bar_index=i) for i, r in enumerate(rs)]


def test_known_r_list_gives_known_ratios() -> None:
    stats = summarise(_outcomes([2.0, -1.0, -1.0, 2.0, -1.0]))

    assert stats.n == 5 and stats.n_open == 0 and stats.n_void == 0
    assert stats.low_sample
    assert stats.hit_rate == pytest.approx(0.4)
    assert stats.average_r == pytest.approx(0.2)
    assert stats.expectancy_r == pytest.approx(0.2)
    assert stats.total_r == pytest.approx(1.0)
    assert stats.profit_factor == pytest.approx(4.0 / 3.0)
    assert stats.max_drawdown_r == pytest.approx(2.0)  # cumulative 2, 1, 0, 2, 1: peak 2 to 0
    assert stats.avg_bars_held == pytest.approx(3.0)
    assert (stats.median_r, stats.best_r, stats.worst_r) == (-1.0, 2.0, -1.0)


def test_open_and_void_outcomes_are_excluded() -> None:
    outcomes = [
        *_outcomes([1.0, -1.0]),
        make_outcome(None),
        make_outcome(None, reason="void", bars_held=0),
    ]
    stats = summarise(outcomes)

    assert (stats.n, stats.n_open, stats.n_void) == (2, 1, 1)
    assert stats.avg_bars_held == pytest.approx(1.5)


def test_no_closed_outcomes_gives_none() -> None:
    stats = summarise([make_outcome(None)])

    assert stats.n == 0 and stats.n_open == 1 and stats.low_sample
    assert stats.total_r == 0.0
    for value in (
        stats.hit_rate,
        stats.average_r,
        stats.expectancy_r,
        stats.profit_factor,
        stats.max_drawdown_r,
        stats.avg_bars_held,
        stats.median_r,
        stats.best_r,
        stats.worst_r,
        stats.ci_low,
        stats.ci_high,
    ):
        assert value is None


def test_confidence_interval_contains_the_mean() -> None:
    rs = [2.0, -1.0, -1.0, 2.0, -1.0, 0.5, -0.3, 2.0, -1.0, 1.2]
    stats = summarise(_outcomes(list(rs)))

    assert stats.ci_low is not None and stats.ci_high is not None
    assert stats.expectancy_r is not None
    assert stats.ci_low < stats.expectancy_r < stats.ci_high
    assert min(rs) <= stats.ci_low and stats.ci_high <= max(rs)


def test_same_seed_same_interval_and_another_seed_differs() -> None:
    rs = [2.0, -1.0, -1.0, 2.0, -1.0, 0.5, -0.3, 2.0, -1.0, 1.2]

    assert bootstrap_ci(rs, seed=7) == bootstrap_ci(rs, seed=7)
    assert summarise(_outcomes(list(rs)), seed=3) == summarise(_outcomes(list(rs)), seed=3)
    assert bootstrap_ci(rs, seed=7) != bootstrap_ci(rs, seed=8)


def test_single_trade_interval_is_that_trade() -> None:
    assert bootstrap_ci([1.5], seed=0) == (1.5, 1.5)


def test_bootstrap_rejects_bad_settings() -> None:
    with pytest.raises(ValueError):
        bootstrap_ci([1.0], seed=0, resamples=0)
    with pytest.raises(ValueError):
        bootstrap_ci([1.0], seed=0, confidence=1.0)


def test_empty_helpers_return_none() -> None:
    assert bootstrap_ci([], seed=0) is None
    assert max_drawdown([]) is None
    assert profit_factor([]) is None


def test_profit_factor_is_none_without_a_loss() -> None:
    assert profit_factor([1.0, 2.0, 0.0]) is None
    assert profit_factor([-1.0, 0.0]) == 0.0


def test_drawdown_counts_losses_from_the_start() -> None:
    assert max_drawdown([-1.0, -1.0, 2.0]) == pytest.approx(2.0)
    assert max_drawdown([1.0, 2.0]) == 0.0
    assert max_drawdown([1.0, -0.5, 3.0, -2.0, -2.0, 1.0]) == pytest.approx(4.0)


def test_stats_are_finite_numbers() -> None:
    stats = summarise(_outcomes([2.0, -1.0, 0.0]))

    assert all(
        math.isfinite(value)
        for value in (stats.ci_low, stats.ci_high, stats.profit_factor)
        if value is not None
    )


def test_thirty_closed_trades_are_no_longer_a_low_sample() -> None:
    assert not summarise(_outcomes([1.0, -1.0] * 15)).low_sample
    assert summarise(_outcomes([1.0, -1.0] * 14 + [1.0])).low_sample
