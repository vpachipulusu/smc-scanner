"""Confluence score: bias alignment, OTE overlap, trendline hold, OB+FVG stack."""

from dataclasses import replace
from typing import Any

from conftest import FLAT, frame

from smc_scanner.models import BEARISH, BULLISH, Direction, Structure, Zone, ZoneKind, ZoneState
from smc_scanner.scoring import score_zone


def _state(kind: ZoneKind, direction: Direction, bottom: float, top: float) -> ZoneState:
    zone = Zone(kind, direction, top=top, bottom=bottom, formed_index=1, touch_start=3)
    return ZoneState(zone, prior_touches=0, invalidated=False, status="TOUCHING", distance_atr=0)


_BASE = Structure(
    atr=2.0,
    bias="range",
    ote_bullish=None,
    ote_bearish=None,
    trendline_bullish=None,
    trendline_bearish=None,
)


def _structure(**overrides: Any) -> Structure:
    return replace(_BASE, **overrides)


OHLC = frame([FLAT] * 3 + [(100.0, 106.0, 103.0, 105.0)])  # latest low 103, high 106


def test_all_four_points_for_a_fully_confluent_bullish_zone() -> None:
    fvg = _state("FVG", BULLISH, 101, 103)
    ob = _state("OB", BULLISH, 100, 102)  # overlaps the FVG in price
    structure = _structure(bias="bullish", ote_bullish=(102.0, 104.0), trendline_bullish=102.5)

    result = score_zone(fvg, structure, [fvg, ob], OHLC)

    assert (result.aligned, result.in_ote, result.trendline_ok, result.stacked) == (
        True,
        True,
        True,
        True,
    )
    assert result.score == 4


def test_zero_in_a_range_with_nothing_else() -> None:
    fvg = _state("FVG", BULLISH, 101, 103)

    assert score_zone(fvg, _structure(), [fvg], OHLC).score == 0


def test_bearish_zone_is_not_aligned_with_bullish_bias() -> None:
    bear = _state("FVG", BEARISH, 108, 110)

    assert not score_zone(bear, _structure(bias="bullish"), [bear], OHLC).aligned
    assert score_zone(bear, _structure(bias="bearish"), [bear], OHLC).aligned


def test_ote_checks_the_band_of_the_zone_direction() -> None:
    fvg = _state("FVG", BULLISH, 101, 103)
    structure = _structure(ote_bullish=(104.0, 105.0), ote_bearish=(101.0, 103.0))

    assert not score_zone(fvg, structure, [fvg], OHLC).in_ote


def test_trendline_broken_when_latest_low_is_below_line() -> None:
    fvg = _state("FVG", BULLISH, 101, 103)

    assert not score_zone(fvg, _structure(trendline_bullish=103.5), [fvg], OHLC).trendline_ok


def test_bearish_trendline_holds_when_latest_high_is_below_line() -> None:
    bear = _state("FVG", BEARISH, 108, 110)

    assert score_zone(bear, _structure(trendline_bearish=106.5), [bear], OHLC).trendline_ok
    assert not score_zone(bear, _structure(trendline_bearish=105.5), [bear], OHLC).trendline_ok


def test_stack_requires_same_direction_and_other_kind() -> None:
    fvg = _state("FVG", BULLISH, 101, 103)
    same_kind = _state("FVG", BULLISH, 102, 104)
    other_direction = _state("OB", BEARISH, 102, 104)
    far_away = _state("OB", BULLISH, 90, 95)

    others = [fvg, same_kind, other_direction, far_away]
    assert not score_zone(fvg, _structure(), others, OHLC).stacked
