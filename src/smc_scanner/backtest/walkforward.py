"""Walk-forward evaluation: in-sample and out-of-sample stats, the null baselines and a verdict.

Each symbol's frame is cut at a boundary bar ``s``: the train part is bars ``[0, s)``, the test
part bars ``[s, end)``. A ``"time"`` split puts ``s`` at ``train_fraction`` of each frame's
rows; a ``"symbols"`` split sends whole symbols to one side (``s`` is the frame length for a
train symbol, 0 for a test symbol).

What each side may read (``split_outcomes``):

* Signals come from one replay of the whole frame. Replay is point-in-time, so a signal at bar
  ``i`` reads bars ``[0, i]`` only, whichever side it lands on. A signal belongs to the side of
  its own bar: in-sample when ``bar_index < s``, out-of-sample otherwise. (Replaying from ``s``
  instead would re-signal zones first hit before ``s``.)
* In-sample outcomes are labelled on the train part alone, so they never see a test bar. A trade
  whose time-stop horizon runs past ``s`` is ``open`` there: it stays in-sample, counted in
  ``n_open``, and is never moved to the test side. Its forward returns past ``s`` are None.
* Out-of-sample outcomes are labelled on the whole frame. Before their own bar they read the
  signal's own history only: the zone it signalled on and the ATR of the bars up to the signal
  bar (``ATR_PERIOD`` + 1 bars). Entry, exits and forward returns are all at or after ``s``.

The baselines (``baseline``) are computed on the test part only. The random one pools
``RANDOM_DRAWS`` independent draws, each with as many entries per symbol as that symbol's test
signals, at bars from ``max(s, MIN_BARS)`` on: one draw of a few dozen trades is too noisy a
bar to judge against. The flipped one is the test signals flipped. Pooled stats order outcomes
by signal time, then symbol, as ``run_backtest`` does.

The verdict (``verdict``) is ``"insufficient"`` under ``LOW_SAMPLE_N`` closed test trades, or
when either baseline has fewer closed trades than that; ``"pass"`` when the test expectancy's
bootstrap lower bound is above 0 and the test expectancy beats both baselines' expectancy;
``"fail"`` otherwise. The bootstrap treats trades as independent (see ``stats``).

A time split cuts each frame at its own row fraction: with equal-length frames from one loader
the boundaries line up in time, but with ragged frames one symbol's test part can predate
another's train part, so pooled out-of-sample is not strictly later than pooled in-sample. A
symbol split has no temporal separation at all: train and test symbols cover the same calendar
period, so correlated instruments share a regime across the split.
"""

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Final, Literal, get_args

import numpy as np
import pandas as pd

from smc_scanner.backtest._common import (
    check_args,
    check_seed,
    chronological,
    distinct_symbols,
    json_safe,
    load_frame,
    run_each,
)
from smc_scanner.backtest.baseline import flipped_signals, random_signals
from smc_scanner.backtest.outcome import ExitRules, Outcome, label
from smc_scanner.backtest.replay import Signal, replay
from smc_scanner.backtest.stats import LOW_SAMPLE_N, BacktestStats, summarise
from smc_scanner.config import MIN_BARS
from smc_scanner.loaders.base import Loader
from smc_scanner.scanner import ScanFailure, ScanOptions
from smc_scanner.strategy.models import Strategy

log = logging.getLogger(__name__)

SplitKind = Literal["time", "symbols"]
Verdict = Literal["pass", "fail", "insufficient"]
DEFAULT_TRAIN_FRACTION: Final = 0.6
RANDOM_DRAWS: Final = 20  # random-baseline draws pooled per run


def _fraction(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value < 1:
        raise ValueError("train_fraction must be a number strictly between 0 and 1")
    return float(value)


def _train_size(n: int, fraction: float) -> int:
    """``floor(n * fraction)``, immune to float error (``90 * 0.7`` is 62.99...)."""
    return math.floor(round(n * fraction, 9))


def split_by_time(ohlc: pd.DataFrame, train_fraction: float = DEFAULT_TRAIN_FRACTION) -> int:
    """The first test bar: train is the bars before it, test the bars from it. Both parts keep
    at least one bar."""
    fraction = _fraction(train_fraction)
    if len(ohlc) < 2:
        raise ValueError("a time split needs at least 2 bars")
    return min(max(_train_size(len(ohlc), fraction), 1), len(ohlc) - 1)


def split_by_symbols(
    symbols: Iterable[str], train_fraction: float, *, seed: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(train, test): a seeded random partition of the distinct symbols, ``floor(n *
    train_fraction)`` to train, each side keeping the input order and at least one symbol."""
    fraction = _fraction(train_fraction)
    check_seed(seed)
    unique = distinct_symbols(symbols)
    if len(unique) < 2:
        raise ValueError("a symbol split needs at least 2 distinct symbols")
    size = min(max(_train_size(len(unique), fraction), 1), len(unique) - 1)
    chosen = set(np.random.default_rng(seed).permutation(len(unique))[:size].tolist())
    train = tuple(s for i, s in enumerate(unique) if i in chosen)
    test = tuple(s for i, s in enumerate(unique) if i not in chosen)
    return train, test


def split_outcomes(
    ohlc: pd.DataFrame, signals: Sequence[Signal], boundary: int, rules: ExitRules
) -> tuple[tuple[Outcome, ...], tuple[Outcome, ...]]:
    """(in-sample, out-of-sample) outcomes of ``signals`` (replayed on ``ohlc``), each in the
    given order: in-sample labelled on ``ohlc.iloc[:boundary]``, out-of-sample on ``ohlc``."""
    if not 0 <= boundary <= len(ohlc):
        raise ValueError(f"boundary {boundary} is outside a frame of {len(ohlc)} bars")
    train = ohlc.iloc[:boundary]
    in_sample = tuple(label(train, s, rules) for s in signals if s.bar_index < boundary)
    out_of_sample = tuple(label(ohlc, s, rules) for s in signals if s.bar_index >= boundary)
    return in_sample, out_of_sample


def verdict(
    out_of_sample: BacktestStats, random_baseline: BacktestStats, flipped_baseline: BacktestStats
) -> Verdict:
    """Whether the out-of-sample result shows an edge over both null baselines."""
    expectancy, ci_low = out_of_sample.expectancy_r, out_of_sample.ci_low
    if out_of_sample.n < LOW_SAMPLE_N or expectancy is None or ci_low is None:
        return "insufficient"
    bars: list[float] = []
    for baseline in (random_baseline, flipped_baseline):
        if baseline.n < LOW_SAMPLE_N or baseline.expectancy_r is None:
            return "insufficient"
        bars.append(baseline.expectancy_r)
    return "pass" if ci_low > 0 and all(expectancy > bar for bar in bars) else "fail"


@dataclass(frozen=True)
class SymbolWindow:
    """How one symbol was split. ``boundary`` is the first test bar: ``bars`` for a symbol that
    is all train, 0 for one that is all test; ``boundary_time`` is None when there is no test
    bar. The signal counts include ``open`` and ``void`` ones."""

    symbol: str
    bars: int
    boundary: int
    boundary_time: str | None
    in_sample_signals: int
    out_of_sample_signals: int


@dataclass(frozen=True)
class WalkForwardResult:
    timeframe: str
    bars: int
    strategy: str
    rules: ExitRules
    seed: int
    stride: int
    split: SplitKind
    train_fraction: float
    random_draws: int
    windows: tuple[SymbolWindow, ...]  # loaded symbols, in input order
    in_sample: BacktestStats
    out_of_sample: BacktestStats
    random_baseline: BacktestStats  # random_draws pooled draws on the out-of-sample part
    flipped_baseline: BacktestStats  # the out-of-sample signals, flipped
    verdict: Verdict
    failures: tuple[ScanFailure, ...]

    def to_dict(self) -> dict[str, object]:
        """The whole result as strict-JSON data: a non-finite float becomes None."""
        safe: dict[str, object] = json_safe(
            {
                "timeframe": self.timeframe,
                "bars": self.bars,
                "strategy": self.strategy,
                "seed": self.seed,
                "stride": self.stride,
                "split": self.split,
                "train_fraction": self.train_fraction,
                "random_draws": self.random_draws,
                "rules": asdict(self.rules),
                "verdict": self.verdict,
                "in_sample": asdict(self.in_sample),
                "out_of_sample": asdict(self.out_of_sample),
                "random_baseline": asdict(self.random_baseline),
                "flipped_baseline": asdict(self.flipped_baseline),
                "windows": [asdict(window) for window in self.windows],
                "failures": [asdict(failure) for failure in self.failures],
            }
        )
        return safe


@dataclass(frozen=True)
class _SymbolResult:
    window: SymbolWindow
    in_sample: tuple[Outcome, ...]
    out_of_sample: tuple[Outcome, ...]
    random: tuple[Outcome, ...]
    flipped: tuple[Outcome, ...]


def _draw_seed(seed: int, position: int, draw: int) -> int:
    """An independent random-baseline seed per symbol and draw, fixed by the symbol's place in
    the input."""
    return int(np.random.SeedSequence([seed, position, draw]).generate_state(1)[0])


@dataclass(frozen=True)
class _Job:
    """Everything one symbol's walk-forward needs besides the symbol."""

    loader: Loader
    timeframe: str
    bars: int
    strategy: Strategy
    rules: ExitRules
    options: ScanOptions | None
    seed: int
    stride: int
    train_fraction: float
    test_symbols: frozenset[str] | None  # None: a time split

    def _boundary(self, symbol: str, ohlc: pd.DataFrame) -> int:
        if self.test_symbols is None:
            return split_by_time(ohlc, self.train_fraction)
        return 0 if symbol in self.test_symbols else len(ohlc)

    def _randoms(
        self, ohlc: pd.DataFrame, tested: Sequence[Signal], start: int, position: int
    ) -> tuple[Outcome, ...]:
        signals = (
            signal
            for draw in range(RANDOM_DRAWS)
            for signal in random_signals(
                ohlc, tested, seed=_draw_seed(self.seed, position, draw), start=start
            )
        )
        return tuple(label(ohlc, signal, self.rules) for signal in signals)

    def run(self, position: int, symbol: str) -> _SymbolResult:
        ohlc = load_frame(self.loader, symbol, self.timeframe, self.bars)
        boundary = self._boundary(symbol, ohlc)
        signals = replay(symbol, ohlc, self.strategy, options=self.options, stride=self.stride)
        in_sample, out_of_sample = split_outcomes(ohlc, signals, boundary, self.rules)
        tested = [outcome.signal for outcome in out_of_sample]
        window = SymbolWindow(
            symbol=symbol,
            bars=len(ohlc),
            boundary=boundary,
            boundary_time=str(ohlc["time"].iloc[boundary]) if boundary < len(ohlc) else None,
            in_sample_signals=len(in_sample),
            out_of_sample_signals=len(out_of_sample),
        )
        return _SymbolResult(
            window=window,
            in_sample=in_sample,
            out_of_sample=out_of_sample,
            random=self._randoms(ohlc, tested, max(boundary, MIN_BARS), position),
            flipped=tuple(label(ohlc, s, self.rules) for s in flipped_signals(ohlc, tested)),
        )


def check_walk_forward_args(
    bars: int, seed: int, stride: int, strategy: Strategy, split: str, train_fraction: float
) -> float:
    """Raise on any bad argument before anything loads; returns ``train_fraction``."""
    check_args(bars, seed, stride, strategy)
    if split not in get_args(SplitKind):
        raise ValueError(f"split must be one of {', '.join(get_args(SplitKind))}")
    return _fraction(train_fraction)


def _pool(parts: Iterable[tuple[Outcome, ...]], seed: int) -> BacktestStats:
    return summarise(chronological(o for part in parts for o in part), seed=seed)


def walk_forward(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    strategy: Strategy,
    rules: ExitRules,
    *,
    split: SplitKind,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    options: ScanOptions | None = None,
    seed: int = 0,
    stride: int = 1,
) -> WalkForwardResult:
    """Walk-forward ``strategy`` on each distinct symbol's last ``bars`` candles (see the module
    docstring for the split and what each side reads). ``seed`` fixes the symbol split, the
    random baseline and every bootstrap. Bad arguments raise before anything loads; a symbol
    whose load, replay or labelling fails is logged, recorded and skipped whole. The caller
    owns and closes ``loader``."""
    fraction = check_walk_forward_args(bars, seed, stride, strategy, split, train_fraction)
    unique = distinct_symbols(symbols)
    test = None
    if split == "symbols":
        test = frozenset(split_by_symbols(unique, fraction, seed=seed)[1])
    job = _Job(loader, timeframe, bars, strategy, rules, options, seed, stride, fraction, test)
    results, failures = run_each(unique, job.run, log)
    out_of_sample = _pool((r.out_of_sample for r in results), seed)
    random_baseline = _pool((r.random for r in results), seed)
    flipped_baseline = _pool((r.flipped for r in results), seed)
    return WalkForwardResult(
        timeframe=timeframe,
        bars=bars,
        strategy=strategy.slug,
        rules=rules,
        seed=seed,
        stride=stride,
        split=split,
        train_fraction=fraction,
        random_draws=RANDOM_DRAWS,
        windows=tuple(result.window for result in results),
        in_sample=_pool((r.in_sample for r in results), seed),
        out_of_sample=out_of_sample,
        random_baseline=random_baseline,
        flipped_baseline=flipped_baseline,
        verdict=verdict(out_of_sample, random_baseline, flipped_baseline),
        failures=tuple(failures),
    )
