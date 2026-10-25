"""Market structure on the latest candle: ATR, confirmed swings, bias, OTE band, trendline
and the last break of structure.

All functions take an OHLC DataFrame with a RangeIndex and lower-case
``open/high/low/close`` columns (see ``loaders.base.normalise``).
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_scanner.config import ATR_PERIOD, OTE_HIGH, OTE_LOW
from smc_scanner.models import BEARISH, BULLISH, Bias, Direction, Structure, Swing
from smc_scanner.smc_lib import smc


def atr(ohlc: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """Average true range over the last ``period`` candles (simple mean of true range)."""
    if len(ohlc) < period + 1:
        raise ValueError(f"ATR({period}) needs at least {period + 1} candles, got {len(ohlc)}")
    high = ohlc["high"].to_numpy(dtype=float)
    low = ohlc["low"].to_numpy(dtype=float)
    prev_close = ohlc["close"].shift(1).to_numpy(dtype=float)
    true_range = np.maximum.reduce(
        [high - low, np.abs(high - prev_close), np.abs(low - prev_close)]
    )
    value = float(np.nanmean(true_range[-period:]))
    if not np.isfinite(value) or value <= 0:
        raise ValueError("ATR is not a positive finite number; the data is flat or malformed")
    return value


def atr_at(ohlc: pd.DataFrame, index: int, period: int = ATR_PERIOD) -> float:
    """``atr`` with bar ``index`` as the latest candle. It reads only the last ``period`` true
    ranges, so only those bars and the close before them are sliced: the same value as on the
    whole prefix, without an O(n) pass per call on a long frame."""
    return atr(ohlc.iloc[max(0, index - period) : index + 1], period)


def raw_swings(ohlc: pd.DataFrame, swing_length: int) -> pd.DataFrame:
    """The library's swing frame (``HighLow``, ``Level``), unfiltered."""
    frame: pd.DataFrame = smc.swing_highs_lows(ohlc, swing_length=swing_length)
    return frame


def confirmed_swings(ohlc: pd.DataFrame, swing_length: int) -> list[Swing]:
    """Swings confirmed by ``swing_length`` candles after them.

    The library tags the first and last candles as swings to close the sequence; those
    and anything within ``swing_length`` of the end are dropped.
    """
    frame = raw_swings(ohlc, swing_length)
    last_index = len(ohlc) - 1
    swings: list[Swing] = []
    for index, kind, level in zip(
        frame.index, frame["HighLow"].to_numpy(), frame["Level"].to_numpy(), strict=True
    ):
        if np.isnan(kind) or index <= 0 or index > last_index - swing_length:
            continue
        direction: Direction = BULLISH if int(kind) == 1 else BEARISH
        swings.append(Swing(index=int(index), kind=direction, level=float(level)))
    return swings


def confirmed_swing_frame(ohlc: pd.DataFrame, swings: list[Swing]) -> pd.DataFrame:
    """A library-shaped swing frame built only from confirmed swings (input to ``smc.ob``)."""
    high_low = np.full(len(ohlc), np.nan)
    level = np.full(len(ohlc), np.nan)
    for swing in swings:
        high_low[swing.index] = swing.kind
        level[swing.index] = swing.level
    return pd.DataFrame({"HighLow": high_low, "Level": level})


def _last_two(swings: list[Swing], kind: Direction) -> tuple[Swing, Swing] | None:
    matching = [swing for swing in swings if swing.kind == kind]
    if len(matching) < 2:
        return None
    return matching[-2], matching[-1]


def bias_from_swings(swings: list[Swing]) -> Bias:
    """HH + HL is bullish, LH + LL is bearish, anything else is range."""
    highs = _last_two(swings, BULLISH)
    lows = _last_two(swings, BEARISH)
    if highs is None or lows is None:
        return "range"
    higher_high = highs[1].level > highs[0].level
    higher_low = lows[1].level > lows[0].level
    lower_high = highs[1].level < highs[0].level
    lower_low = lows[1].level < lows[0].level
    if higher_high and higher_low:
        return "bullish"
    if lower_high and lower_low:
        return "bearish"
    return "range"  # mixed, or equal levels


def ote_band(
    ohlc: pd.DataFrame, swings: list[Swing], direction: Direction
) -> tuple[float, float] | None:
    """Price band of the 0.618-0.786 retracement.

    Bullish: from the last confirmed swing low to the highest high since.
    Bearish: from the last confirmed swing high to the lowest low since.
    Returns ``(low, high)`` or None when there is no swing or no range.
    """
    anchor_kind: Direction = BEARISH if direction == BULLISH else BULLISH
    anchors = [swing for swing in swings if swing.kind == anchor_kind]
    if not anchors:
        return None
    anchor = anchors[-1]
    if direction == BULLISH:
        extreme = float(ohlc["high"].iloc[anchor.index :].max())
        span = extreme - anchor.level
        if span <= 0:
            return None
        return extreme - OTE_HIGH * span, extreme - OTE_LOW * span
    extreme = float(ohlc["low"].iloc[anchor.index :].min())
    span = anchor.level - extreme
    if span <= 0:
        return None
    return extreme + OTE_LOW * span, extreme + OTE_HIGH * span


def trendline_value(ohlc: pd.DataFrame, swings: list[Swing], direction: Direction) -> float | None:
    """Line through the last two confirmed swing lows (bullish) or highs (bearish),
    projected to the latest candle."""
    anchor_kind: Direction = BEARISH if direction == BULLISH else BULLISH
    pair = _last_two(swings, anchor_kind)
    if pair is None:
        return None
    first, second = pair
    slope = (second.level - first.level) / (second.index - first.index)
    last_index = len(ohlc) - 1
    return second.level + slope * (last_index - second.index)


@dataclass(frozen=True)
class BreakOfStructure:
    """A break of structure: its direction, the broken level and the candle that closed past it."""

    direction: Literal["bullish", "bearish"]
    level: float
    index: int


def last_break_of_structure(ohlc: pd.DataFrame, swings: list[Swing]) -> BreakOfStructure | None:
    """The most recent close-confirmed break of structure over the confirmed ``swings``."""
    if not swings:
        return None
    frame = smc.bos_choch(ohlc, confirmed_swing_frame(ohlc, swings), close_break=True)
    broken = frame["BrokenIndex"].to_numpy(dtype=float)
    kind = frame["BOS"].to_numpy(dtype=float)
    reached = ~np.isnan(kind) & ~np.isnan(broken) & (broken > 0) & (broken < len(ohlc))
    candidates = np.flatnonzero(reached)
    if candidates.size == 0:
        return None
    position = int(candidates[np.argmax(broken[candidates])])
    return BreakOfStructure(
        direction="bullish" if kind[position] > 0 else "bearish",
        level=float(frame["Level"].iloc[position]),
        index=int(broken[position]),
    )


def analyse_structure(
    ohlc: pd.DataFrame, swings: list[Swing], *, with_bos: bool = False
) -> Structure:
    """The structure on the latest candle. ``last_bos`` is found only ``with_bos`` (the library
    loop costs about as much as the rest of a scan); otherwise it is None."""
    last_bos = last_break_of_structure(ohlc, swings) if with_bos else None
    return Structure(
        atr=atr(ohlc),
        bias=bias_from_swings(swings),
        ote_bullish=ote_band(ohlc, swings, BULLISH),
        ote_bearish=ote_band(ohlc, swings, BEARISH),
        trendline_bullish=trendline_value(ohlc, swings, BULLISH),
        trendline_bearish=trendline_value(ohlc, swings, BEARISH),
        last_bos=None if last_bos is None else last_bos.direction,
    )
