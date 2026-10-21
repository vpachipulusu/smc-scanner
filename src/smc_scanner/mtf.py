"""Multi-timeframe helpers: bias and last break of structure on a neighbouring timeframe.

Higher-timeframe (HTF) alignment is shown next to a hit and is an opt-in filter; it never
adds to the 0-4 confluence score. Everything here is pure over frames that were already
loaded, and degrades to "unknown" (None) instead of raising: a missing or malformed
neighbour frame must never fail a scan or an analysis.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import pandas as pd

from smc_scanner.config import neighbour_timeframes
from smc_scanner.models import Bias, ScanRow
from smc_scanner.smc_lib import smc
from smc_scanner.structure import bias_from_swings, confirmed_swing_frame, confirmed_swings

log = logging.getLogger(__name__)

# (symbol, timeframe) -> the frame already loaded for it, or None.
FrameLookup = Callable[[str, str], pd.DataFrame | None]


@dataclass(frozen=True)
class LastBos:
    """The most recent break of structure: its direction, the broken level and the break bar."""

    direction: Literal["bullish", "bearish"]
    level: float
    time: str


@dataclass(frozen=True)
class TimeframeView:
    timeframe: str
    bias: Bias
    last_bos: LastBos | None


@dataclass(frozen=True)
class MtfInputs:
    """What the AI context needs: the neighbour timeframes and, when available, their views."""

    higher: str | None
    lower: str | None
    htf: TimeframeView | None
    ltf: TimeframeView | None


_BULL_PREFIX: Final = "bull"


def row_direction(row: ScanRow) -> Literal["bullish", "bearish"]:
    """The hit's direction, from its zone label ("bull OB" / "bear FVG")."""
    return "bullish" if row.zone.startswith(_BULL_PREFIX) else "bearish"


def htf_allows(row: ScanRow, bias: Bias | None) -> bool:
    """False when a known HTF bias does not confirm the hit's direction. A range is not
    confirmation (as in ``scoring.is_aligned``); an unknown (None) bias passes."""
    return bias is None or bias == row_direction(row)


def _last_bos(ohlc: pd.DataFrame, swing_length: int) -> LastBos | None:
    swings = confirmed_swings(ohlc, swing_length)
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
    return LastBos(
        direction="bullish" if kind[position] > 0 else "bearish",
        level=float(frame["Level"].iloc[position]),
        time=pd.Timestamp(ohlc["time"].iloc[int(broken[position])]).isoformat(),
    )


def htf_bias(ohlc: pd.DataFrame, swing_length: int) -> Bias:
    """Structure bias of a (higher-timeframe) frame."""
    return bias_from_swings(confirmed_swings(ohlc, swing_length))


def timeframe_view(ohlc: pd.DataFrame, timeframe: str, swing_length: int) -> TimeframeView:
    return TimeframeView(
        timeframe=timeframe,
        bias=htf_bias(ohlc, swing_length),
        last_bos=_last_bos(ohlc, swing_length),
    )


def _safe_view(
    lookup: FrameLookup, symbol: str, timeframe: str | None, swing_length: int
) -> TimeframeView | None:
    if timeframe is None:
        return None
    try:
        frame = lookup(symbol, timeframe)
        return None if frame is None else timeframe_view(frame, timeframe, swing_length)
    except Exception as exc:  # noqa: BLE001 - a bad neighbour frame must not fail the analysis
        log.warning("%s: no %s view (%s)", symbol, timeframe, type(exc).__name__)
        return None


def build_mtf_inputs(
    row: ScanRow, timeframe: str, swing_length: int, lookup: FrameLookup
) -> MtfInputs:
    """Views of the timeframes either side of ``timeframe`` for one hit that is going to the AI."""
    higher, lower = neighbour_timeframes(timeframe)
    return MtfInputs(
        higher=higher,
        lower=lower,
        htf=_safe_view(lookup, row.instrument, higher, swing_length),
        ltf=_safe_view(lookup, row.instrument, lower, swing_length),
    )
