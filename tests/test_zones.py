"""FVG/OB touch, freshness, invalidation and status rules on hand-built candles."""

import pandas as pd
import pytest
from conftest import (
    FLAT,
    FVG_BOTTOM,
    FVG_SETUP,
    FVG_TOP,
    OB_BOTTOM,
    OB_SETUP,
    OB_TOP,
    TOUCH_LAST,
    Candle,
    frame,
    with_warmup,
)

from smc_scanner.models import BEARISH, BULLISH, ScanRow, Zone
from smc_scanner.scanner import ScanOptions, scan_instrument
from smc_scanner.structure import atr, confirmed_swing_frame, confirmed_swings
from smc_scanner.zones import Candles, detect_fvgs, detect_obs, evaluate_zone, evaluate_zones

SWING = 2


def _rows(ohlc: pd.DataFrame, zone: str, all_touches: bool = False) -> list[ScanRow]:
    options = ScanOptions(swing_length=SWING, all_touches=all_touches)
    return [row for row in scan_instrument("TEST", ohlc, options) if row.zone == zone]


def _fvg_rows(ohlc: pd.DataFrame, all_touches: bool = False) -> list[ScanRow]:
    return _rows(ohlc, "bull FVG", all_touches)


def test_fresh_bullish_fvg_touched_on_last_candle_is_reported(fvg_touching: pd.DataFrame) -> None:
    rows = _fvg_rows(fvg_touching)

    assert len(rows) == 1
    row = rows[0]
    assert row.status == "TOUCHING"
    assert (row.zone_low, row.zone_high) == (FVG_BOTTOM, FVG_TOP)
    assert row.dist_atr == 0
    assert row.prior_touches == 0
    assert row.zone_age == 4  # middle candle is 4 bars before the latest


def test_previously_tested_gap_is_not_reported(fvg_tested_before: pd.DataFrame) -> None:
    assert _fvg_rows(fvg_tested_before) == []


def test_previously_tested_gap_is_reported_with_all_touches(
    fvg_tested_before: pd.DataFrame,
) -> None:
    rows = _fvg_rows(fvg_tested_before, all_touches=True)

    assert len(rows) == 1
    assert rows[0].status == "TOUCHING"
    assert rows[0].prior_touches == 1


def test_gap_price_traded_through_is_not_reported(fvg_traded_through: pd.DataFrame) -> None:
    assert _fvg_rows(fvg_traded_through) == []
    assert _fvg_rows(fvg_traded_through, all_touches=True) == []


def _near_frame(distance_in_atr: float, setup: list[Candle] | None = None) -> pd.DataFrame:
    """The latest close sits ``distance_in_atr`` above the gap top (ATR of the final frame)."""
    candles = list(setup or FVG_SETUP)
    probe = with_warmup([*candles, (105.0, 105.5, 104.5, 105.0)])
    close = FVG_TOP + distance_in_atr * atr(probe)
    return with_warmup([*candles, (close + 0.2, close + 0.5, close - 0.1, close)])


def test_untouched_gap_within_near_limit_is_near() -> None:
    rows = _fvg_rows(_near_frame(0.4))

    assert len(rows) == 1
    assert rows[0].status == "NEAR"
    assert rows[0].dist_atr == pytest.approx(0.4, abs=0.02)


def test_untouched_gap_beyond_near_limit_is_not_reported() -> None:
    assert _fvg_rows(_near_frame(0.6)) == []


def test_tested_gap_can_be_near_with_all_touches() -> None:
    tested = list(FVG_SETUP)
    tested[4] = (107.0, 108.0, 102.8, 105.0)
    ohlc = _near_frame(0.4, tested)

    assert _fvg_rows(ohlc) == []
    rows = _fvg_rows(ohlc, all_touches=True)
    assert len(rows) == 1
    assert rows[0].status == "NEAR"
    assert rows[0].prior_touches == 1


def test_fvg_not_fully_formed_before_latest_candle_is_skipped() -> None:
    # The gap closes on the latest candle itself, so it cannot be used yet.
    ohlc = with_warmup(FVG_SETUP[:3])

    assert detect_fvgs(ohlc) == []


def test_fvg_touch_window_starts_two_candles_after_middle(fvg_touching: pd.DataFrame) -> None:
    zones = detect_fvgs(fvg_touching)

    assert len(zones) == 1
    assert zones[0].touch_start == zones[0].formed_index + 2


def _mirror(candles: list[Candle], axis: float = 200.0) -> list[Candle]:
    return [(axis - o, axis - lo, axis - hi, axis - c) for o, hi, lo, c in candles]


def test_fresh_bearish_fvg_touched_on_last_candle_is_reported() -> None:
    ohlc = frame(_mirror([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST]))

    rows = _rows(ohlc, "bear FVG")

    assert len(rows) == 1
    assert rows[0].status == "TOUCHING"
    assert (rows[0].zone_low, rows[0].zone_high) == (200 - FVG_TOP, 200 - FVG_BOTTOM)


def test_bearish_gap_traded_through_is_not_reported() -> None:
    broken = list(FVG_SETUP)
    broken[4] = (107.0, 108.0, 100.5, 105.0)
    ohlc = frame(_mirror([FLAT] * 16 + [*broken, TOUCH_LAST]))

    assert _rows(ohlc, "bear FVG", all_touches=True) == []


def test_fresh_bullish_ob_touched_on_last_candle_is_reported(ob_touching: pd.DataFrame) -> None:
    rows = _rows(ob_touching, "bull OB")

    assert len(rows) == 1
    assert rows[0].status == "TOUCHING"
    assert (rows[0].zone_low, rows[0].zone_high) == (OB_BOTTOM, OB_TOP)
    # The candle that overlapped the block before price moved away does not count.
    assert rows[0].prior_touches == 0


def test_ob_touches_count_only_after_price_moved_away(ob_touching: pd.DataFrame) -> None:
    swings = confirmed_swings(ob_touching, SWING)
    zones = detect_obs(ob_touching, confirmed_swing_frame(ob_touching, swings))
    bullish = [zone for zone in zones if zone.direction == BULLISH and zone.top == OB_TOP]

    assert len(bullish) == 1
    moved_away = bullish[0].formed_index + 2  # first candle whose low is above the block
    assert bullish[0].touch_start == moved_away + 1


def test_ob_edges_are_exact_candle_values_not_float32() -> None:
    """The library returns float32 edges; an equal-price retest must still count."""
    scale = 100.0
    setup = [
        (o / scale, h / scale, lo / scale, c / scale) for o, h, lo, c in [FLAT] * 16 + OB_SETUP
    ]
    exact_edge_touch: Candle = (1.05, 1.06, OB_TOP / scale, 1.03)  # low == block top (1.02)
    ohlc = frame([*setup, exact_edge_touch])

    rows = _rows(ohlc, "bull OB")

    assert len(rows) == 1
    assert rows[0].status == "TOUCHING"
    assert rows[0].zone_high == 1.02 and rows[0].zone_low == 0.995


def test_zone_with_latest_close_beyond_far_side_is_invalidated() -> None:
    ohlc = with_warmup([*FVG_SETUP, (100.0, 100.5, 99.0, 99.5)])  # whole candle below the gap
    zone = Zone("FVG", BULLISH, top=FVG_TOP, bottom=FVG_BOTTOM, formed_index=17, touch_start=19)

    state = evaluate_zone(Candles.from_frame(ohlc), zone, atr(ohlc), 0.5)

    assert state.invalidated
    assert state.status is None


def test_bearish_zone_with_latest_close_above_is_invalidated() -> None:
    ohlc = with_warmup([*FVG_SETUP, (110.0, 111.0, 109.0, 110.5)])
    zone = Zone("FVG", BEARISH, top=105.0, bottom=104.0, formed_index=17, touch_start=19)

    state = evaluate_zone(Candles.from_frame(ohlc), zone, atr(ohlc), 0.5)

    assert state.invalidated


def test_evaluate_zone_rejects_bad_atr(fvg_touching: pd.DataFrame) -> None:
    zone = Zone("FVG", BULLISH, top=FVG_TOP, bottom=FVG_BOTTOM, formed_index=17, touch_start=19)
    with pytest.raises(ValueError, match="ATR"):
        evaluate_zone(Candles.from_frame(fvg_touching), zone, 0.0, 0.5)


def test_evaluate_zones_drops_invalidated(fvg_traded_through: pd.DataFrame) -> None:
    swings = confirmed_swings(fvg_traded_through, SWING)
    states = evaluate_zones(
        fvg_traded_through,
        confirmed_swing_frame(fvg_traded_through, swings),
        atr(fvg_traded_through),
        0.5,
    )

    assert all(not state.invalidated for state in states)
    assert not any(s.zone.kind == "FVG" and s.zone.top == FVG_TOP for s in states)
