"""Immutable value types passed between the structure, zone, scoring and report layers."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

Direction = Literal[1, -1]
ZoneKind = Literal["FVG", "OB"]
Bias = Literal["bullish", "bearish", "range"]
Status = Literal["TOUCHING", "NEAR"]

BULLISH: Direction = 1
BEARISH: Direction = -1


@dataclass(frozen=True)
class Swing:
    """A confirmed swing point: ``kind`` is 1 for a swing high, -1 for a swing low."""

    index: int
    kind: Direction
    level: float


@dataclass(frozen=True)
class Structure:
    """Market context on the latest candle."""

    atr: float
    bias: Bias
    # (low, high) price band of the 0.618-0.786 retracement, or None when undefined.
    ote_bullish: tuple[float, float] | None
    ote_bearish: tuple[float, float] | None
    # Trendline value projected to the latest candle, or None without two swings.
    trendline_bullish: float | None
    trendline_bearish: float | None


@dataclass(frozen=True)
class Zone:
    """A detected order block or fair value gap.

    ``formed_index`` is the candle the library flags (the middle candle of an FVG, the
    block candle of an OB). ``touch_start`` is the first candle index at which a touch
    counts: ``formed_index + 2`` for an FVG, the candle after price first moved away for an OB.
    """

    kind: ZoneKind
    direction: Direction
    top: float
    bottom: float
    formed_index: int
    touch_start: int

    def overlaps_candle(self, high: float, low: float) -> bool:
        return low <= self.top and high >= self.bottom

    def overlaps_band(self, band_low: float, band_high: float) -> bool:
        return self.bottom <= band_high and self.top >= band_low


@dataclass(frozen=True)
class ZoneState:
    """A zone evaluated against the latest candle."""

    zone: Zone
    prior_touches: int
    invalidated: bool
    status: Status | None
    distance_atr: float


@dataclass(frozen=True)
class ScanRow:
    """One reported hit: an instrument whose latest candle is touching or near a zone."""

    instrument: str
    status: Status
    zone: str
    zone_low: float
    zone_high: float
    price: float
    dist_atr: float
    bias: Bias
    in_ote: bool
    trendline_ok: bool
    ob_fvg: bool
    score: int
    zone_age: int
    prior_touches: int
    bar_time: str
    # The strategy that produced the row; matches ``strategy.DEFAULT_STRATEGY_SLUG`` (a literal
    # here: the strategy package imports this module).
    strategy: str = "smc-default"
    # Every condition the strategy evaluated, by key. A plain dict on purpose (``asdict`` cannot
    # deep-copy a MappingProxyType), built fresh per row; treat it as read-only. Kept out of the
    # hash because a dict is unhashable.
    conditions: Mapping[str, bool] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, eq=False)  # eq=False: comparing frames element-wise is ambiguous
class ZoneContext:
    """Everything a strategy condition may read about one candidate zone on the latest candle."""

    state: ZoneState
    structure: Structure
    valid: Sequence[ZoneState]  # every valid zone on the frame, for cross-zone checks
    ohlc: pd.DataFrame
    last_index: int
    htf_bias: Bias | None  # None when the higher timeframe is off or unknown
