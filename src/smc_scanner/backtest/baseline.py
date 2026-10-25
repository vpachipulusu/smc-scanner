"""Null baselines a strategy has to beat: random entries and its own signals flipped.

Both build ``Signal``s by hand and run them through ``label``, so they trade under the same
``ExitRules`` (entry at the next open, stop beyond the zone's far edge, ``rr`` target, time
stop, spread) as the strategy. Both are deterministic: the random one for a given ``seed``.

Random entries (``random_signals``): the same number of signals as the strategy, at bars drawn
uniformly from ``start`` to the last bar, without replacement while there are enough bars (with
replacement beyond that). A seeded permutation pairs each random signal 1:1 with a strategy
signal and copies its direction (so the long/short mix, and its exposure to drift, match) and
its geometry: the distance ``d`` from the strategy signal's close to its zone's far edge, in
that signal's ATR. The random zone sits that far from its own bar's close in its own bar's
ATR: ``[close - d * atr, close]`` for a long, ``[close, close + d * atr]`` for a short. Given
only a count, the direction is a fair coin and ``d`` is 1 ATR. A strategy signal whose close is
already beyond its far edge gives ``d = 0``: the stop sits at the close, so the trade voids
under ``min_risk_atr`` unless the next bar opens at least that far in its favour.

Flipped (``flipped_signals``): every strategy signal with its direction inverted and its zone
mirrored around the trade's entry (the next bar's open), so the stop and the target land
exactly opposite the original trade's and the risk is the same. A signal on the last bar has no
entry; it is mirrored around its close and labels ``open``.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from smc_scanner.backtest._common import check_seed
from smc_scanner.backtest.outcome import ExitRules, label
from smc_scanner.backtest.replay import Signal, ZoneKey
from smc_scanner.backtest.stats import BacktestStats, summarise
from smc_scanner.config import MIN_BARS
from smc_scanner.models import BEARISH, BULLISH, Direction, ScanRow, ZoneKind
from smc_scanner.structure import atr_at

RANDOM_SYMBOL: Final = "random"  # the instrument count-only random signals report
RANDOM_STRATEGY: Final = "baseline-random"
DEFAULT_STOP_ATR: Final = 1.0  # far-edge distance, in ATR, when only a count is given
MAX_RANDOM_SIGNALS: Final = 1_000_000  # a count beyond this would only exhaust memory

SignalsOrCount = Sequence[Signal] | int


def _side(direction: Direction) -> str:
    return "bull" if direction == BULLISH else "bear"


def _close(ohlc: pd.DataFrame, index: int) -> float:
    return float(ohlc["close"].iloc[index])


def _stop_distance(ohlc: pd.DataFrame, signal: Signal) -> float:
    """How far the strategy put its far edge from the close, in the signal bar's ATR."""
    close = _close(ohlc, signal.bar_index)
    edge = signal.zone.bottom if signal.direction == BULLISH else signal.zone.top
    return max(0.0, signal.direction * (close - edge) / atr_at(ohlc, signal.bar_index))


_Shape = tuple[Direction, float, ZoneKind]  # direction, far-edge distance in ATR, zone kind


def _shapes(
    ohlc: pd.DataFrame, signals_or_n: SignalsOrCount, rng: np.random.Generator
) -> list[_Shape]:
    """What each random signal copies: a paired strategy signal's, or a coin and 1 ATR."""
    if isinstance(signals_or_n, int):
        longs = rng.integers(0, 2, size=signals_or_n).astype(bool)
        return [(BULLISH if long else BEARISH, DEFAULT_STOP_ATR, "OB") for long in longs]
    shapes = [(s.direction, _stop_distance(ohlc, s), s.zone.kind) for s in signals_or_n]
    return [shapes[int(i)] for i in rng.permutation(len(shapes))]


def _bars(n: int, start: int, end: int, rng: np.random.Generator) -> npt.NDArray[np.int64]:
    """``n`` sorted bars from ``[start, end)``, distinct while the window has room."""
    picked = rng.choice(np.arange(start, end), size=n, replace=n > end - start)
    return np.sort(picked)


def _count(signals_or_n: SignalsOrCount) -> int:
    if not isinstance(signals_or_n, int):
        return len(signals_or_n)
    if isinstance(signals_or_n, bool) or not 0 <= signals_or_n <= MAX_RANDOM_SIGNALS:
        raise ValueError(f"count must be an integer from 0 to {MAX_RANDOM_SIGNALS}")
    return signals_or_n


def _symbol(signals_or_n: SignalsOrCount) -> str:
    if isinstance(signals_or_n, int) or not signals_or_n:
        return RANDOM_SYMBOL
    return signals_or_n[0].row.instrument


def _random_signal(ohlc: pd.DataFrame, index: int, shape: _Shape, symbol: str) -> Signal:
    direction, distance, kind = shape
    close = _close(ohlc, index)
    width = distance * atr_at(ohlc, index)
    low, high = (close - width, close) if direction == BULLISH else (close, close + width)
    bar_time = str(ohlc["time"].iloc[index])
    row = ScanRow(
        instrument=symbol,
        status="TOUCHING",
        zone=f"{_side(direction)} {kind}",
        zone_low=low,
        zone_high=high,
        price=close,
        dist_atr=0.0,
        bias="range",
        in_ote=False,
        trendline_ok=False,
        ob_fvg=False,
        score=0,
        zone_age=0,
        prior_touches=0,
        bar_time=bar_time,
        strategy=RANDOM_STRATEGY,
    )
    return Signal(index, bar_time, row, ZoneKey(kind, direction, index, high, low))


def random_signals(
    ohlc: pd.DataFrame,
    signals_or_n: SignalsOrCount,
    *,
    seed: int,
    start: int = MIN_BARS,
    symbol: str | None = None,
) -> tuple[Signal, ...]:
    """As many random signals as ``signals_or_n`` (the strategy's signals on ``ohlc``, or a
    count), at bars from ``start`` to the last, in bar order; empty when no bar is eligible.
    ``symbol`` names their instrument; it defaults to the first strategy signal's."""
    check_seed(seed)
    if start < MIN_BARS - 1:
        raise ValueError(f"start must be at least {MIN_BARS - 1} (the ATR needs {MIN_BARS} bars)")
    n = _count(signals_or_n)
    if n == 0 or start >= len(ohlc):
        return ()
    name = _symbol(signals_or_n) if symbol is None else symbol
    rng = np.random.default_rng(seed)
    bars = _bars(n, start, len(ohlc), rng)
    shapes = _shapes(ohlc, signals_or_n, rng)
    return tuple(
        _random_signal(ohlc, int(bar), shape, name) for bar, shape in zip(bars, shapes, strict=True)
    )


def random_entries(
    ohlc: pd.DataFrame,
    signals_or_n: SignalsOrCount,
    rules: ExitRules,
    *,
    seed: int,
    start: int = MIN_BARS,
) -> BacktestStats:
    """The stats of ``random_signals`` labelled under ``rules``; ``seed`` also seeds the CI."""
    signals = random_signals(ohlc, signals_or_n, seed=seed, start=start)
    return summarise((label(ohlc, signal, rules) for signal in signals), seed=seed)


def _flipped(ohlc: pd.DataFrame, signal: Signal) -> Signal:
    entry_index = signal.bar_index + 1
    has_entry = entry_index < len(ohlc)
    pivot = float(ohlc["open"].iloc[entry_index]) if has_entry else _close(ohlc, signal.bar_index)
    direction: Direction = BEARISH if signal.direction == BULLISH else BULLISH
    top, bottom = 2 * pivot - signal.zone.bottom, 2 * pivot - signal.zone.top
    label_text = f"{_side(direction)} {signal.zone.kind}"
    row = replace(signal.row, zone=label_text, zone_low=bottom, zone_high=top)
    zone = replace(signal.zone, direction=direction, top=top, bottom=bottom)
    return replace(signal, row=row, zone=zone)


def flipped_signals(ohlc: pd.DataFrame, signals: Sequence[Signal]) -> tuple[Signal, ...]:
    """``signals`` (replayed on ``ohlc``) with each direction inverted and its zone mirrored."""
    return tuple(_flipped(ohlc, signal) for signal in signals)


def direction_flipped(
    ohlc: pd.DataFrame, signals: Sequence[Signal], rules: ExitRules, *, seed: int = 0
) -> BacktestStats:
    """The stats of ``flipped_signals`` labelled under ``rules``; ``seed`` seeds the CI."""
    check_seed(seed)
    flipped = flipped_signals(ohlc, signals)
    return summarise((label(ohlc, signal, rules) for signal in flipped), seed=seed)
