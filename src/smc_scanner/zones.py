"""Zone detection (via smartmoneyconcepts) and the scanner's own touch/invalidation rules.

The library only *detects* FVGs and OBs. Touch counting, freshness, invalidation and the
TOUCHING/NEAR status follow the rules below, which are stricter than the library's
``MitigatedIndex``:

* FVG: usable only once fully formed before the latest candle; touches count from two
  candles after the middle candle.
* OB: touches count only after price has first moved completely away from the block.
* A zone is invalidated when a candle before the latest one traded through its far side
  (wick-based), or when the latest close sits beyond the far side without overlapping.
"""

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from smc_scanner.models import BEARISH, BULLISH, Direction, Status, Zone, ZoneState
from smc_scanner.smc_lib import smc

# Candles after the middle candle of an FVG before a touch counts (the third candle
# completes the gap, so the first possible touch is the one after it).
FVG_TOUCH_OFFSET = 2

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Candles:
    """Price arrays extracted once per instrument, shared by every zone evaluation."""

    high: FloatArray
    low: FloatArray
    close: FloatArray

    @classmethod
    def from_frame(cls, ohlc: pd.DataFrame) -> "Candles":
        return cls(
            high=ohlc["high"].to_numpy(dtype=float),
            low=ohlc["low"].to_numpy(dtype=float),
            close=ohlc["close"].to_numpy(dtype=float),
        )

    @property
    def last_index(self) -> int:
        return len(self.high) - 1


def _direction(value: float) -> Direction:
    return BULLISH if int(value) == 1 else BEARISH


def detect_fvgs(ohlc: pd.DataFrame) -> list[Zone]:
    """Fair value gaps fully formed before the latest candle."""
    frame = smc.fvg(ohlc)
    last_index = len(ohlc) - 1
    zones: list[Zone] = []
    for index, flag, top, bottom in zip(
        frame.index,
        frame["FVG"].to_numpy(),
        frame["Top"].to_numpy(),
        frame["Bottom"].to_numpy(),
        strict=True,
    ):
        if np.isnan(flag):
            continue
        formed = int(index)
        # The gap is between candle formed-1 and formed+1; it must close before the last bar.
        if formed + 1 >= last_index:
            continue
        zones.append(
            Zone(
                kind="FVG",
                direction=_direction(flag),
                top=float(top),
                bottom=float(bottom),
                formed_index=formed,
                touch_start=formed + FVG_TOUCH_OFFSET,
            )
        )
    return zones


def _move_away_index(
    candles: Candles, direction: Direction, top: float, bottom: float, formed: int
) -> int | None:
    """First candle after the block that sits entirely outside it on the trade side."""
    start = formed + 1
    if direction == BULLISH:
        clear = np.flatnonzero(candles.low[start:] > top)
    else:
        clear = np.flatnonzero(candles.high[start:] < bottom)
    return start + int(clear[0]) if clear.size else None


def detect_obs(ohlc: pd.DataFrame, swing_frame: pd.DataFrame) -> list[Zone]:
    """Order blocks that price has already moved away from (so a touch can be counted).

    The library stores block edges as float32; they are exactly the block candle's high
    and low, so the float64 candle values are used instead.
    """
    frame = smc.ob(ohlc, swing_frame)
    candles = Candles.from_frame(ohlc)
    zones: list[Zone] = []
    for index, flag in zip(frame.index, frame["OB"].to_numpy(), strict=True):
        if np.isnan(flag) or int(flag) == 0 or int(index) >= candles.last_index:
            continue
        formed = int(index)
        direction = _direction(flag)
        top = float(candles.high[formed])
        bottom = float(candles.low[formed])
        moved_away = _move_away_index(candles, direction, top, bottom, formed)
        if moved_away is None:
            continue
        zones.append(
            Zone(
                kind="OB",
                direction=direction,
                top=top,
                bottom=bottom,
                formed_index=formed,
                touch_start=moved_away + 1,
            )
        )
    return zones


def _traded_through_before_last(candles: Candles, zone: Zone) -> bool:
    start, last = zone.formed_index + 1, candles.last_index
    if zone.direction == BULLISH:
        return bool((candles.low[start:last] < zone.bottom).any())
    return bool((candles.high[start:last] > zone.top).any())


def _prior_touches(candles: Candles, zone: Zone) -> int:
    start, last = zone.touch_start, candles.last_index
    if start >= last:
        return 0
    overlaps = (candles.low[start:last] <= zone.top) & (candles.high[start:last] >= zone.bottom)
    return int(np.count_nonzero(overlaps))


def _signed_distance(zone: Zone, close: float) -> float:
    """Distance from the close to the near edge; negative means beyond the far side."""
    if zone.direction == BULLISH:
        return close - zone.top
    return zone.bottom - close


def evaluate_zone(candles: Candles, zone: Zone, atr_value: float, near_atr: float) -> ZoneState:
    """Count prior touches, check invalidation and classify the latest candle.

    The status is independent of freshness; ``select_hits`` applies the fresh-only filter.
    """
    if not math.isfinite(atr_value) or atr_value <= 0:
        raise ValueError("ATR must be a positive finite number")
    last = candles.last_index
    invalidated = _traded_through_before_last(candles, zone)
    prior_touches = _prior_touches(candles, zone)

    status: Status | None = None
    if zone.overlaps_candle(candles.high[last], candles.low[last]):
        distance_atr = 0.0
        status = "TOUCHING"
    else:
        signed = _signed_distance(zone, float(candles.close[last]))
        if signed < 0:
            invalidated = True
        distance_atr = signed / atr_value
        if 0 <= distance_atr <= near_atr:
            status = "NEAR"

    return ZoneState(
        zone=zone,
        prior_touches=prior_touches,
        invalidated=invalidated,
        status=status,
        distance_atr=round(float(distance_atr), 3),
    )


def evaluate_zones(
    ohlc: pd.DataFrame,
    swing_frame: pd.DataFrame,
    atr_value: float,
    near_atr: float,
) -> list[ZoneState]:
    """Every detected zone evaluated on the latest candle, invalidated ones dropped."""
    candles = Candles.from_frame(ohlc)
    zones = detect_fvgs(ohlc) + detect_obs(ohlc, swing_frame)
    states = (evaluate_zone(candles, zone, atr_value, near_atr) for zone in zones)
    return [state for state in states if not state.invalidated]


def select_hits(states: list[ZoneState], all_touches: bool) -> list[ZoneState]:
    """Zones to report: TOUCHING or NEAR, and fresh unless ``all_touches`` is set."""
    return [
        state
        for state in states
        if state.status is not None and (all_touches or state.prior_touches == 0)
    ]
