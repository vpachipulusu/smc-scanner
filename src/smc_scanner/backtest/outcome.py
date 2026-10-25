"""Label a signal with a simulated trade and raw forward returns.

Entry is the open of the bar after the signal. The stop sits beyond the zone's far edge (below
``zone_low`` for a long, above ``zone_high`` for a short) plus an ATR buffer; the target is
``rr`` times the risk from entry. Bars are walked forward from the entry bar:

* a bar that reaches both stop and target is a loss (the order inside a bar is unknown);
* a bar that opens beyond the stop fills at its open (a gap), so a loss can exceed 1R;
* the target fills on a touch, at the target, even on a gap through it (conservative);
* after ``time_stop_bars`` bars without either, the trade closes at that bar's close.

``spread`` (price units) is charged once per trade. A signal whose full ``time_stop_bars``
horizon is not in the frame is ``open`` with no R, even when an early exit is visible: keeping
only the trades that resolved early would bias the stats towards fast outcomes. An entry that
opens at or beyond the stop, or so close to it that the risk is under ``min_risk_atr`` ATR, is
``void`` (no trade): a sliver of risk would turn the spread and any gap into huge R values.
"""

import math
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from smc_scanner.backtest.replay import Signal
from smc_scanner.config import MAX_BARS
from smc_scanner.models import BULLISH, Direction
from smc_scanner.structure import atr_at

ExitReason = Literal["target", "stop", "time", "open", "void"]
FORWARD_HORIZONS: Final = (5, 10, 20)  # bars; Outcome has one fwd_<h>_atr field per horizon
MAX_RR: Final = 100.0
MAX_ATR_MULTIPLE: Final = 50.0  # cap on stop_buffer_atr and min_risk_atr
MAX_SPREAD: Final = 1e9  # price units; keeps R arithmetic far from overflow

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ExitRules:
    """How a signal becomes a trade. ``spread`` is in price units, paid once per trade."""

    rr: float = 2.0
    stop_buffer_atr: float = 0.0
    time_stop_bars: int = 50
    spread: float = 0.0
    min_risk_atr: float = 0.1

    def __post_init__(self) -> None:
        if not 0 < _number("rr", self.rr) <= MAX_RR:
            raise ValueError(f"rr must be above 0 and at most {MAX_RR:g}")
        for name in ("stop_buffer_atr", "min_risk_atr"):
            if not 0 <= _number(name, getattr(self, name)) <= MAX_ATR_MULTIPLE:
                raise ValueError(f"{name} must be between 0 and {MAX_ATR_MULTIPLE:g}")
        if not 0 <= _number("spread", self.spread) <= MAX_SPREAD:
            raise ValueError(f"spread must be between 0 and {MAX_SPREAD:g}")
        if not isinstance(self.time_stop_bars, int) or isinstance(self.time_stop_bars, bool):
            raise ValueError("time_stop_bars must be an integer")
        if not 1 <= self.time_stop_bars <= MAX_BARS:
            raise ValueError(f"time_stop_bars must be between 1 and {MAX_BARS}")


def _number(name: str, value: object) -> float:
    """``value`` as a finite float; bools and non-numbers are rejected."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class Outcome:
    """A labelled signal. ``r_multiple`` is None for ``open`` and ``void``: leave those out of
    stats. ``bars_held`` counts bars from the entry bar to the exit bar inclusive; for ``open``
    it is the bars available before the frame ended, for ``void`` 0. Forward returns are from
    the signal bar's close, signed so positive favours the trade, in ATR units; None past the
    end of the frame."""

    signal: Signal
    exit_reason: ExitReason
    r_multiple: float | None
    bars_held: int
    entry: float | None
    stop: float | None
    target: float | None
    exit_price: float | None
    atr: float
    fwd_5_atr: float | None
    fwd_10_atr: float | None
    fwd_20_atr: float | None


@dataclass(frozen=True)
class _Prices:
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray

    @classmethod
    def from_frame(cls, ohlc: pd.DataFrame) -> "_Prices":
        return cls(
            *(ohlc[column].to_numpy(dtype=float) for column in ("open", "high", "low", "close"))
        )


@dataclass(frozen=True)
class _Trade:
    direction: Direction
    entry_index: int
    entry: float
    stop: float
    target: float

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    def r(self, exit_price: float, spread: float) -> float:
        return (self.direction * (exit_price - self.entry) - spread) / self.risk


def _checked_atr(ohlc: pd.DataFrame, signal: Signal, value: float | None) -> float:
    if value is None:  # the signal bar's own ATR: nothing after it is read
        return atr_at(ohlc, signal.bar_index)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("ATR must be a positive finite number")
    return value


def _forward(close: FloatArray, signal: Signal, atr: float) -> tuple[float | None, ...]:
    base = float(close[signal.bar_index])
    return tuple(
        signal.direction * (float(close[signal.bar_index + h]) - base) / atr
        if signal.bar_index + h < len(close)
        else None
        for h in FORWARD_HORIZONS
    )


def _trade(prices: _Prices, signal: Signal, rules: ExitRules, atr: float) -> _Trade:
    direction = signal.direction
    entry_index = signal.bar_index + 1
    entry = float(prices.open[entry_index])
    buffer = rules.stop_buffer_atr * atr
    stop = signal.zone.bottom - buffer if direction == BULLISH else signal.zone.top + buffer
    target = entry + direction * rules.rr * abs(entry - stop)
    return _Trade(direction, entry_index, entry, stop, target)


def _bar_exit(trade: _Trade, prices: _Prices, j: int) -> tuple[ExitReason, float] | None:
    open_, high, low = float(prices.open[j]), float(prices.high[j]), float(prices.low[j])
    if trade.direction == BULLISH:
        stopped, reached, gapped = low <= trade.stop, high >= trade.target, open_ < trade.stop
    else:
        stopped, reached, gapped = high >= trade.stop, low <= trade.target, open_ > trade.stop
    if stopped:  # checked first: a bar reaching both is a loss
        return "stop", open_ if gapped else trade.stop
    if reached:
        return "target", trade.target
    return None


def _walk(trade: _Trade, prices: _Prices, time_stop: int) -> tuple[ExitReason, float | None, int]:
    """(reason, exit price, bars held) from the entry bar on."""
    last_bar = trade.entry_index + time_stop - 1
    if last_bar >= len(prices.close):
        return "open", None, len(prices.close) - trade.entry_index
    for j in range(trade.entry_index, last_bar + 1):
        hit = _bar_exit(trade, prices, j)
        if hit is not None:
            return hit[0], hit[1], j - trade.entry_index + 1
    return "time", float(prices.close[last_bar]), time_stop


def _void(trade: _Trade, min_risk: float) -> bool:
    """The entry opened at or beyond the stop, or leaves less than ``min_risk`` to it."""
    signed_risk = trade.direction * (trade.entry - trade.stop)
    return signed_risk <= 0 or signed_risk < min_risk


@dataclass(frozen=True)
class _Labeller:
    """What every outcome of one signal shares, whatever happens to the trade."""

    signal: Signal
    atr: float
    forward: tuple[float | None, ...]

    def outcome(
        self,
        reason: ExitReason,
        held: int,
        trade: _Trade | None = None,
        r: float | None = None,
        exit_price: float | None = None,
    ) -> Outcome:
        fwd_5, fwd_10, fwd_20 = self.forward
        return Outcome(
            signal=self.signal,
            exit_reason=reason,
            r_multiple=r,
            bars_held=held,
            entry=trade.entry if trade else None,
            stop=trade.stop if trade else None,
            target=trade.target if trade else None,
            exit_price=exit_price,
            atr=self.atr,
            fwd_5_atr=fwd_5,
            fwd_10_atr=fwd_10,
            fwd_20_atr=fwd_20,
        )


def label(
    ohlc: pd.DataFrame, signal: Signal, rules: ExitRules, atr: float | None = None
) -> Outcome:
    """Simulate ``signal`` on ``ohlc`` (the frame it was replayed on). ``atr`` defaults to the
    ATR of the frame up to the signal bar; it sizes the stop buffer and the forward returns."""
    atr_value = _checked_atr(ohlc, signal, atr)
    prices = _Prices.from_frame(ohlc)
    base = _Labeller(signal, atr_value, _forward(prices.close, signal, atr_value))
    if signal.bar_index + 1 >= len(ohlc):
        return base.outcome("open", 0)
    trade = _trade(prices, signal, rules, atr_value)
    if _void(trade, rules.min_risk_atr * atr_value):
        return base.outcome("void", 0, trade)
    reason, exit_price, held = _walk(trade, prices, rules.time_stop_bars)
    r = None if exit_price is None else trade.r(exit_price, rules.spread)
    return base.outcome(reason, held, trade, r, exit_price)
