"""Backtest statistics over labelled outcomes, with a bootstrap interval on expectancy.

Only closed outcomes (target, stop, time) count; ``open`` and ``void`` ones are counted apart.
With no closed outcome every ratio is None. Order matters for the drawdown only: it is measured
on the cumulative R path in the order the outcomes are given (signal order).

Assumptions a reader must keep in mind: every trade risks 1R, with unlimited concurrency, so
overlapping trades (several signals on one bar, or across symbols when pooled) all count in
full, and the signal-order path is not an exit-time equity curve. The bootstrap resamples
trades as independent; clustered signals make its interval too narrow. ``low_sample`` flags
counts under ``LOW_SAMPLE_N``, where a percentile bootstrap is unreliable.
"""

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from smc_scanner import rstats
from smc_scanner.backtest.outcome import Outcome

BOOTSTRAP_RESAMPLES: Final = 2000
CONFIDENCE: Final = 0.95
LOW_SAMPLE_N: Final = 30


@dataclass(frozen=True)
class BacktestStats:
    n: int  # closed trades
    n_open: int  # horizon past the end of the frame: no R
    n_void: int  # entry at, beyond or too close to the stop: no trade
    low_sample: bool  # n < LOW_SAMPLE_N
    hit_rate: float | None
    average_r: float | None
    expectancy_r: float | None
    median_r: float | None
    best_r: float | None
    worst_r: float | None
    total_r: float
    profit_factor: float | None  # None also when there is no losing trade (undefined)
    max_drawdown_r: float | None  # a positive number of R below the running peak
    avg_bars_held: float | None
    ci_low: float | None  # bootstrap interval of expectancy_r at CONFIDENCE
    ci_high: float | None


def profit_factor(rs: Sequence[float]) -> float | None:
    """Gross win over gross loss, in R; None without a losing trade."""
    gross_loss = -math.fsum(r for r in rs if r < 0)
    if gross_loss == 0:
        return None
    return math.fsum(r for r in rs if r > 0) / gross_loss


def max_drawdown(rs: Sequence[float]) -> float | None:
    """Largest fall of the cumulative R path below its running peak (which starts at 0)."""
    if not rs:
        return None
    path = np.cumsum(np.asarray(rs, dtype=float))
    peaks = np.maximum.accumulate(np.maximum(path, 0.0))
    return float(np.max(peaks - path))


def bootstrap_ci(
    rs: Sequence[float],
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval of the mean R; the same ``seed`` gives the same interval."""
    if resamples < 1:
        raise ValueError("resamples must be at least 1")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if not rs:
        return None
    values = np.asarray(rs, dtype=float)
    rng = np.random.default_rng(seed)
    # One resample at a time keeps memory at O(n) however many trades there are.
    means = np.fromiter(
        (values[rng.integers(0, len(values), len(values))].mean() for _ in range(resamples)),
        dtype=float,
        count=resamples,
    )
    tail = (1 - confidence) / 2 * 100
    low, high = np.percentile(means, [tail, 100 - tail])
    return float(low), float(high)


def summarise(outcomes: Iterable[Outcome], *, seed: int = 0) -> BacktestStats:
    items = list(outcomes)
    closed = [(o.r_multiple, o.bars_held) for o in items if o.r_multiple is not None]
    rs = [r for r, _ in closed]
    ci = bootstrap_ci(rs, seed=seed)
    return BacktestStats(
        n=len(rs),
        n_open=sum(o.exit_reason == "open" for o in items),
        n_void=sum(o.exit_reason == "void" for o in items),
        low_sample=len(rs) < LOW_SAMPLE_N,
        hit_rate=rstats.hit_rate(rs),
        average_r=rstats.mean(rs),
        expectancy_r=rstats.expectancy(rs),
        median_r=statistics.median(rs) if rs else None,
        best_r=max(rs, default=None),
        worst_r=min(rs, default=None),
        total_r=math.fsum(rs),
        profit_factor=profit_factor(rs),
        max_drawdown_r=max_drawdown(rs),
        avg_bars_held=rstats.mean([float(held) for _, held in closed]),
        ci_low=None if ci is None else ci[0],
        ci_high=None if ci is None else ci[1],
    )
