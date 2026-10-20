"""Confluence score out of 4 for a zone on the latest candle."""

from dataclasses import dataclass

import pandas as pd

from smc_scanner.models import BULLISH, Structure, ZoneState


@dataclass(frozen=True)
class Confluence:
    aligned: bool
    in_ote: bool
    trendline_ok: bool
    stacked: bool

    @property
    def score(self) -> int:
        return int(self.aligned) + int(self.in_ote) + int(self.trendline_ok) + int(self.stacked)


def is_aligned(state: ZoneState, structure: Structure) -> bool:
    """The zone direction matches a trending bias; a range is never aligned."""
    if structure.bias == "range":
        return False
    return (structure.bias == "bullish") == (state.zone.direction == BULLISH)


def _in_ote(state: ZoneState, structure: Structure) -> bool:
    band = structure.ote_bullish if state.zone.direction == BULLISH else structure.ote_bearish
    if band is None:
        return False
    return state.zone.overlaps_band(band[0], band[1])


def _trendline_ok(state: ZoneState, structure: Structure, ohlc: pd.DataFrame) -> bool:
    """Bullish: the latest low holds above the swing-low line. Bearish: mirrored."""
    last = ohlc.iloc[-1]
    if state.zone.direction == BULLISH:
        line = structure.trendline_bullish
        return line is not None and float(last["low"]) >= line
    line = structure.trendline_bearish
    return line is not None and float(last["high"]) <= line


def _stacked(state: ZoneState, valid: list[ZoneState]) -> bool:
    """An OB and an FVG of the same direction overlap in price."""
    zone = state.zone
    return any(
        other.zone.kind != zone.kind
        and other.zone.direction == zone.direction
        and other.zone.overlaps_band(zone.bottom, zone.top)
        for other in valid
    )


def score_zone(
    state: ZoneState, structure: Structure, valid: list[ZoneState], ohlc: pd.DataFrame
) -> Confluence:
    return Confluence(
        aligned=is_aligned(state, structure),
        in_ote=_in_ote(state, structure),
        trendline_ok=_trendline_ok(state, structure, ohlc),
        stacked=_stacked(state, valid),
    )
