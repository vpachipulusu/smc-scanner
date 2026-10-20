"""Compact, deterministic JSON-ready context for one scan hit (sent to an LLM instead of a chart).

Pure: no I/O, inputs are never mutated. The last candle in the frame is assumed to be a
closed bar (closed-bar filtering happens in the loaders).

Precision: candles carry none, so every price is rounded to a number of decimals inferred
from its magnitude (see ``price_decimals``): >=1000 -> 2, >=10 -> 3, >=1 -> 5, else 6. The
decimals come from the hit's latest price and are applied to every price in the payload.
"""

import json
import math
import re
from collections.abc import Sequence
from typing import Final, Literal, SupportsFloat, TypedDict

import pandas as pd

from smc_scanner.models import (
    BEARISH,
    BULLISH,
    Bias,
    Direction,
    ScanRow,
    Status,
    Structure,
    Swing,
    ZoneKind,
    ZoneState,
)
from smc_scanner.scoring import is_aligned

MAX_CANDLES: Final[int] = 30
MAX_SWINGS_PER_SIDE: Final[int] = 3
# Ceiling for the serialised payload (``json.dumps(..., sort_keys=True)``), in characters.
MAX_CONTEXT_CHARS: Final[int] = 12_000
RATIO_DECIMALS: Final[int] = 3  # dist_atr is a ratio, not a price

# Free text reaches the LLM only through these two fields, so both are restricted.
_SYMBOL_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,32}")
_TIMEFRAME_PATTERN: Final = re.compile(r"[A-Za-z0-9]{1,8}")
_REQUIRED_COLUMNS: Final[tuple[str, ...]] = ("time", "open", "high", "low", "close")

_FALLBACK_DECIMALS: Final[int] = 2
# (minimum absolute price, decimals), checked top-down.
_PRECISION_STEPS: Final[tuple[tuple[float, int], ...]] = ((1000.0, 2), (10.0, 3), (1.0, 5))
_SMALL_PRICE_DECIMALS: Final[int] = 6


class ContextTooLargeError(ValueError):
    """The serialised payload exceeds ``MAX_CONTEXT_CHARS``."""


class ZoneContext(TypedDict):
    kind: ZoneKind
    direction: Literal["bullish", "bearish"]
    low: float | None
    high: float | None
    age_bars: int
    prior_touches: int


class SwingContext(TypedDict):
    index: int
    time: str | None
    price: float | None


class SwingsContext(TypedDict):
    highs: list[SwingContext]
    lows: list[SwingContext]


class OteContext(TypedDict):
    low: float | None
    high: float | None


class ScoreContext(TypedDict):
    aligned: bool
    in_ote: bool
    trendline_ok: bool
    stacked: bool
    score: int


class CandleContext(TypedDict):
    time: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None


class ScanContext(TypedDict):
    symbol: str
    timeframe: str
    bar_time: str
    zone: ZoneContext
    price: float | None
    atr: float | None
    dist_atr: float | None
    status: Status
    bias: Bias
    swings: SwingsContext
    ote: OteContext | None
    trendline: float | None
    score: ScoreContext
    candles: list[CandleContext]


def price_decimals(reference: float) -> int:
    """Decimals for prices near ``reference`` (sign ignored); 2 when it is not finite."""
    magnitude = abs(reference)
    if not math.isfinite(magnitude):
        return _FALLBACK_DECIMALS
    for minimum, decimals in _PRECISION_STEPS:
        if magnitude >= minimum:
            return decimals
    return _SMALL_PRICE_DECIMALS


def round_price(value: SupportsFloat | None, decimals: int) -> float | None:
    """A plain ``float`` rounded to ``decimals``; None for None, NaN or infinity.

    Casting first turns float32 and numpy scalars into Python floats; ``+ 0.0`` turns -0.0
    into 0.0 so equal values always serialise identically.
    """
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, decimals) + 0.0


def _iso(value: pd.Timestamp | str) -> str:
    return pd.Timestamp(value).isoformat()


def _time_text(ohlc: pd.DataFrame, index: int) -> str | None:
    if not 0 <= index < len(ohlc):
        return None
    return _iso(ohlc["time"].iloc[index])


def _swing_contexts(
    ohlc: pd.DataFrame, swings: Sequence[Swing], kind: Direction, limit: int, decimals: int
) -> list[SwingContext]:
    matching = [swing for swing in swings if swing.kind == kind]
    recent = matching[-limit:] if limit > 0 else []
    return [
        SwingContext(
            index=int(swing.index),
            time=_time_text(ohlc, swing.index),
            price=round_price(swing.level, decimals),
        )
        for swing in recent
    ]


def _candle_contexts(ohlc: pd.DataFrame, count: int, decimals: int) -> list[CandleContext]:
    tail = ohlc.iloc[-count:] if count > 0 else ohlc.iloc[:0]
    times = [_iso(value) for value in tail["time"]]
    columns = {
        name: tail[name].to_numpy(dtype=float).tolist() for name in ("open", "high", "low", "close")
    }
    return [
        CandleContext(
            time=times[i],
            open=round_price(columns["open"][i], decimals),
            high=round_price(columns["high"][i], decimals),
            low=round_price(columns["low"][i], decimals),
            close=round_price(columns["close"][i], decimals),
        )
        for i in range(len(times))
    ]


def _score_context(row: ScanRow, structure: Structure, state: ZoneState) -> ScoreContext:
    return ScoreContext(
        aligned=is_aligned(state, structure),
        in_ote=row.in_ote,
        trendline_ok=row.trendline_ok,
        stacked=row.ob_fvg,
        score=int(row.score),
    )


def _validate(ohlc: pd.DataFrame, row: ScanRow, timeframe: str) -> None:
    if not _SYMBOL_PATTERN.fullmatch(row.instrument):
        raise ValueError("symbol must match [A-Za-z0-9._-]{1,32}")
    if not _TIMEFRAME_PATTERN.fullmatch(timeframe):
        raise ValueError("timeframe must match [A-Za-z0-9]{1,8}")
    missing = [name for name in _REQUIRED_COLUMNS if name not in ohlc.columns]
    if missing:
        raise ValueError(f"ohlc is missing columns: {', '.join(missing)}")
    if ohlc.empty:
        raise ValueError("ohlc is empty")
    if str(ohlc["time"].iloc[-1]) != row.bar_time:
        raise ValueError("ohlc last candle time does not match row.bar_time")


def build_context(
    ohlc: pd.DataFrame,
    row: ScanRow,
    structure: Structure,
    state: ZoneState,
    swings: Sequence[Swing],
    *,
    timeframe: str,
    candle_count: int = MAX_CANDLES,
    max_swings_per_side: int = MAX_SWINGS_PER_SIDE,
) -> ScanContext:
    """The payload for one hit. ``ohlc`` is the frame the hit was scanned on (last bar closed),
    ``swings`` its confirmed swings; ``row``, ``structure`` and ``state`` come from the scan.
    """
    _validate(ohlc, row, timeframe)
    candle_count = min(max(candle_count, 0), MAX_CANDLES)
    max_swings_per_side = min(max(max_swings_per_side, 0), MAX_SWINGS_PER_SIDE)
    decimals = price_decimals(row.price)
    bullish = state.zone.direction == BULLISH
    band = structure.ote_bullish if bullish else structure.ote_bearish
    line = structure.trendline_bullish if bullish else structure.trendline_bearish
    ote = (
        None
        if band is None
        else OteContext(low=round_price(band[0], decimals), high=round_price(band[1], decimals))
    )
    context = ScanContext(
        symbol=row.instrument,
        timeframe=timeframe,
        bar_time=_iso(ohlc["time"].iloc[-1]),
        zone=ZoneContext(
            kind=state.zone.kind,
            direction="bullish" if bullish else "bearish",
            low=round_price(row.zone_low, decimals),
            high=round_price(row.zone_high, decimals),
            age_bars=int(row.zone_age),
            prior_touches=int(row.prior_touches),
        ),
        price=round_price(row.price, decimals),
        atr=round_price(structure.atr, decimals),
        dist_atr=round_price(row.dist_atr, RATIO_DECIMALS),
        status=row.status,
        bias=structure.bias,
        swings=SwingsContext(
            highs=_swing_contexts(ohlc, swings, BULLISH, max_swings_per_side, decimals),
            lows=_swing_contexts(ohlc, swings, BEARISH, max_swings_per_side, decimals),
        ),
        ote=ote,
        trendline=round_price(line, decimals),
        score=_score_context(row, structure, state),
        candles=_candle_contexts(ohlc, candle_count, decimals),
    )
    if len(json.dumps(context, sort_keys=True)) >= MAX_CONTEXT_CHARS:
        raise ContextTooLargeError(f"context exceeds {MAX_CONTEXT_CHARS} characters")
    return context
