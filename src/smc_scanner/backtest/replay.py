"""Point-in-time replay of a strategy over one frame.

At each bar ``i`` the strategy scans ``ohlc.iloc[:i+1]`` exactly as a live scan would on that
candle, so a signal can only use bars known at the time. Swings are confirmed ``swing_length``
bars after they form and every zone rule reads the frame it is given, so nothing after ``i``
leaks in. A zone signals once, on its first hit; later re-touches are not new signals.

No higher timeframe is replayed: ``htf_bias`` is None, so an ``htf_aligned`` condition passes
and a strategy's ``mtf``/``require_htf_aligned`` flags have no effect here.
"""

from dataclasses import dataclass
from typing import Final

import pandas as pd

from smc_scanner.config import MIN_BARS
from smc_scanner.models import BEARISH, BULLISH, Direction, ScanRow, ZoneKind
from smc_scanner.scanner import ScanOptions
from smc_scanner.strategy.engine import scan_instrument_with_strategy
from smc_scanner.strategy.models import Strategy

_SIDES: Final[dict[str, Direction]] = {"bull": BULLISH, "bear": BEARISH}
_KINDS: Final[dict[str, ZoneKind]] = {"OB": "OB", "FVG": "FVG"}


@dataclass(frozen=True)
class ZoneKey:
    """A zone's identity on one frame: the same zone keeps it on every later prefix."""

    kind: ZoneKind
    direction: Direction
    formed_index: int
    top: float
    bottom: float


@dataclass(frozen=True)
class Signal:
    """The first bar on which a zone became a strategy hit."""

    bar_index: int
    bar_time: str
    row: ScanRow
    zone: ZoneKey

    @property
    def direction(self) -> Direction:
        return self.zone.direction


def zone_key(row: ScanRow, bar_index: int) -> ZoneKey:
    """The identity of the zone behind ``row``, scanned with ``bar_index`` as the latest bar."""
    side, _, kind = row.zone.partition(" ")
    if side not in _SIDES or kind not in _KINDS:
        raise ValueError(f"unrecognised zone label {row.zone!r}")
    return ZoneKey(
        _KINDS[kind], _SIDES[side], bar_index - row.zone_age, row.zone_high, row.zone_low
    )


def scan_at(
    symbol: str,
    ohlc: pd.DataFrame,
    strategy: Strategy | None,
    index: int,
    *,
    options: ScanOptions | None = None,
) -> list[ScanRow]:
    """The live scan as it would have run with bar ``index`` as the latest candle."""
    if not 0 <= index < len(ohlc):
        raise IndexError(f"bar index {index} is outside a frame of {len(ohlc)} bars")
    return scan_instrument_with_strategy(symbol, ohlc.iloc[: index + 1], strategy, options=options)


def replay(
    symbol: str,
    ohlc: pd.DataFrame,
    strategy: Strategy | None,
    *,
    options: ScanOptions | None = None,
    start: int = MIN_BARS,
    stride: int = 1,
) -> tuple[Signal, ...]:
    """One ``Signal`` per zone, on the first bar from ``start`` on where it is a hit.

    ``stride`` > 1 scans every ``stride``-th bar only: faster but approximate, since a hit
    between sampled bars is signalled late (if still a hit) or missed.
    """
    if start < MIN_BARS - 1:
        raise ValueError(f"start must be at least {MIN_BARS - 1} (a scan needs {MIN_BARS} bars)")
    if stride < 1:
        raise ValueError("stride must be at least 1")
    seen: set[ZoneKey] = set()
    signals: list[Signal] = []
    for index in range(start, len(ohlc), stride):
        for row in scan_at(symbol, ohlc, strategy, index, options=options):
            key = zone_key(row, index)
            if key not in seen:
                seen.add(key)
                signals.append(Signal(index, row.bar_time, row, key))
    return tuple(signals)
