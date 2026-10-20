"""Context builder: field coverage, rounding, determinism, size cap, missing data."""

import json
import math
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from conftest import FLAT, FVG_SETUP, OB_SETUP, OB_TOUCH_LAST, TOUCH_LAST, frame

from smc_scanner.ai import build_context as exported_build_context
from smc_scanner.ai import context as context_module
from smc_scanner.ai.context import (
    MAX_CANDLES,
    MAX_CONTEXT_CHARS,
    MAX_SWINGS_PER_SIDE,
    ContextTooLargeError,
    ScanContext,
    build_context,
    price_decimals,
    round_price,
)
from smc_scanner.models import (
    BEARISH,
    BULLISH,
    Bias,
    Direction,
    ScanRow,
    Structure,
    Swing,
    ZoneState,
)
from smc_scanner.scanner import ScanOptions, scan_instrument
from smc_scanner.structure import analyse_structure, confirmed_swing_frame, confirmed_swings
from smc_scanner.zones import evaluate_zones

SWING = 2
Candle = tuple[float, float, float, float]


def _mirror(candles: list[Candle], axis: float = 200.0) -> list[Candle]:
    return [(axis - o, axis - lo, axis - hi, axis - c) for o, hi, lo, c in candles]


def _pipeline(ohlc: pd.DataFrame, zone: str) -> tuple[ScanRow, Structure, ZoneState, list[Swing]]:
    """Run the scanner steps by hand to get the inputs ``build_context`` takes."""
    options = ScanOptions(swing_length=SWING)
    row = next(r for r in scan_instrument("TEST", ohlc, options) if r.zone == zone)
    swings = confirmed_swings(ohlc, SWING)
    structure = analyse_structure(ohlc, swings)
    states = evaluate_zones(ohlc, confirmed_swing_frame(ohlc, swings), structure.atr, 0.5)
    state = next(
        s
        for s in states
        if (s.zone.bottom, s.zone.top) == (row.zone_low, row.zone_high)
        and s.zone.formed_index == len(ohlc) - 1 - row.zone_age
    )
    return row, structure, state, swings


def _context(ohlc: pd.DataFrame, zone: str, **kwargs: int) -> ScanContext:
    row, structure, state, swings = _pipeline(ohlc, zone)
    return build_context(ohlc, row, structure, state, swings, timeframe="1h", **kwargs)


def _dump(context: ScanContext) -> str:
    return json.dumps(context, sort_keys=True)


def _alternating(count: int, base: float) -> list[Swing]:
    swings: list[Swing] = []
    for i in range(1, count + 1):
        kind: Direction = BULLISH if i % 2 else BEARISH
        swings.append(Swing(i, kind, base + i))
    return swings


BULL_FVG = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST])
BEAR_FVG = frame(_mirror([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST]))
BULL_OB = frame([FLAT] * 16 + [*OB_SETUP, OB_TOUCH_LAST])


def test_bullish_fvg_context_has_every_field() -> None:
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")

    ctx = _context(BULL_FVG, "bull FVG")

    assert ctx["symbol"] == "TEST"
    assert ctx["timeframe"] == "1h"
    assert ctx["bar_time"] == "2026-01-01T21:00:00"
    assert ctx["zone"] == {
        "kind": "FVG",
        "direction": "bullish",
        "low": 101.0,
        "high": 103.0,
        "age_bars": 4,
        "prior_touches": 0,
    }
    assert ctx["price"] == 103.0
    assert ctx["atr"] == round(structure.atr, 3)
    assert ctx["dist_atr"] == 0.0
    assert ctx["status"] == "TOUCHING"
    assert ctx["bias"] == structure.bias
    assert state.zone.kind == "FVG"
    assert set(ctx["score"]) == {"aligned", "in_ote", "trendline_ok", "stacked", "score"}
    assert ctx["score"]["score"] == row.score
    assert ctx["score"]["in_ote"] == row.in_ote
    assert ctx["score"]["stacked"] == row.ob_fvg
    assert len(ctx["candles"]) == len(BULL_FVG)  # fewer than MAX_CANDLES available
    assert set(ctx["candles"][0]) == {"time", "open", "high", "low", "close"}
    assert set(ctx["swings"]) == {"highs", "lows"}


def test_score_breakdown_sums_to_the_row_score() -> None:
    for ohlc, zone in ((BULL_FVG, "bull FVG"), (BEAR_FVG, "bear FVG"), (BULL_OB, "bull OB")):
        score = _context(ohlc, zone)["score"]
        parts = [score["aligned"], score["in_ote"], score["trendline_ok"], score["stacked"]]
        assert score["score"] == sum(parts)


def test_bearish_fvg_context_uses_the_bearish_bands() -> None:
    row, structure, _, _ = _pipeline(BEAR_FVG, "bear FVG")

    ctx = _context(BEAR_FVG, "bear FVG")

    assert ctx["zone"]["direction"] == "bearish"
    assert (ctx["zone"]["low"], ctx["zone"]["high"]) == (97.0, 99.0)
    expected = structure.ote_bearish
    if expected is None:
        assert ctx["ote"] is None
    else:
        assert ctx["ote"] == {"low": round(expected[0], 3), "high": round(expected[1], 3)}
    line = structure.trendline_bearish
    assert ctx["trendline"] == (None if line is None else round(line, 3))
    assert row.status == ctx["status"]


def test_bullish_ob_context() -> None:
    ctx = _context(BULL_OB, "bull OB")

    assert ctx["zone"]["kind"] == "OB"
    assert (ctx["zone"]["low"], ctx["zone"]["high"]) == (99.5, 102.0)


def test_ote_band_and_trendline_come_from_the_structure_for_the_zone_direction() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")
    structure = replace(structure, ote_bullish=(102.123456, 104.0), trendline_bullish=101.55555)

    ctx = build_context(BULL_FVG, row, structure, state, swings, timeframe="1h")

    assert state.zone.direction == BULLISH
    assert ctx["ote"] == {"low": 102.123, "high": 104.0}
    assert ctx["trendline"] == 101.556


def test_zone_without_ote_or_trendline_gives_nulls() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")
    structure = replace(structure, ote_bullish=None, trendline_bullish=None)

    ctx = build_context(BULL_FVG, row, structure, state, swings, timeframe="1h")

    assert ctx["ote"] is None
    assert ctx["trendline"] is None


def test_swings_are_capped_ordered_and_carry_index_time_price() -> None:
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")

    ctx = build_context(
        BULL_FVG,
        row,
        structure,
        state,
        _alternating(10, 100.0),
        timeframe="1h",
        max_swings_per_side=2,
    )

    assert [s["index"] for s in ctx["swings"]["highs"]] == [7, 9]
    assert [s["index"] for s in ctx["swings"]["lows"]] == [8, 10]
    first = ctx["swings"]["highs"][0]
    assert first["price"] == 107.0
    assert first["time"] == "2026-01-01T07:00:00"


def test_no_swings_gives_empty_lists() -> None:
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")

    ctx = build_context(BULL_FVG, row, structure, state, [], timeframe="1h")

    assert ctx["swings"] == {"highs": [], "lows": []}


def test_swing_outside_the_frame_has_null_time() -> None:
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")

    ctx = build_context(
        BULL_FVG, row, structure, state, [Swing(999, BULLISH, 100.0)], timeframe="1h"
    )

    assert ctx["swings"]["highs"][0]["time"] is None


def test_short_history_returns_all_available_candles() -> None:
    short = BULL_FVG.iloc[-10:].reset_index(drop=True)
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    ctx = build_context(short, row, structure, state, swings, timeframe="1h")

    assert len(ctx["candles"]) == 10
    assert ctx["candles"][-1]["close"] == 103.0


def test_candles_are_the_last_n_without_volume() -> None:
    ctx = _context(BULL_FVG, "bull FVG", candle_count=5)

    assert [c["close"] for c in ctx["candles"]] == [105.0, 106.0, 107.0, 105.0, 103.0]
    assert all("volume" not in c for c in ctx["candles"])


def test_inputs_are_not_mutated() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")
    before = BULL_FVG.copy(deep=True)
    swings_before = list(swings)

    build_context(BULL_FVG, row, structure, state, swings, timeframe="1h")

    pd.testing.assert_frame_equal(BULL_FVG, before)
    assert swings == swings_before


def test_output_is_json_serialisable_and_deterministic() -> None:
    first = _dump(_context(BULL_FVG, "bull FVG"))
    second = _dump(_context(BULL_FVG, "bull FVG"))

    assert first == second
    assert json.loads(first)["symbol"] == "TEST"


def test_key_order_is_stable_without_sort_keys() -> None:
    first = json.dumps(_context(BULL_FVG, "bull FVG"))
    second = json.dumps(_context(BULL_FVG, "bull FVG"))

    assert first == second
    assert first.startswith('{"symbol": "TEST", "timeframe": "1h"')


def test_size_stays_under_the_character_ceiling_with_a_full_window() -> None:
    long_frame = frame([FLAT] * 400 + [*FVG_SETUP, TOUCH_LAST])
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")
    row = replace(row, bar_time=str(long_frame["time"].iloc[-1]))

    ctx = build_context(
        long_frame, row, structure, state, _alternating(199, 12345.6789), timeframe="1h"
    )

    assert len(ctx["candles"]) == MAX_CANDLES
    assert len(_dump(ctx)) < MAX_CONTEXT_CHARS


@pytest.mark.parametrize(
    ("price", "decimals"),
    [
        (0.00012345, 6),
        (0.5, 6),
        (1.08123, 5),
        (9.99, 5),
        (10.0, 3),
        (149.123, 3),
        (999.9, 3),
        (1000.0, 2),
        (65432.123, 2),
    ],
)
def test_price_decimals_follow_magnitude(price: float, decimals: int) -> None:
    assert price_decimals(price) == decimals


def test_price_decimals_uses_absolute_value_and_handles_non_finite() -> None:
    assert price_decimals(-65000.0) == 2
    assert price_decimals(float("nan")) == 2
    assert price_decimals(0.0) == 6


def test_round_price_casts_numpy_scalars_to_plain_floats() -> None:
    for value in (np.float32(1.08), np.float64(1.08), np.int64(1)):
        assert type(round_price(value, 5)) is float
    assert round_price(np.float32(1.08), 5) == 1.08


def test_round_price_maps_nan_and_inf_to_none_and_normalises_negative_zero() -> None:
    assert round_price(float("nan"), 2) is None
    assert round_price(math.inf, 2) is None
    assert round_price(-math.inf, 2) is None
    assert round_price(None, 2) is None
    assert str(round_price(-0.0001, 2)) == "0.0"


def test_float32_candles_serialise_like_float64() -> None:
    f32 = BULL_FVG.copy()
    for col in ("open", "high", "low", "close"):
        f32[col] = f32[col].astype(np.float32)
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    ctx = build_context(f32, row, structure, state, swings, timeframe="1h")

    assert _dump(ctx) == _dump(
        build_context(BULL_FVG, row, structure, state, swings, timeframe="1h")
    )


def test_nan_candle_value_becomes_null() -> None:
    bad = BULL_FVG.copy()
    bad.loc[len(bad) - 2, "high"] = float("nan")
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    ctx = build_context(bad, row, structure, state, swings, timeframe="1h")

    assert ctx["candles"][-2]["high"] is None
    json.dumps(ctx, allow_nan=False)


def test_prices_use_precision_inferred_from_the_price() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")
    fx = replace(row, price=1.0812349999, zone_low=1.081234567, zone_high=1.082)
    fx_structure = replace(structure, atr=0.00123456789)

    ctx = build_context(BULL_FVG, fx, fx_structure, state, swings, timeframe="1h")

    assert ctx["price"] == 1.08123
    assert ctx["zone"]["low"] == 1.08123
    assert ctx["atr"] == 0.00123


GOLDEN = (
    '{"atr": 2.75, "bar_time": "2026-01-01T21:00:00", "bias": "range", "candles": ['
    '{"close": 107.0, "high": 108.0, "low": 105.0, "open": 106.0, "time": "2026-01-01T19:00:00"}, '
    '{"close": 105.0, "high": 108.0, "low": 104.0, "open": 107.0, "time": "2026-01-01T20:00:00"}, '
    '{"close": 103.0, "high": 106.0, "low": 102.5, "open": 105.0, "time": "2026-01-01T21:00:00"}], '
    '"dist_atr": 0.0, "ote": {"high": 102.438, "low": 100.926}, "price": 103.0, '
    '"score": {"aligned": false, "in_ote": true, "score": 2, "stacked": true, '
    '"trendline_ok": false}, "status": "TOUCHING", '
    '"swings": {"highs": [{"index": 3, "price": 101.0, "time": "2026-01-01T03:00:00"}, '
    '{"index": 19, "price": 108.0, "time": "2026-01-01T19:00:00"}], '
    '"lows": [{"index": 15, "price": 99.0, "time": "2026-01-01T15:00:00"}]}, '
    '"symbol": "TEST", "timeframe": "1h", "trendline": null, '
    '"zone": {"age_bars": 4, "direction": "bullish", "high": 103.0, "kind": "FVG", '
    '"low": 101.0, "prior_touches": 0}}'
)


def test_golden_json_for_a_bullish_fvg_hit() -> None:
    assert _dump(_context(BULL_FVG, "bull FVG", candle_count=3)) == GOLDEN


def _with(ohlc: pd.DataFrame, zone: str, **overrides: Any) -> ScanContext:
    row, structure, state, swings = _pipeline(ohlc, zone)
    structure = replace(structure, **{k: v for k, v in overrides.items() if k in _STRUCT})
    row = replace(row, **{k: v for k, v in overrides.items() if k not in _STRUCT})
    return build_context(ohlc, row, structure, state, swings, timeframe="1h")


_STRUCT = {"bias", "atr", "ote_bearish", "ote_bullish", "trendline_bearish", "trendline_bullish"}


@pytest.mark.parametrize(
    ("ohlc", "zone", "bias", "aligned"),
    [
        (BULL_FVG, "bull FVG", "bullish", True),
        (BEAR_FVG, "bear FVG", "bearish", True),
        (BULL_FVG, "bull FVG", "bearish", False),
        (BEAR_FVG, "bear FVG", "bullish", False),
        (BULL_FVG, "bull FVG", "range", False),
    ],
)
def test_aligned_comes_from_bias_and_zone_direction(
    ohlc: pd.DataFrame, zone: str, bias: Bias, aligned: bool
) -> None:
    ctx = _with(ohlc, zone, bias=bias)

    assert ctx["score"]["aligned"] is aligned


def test_bearish_zone_reads_a_populated_bearish_band_and_trendline() -> None:
    ctx = _with(
        BEAR_FVG,
        "bear FVG",
        ote_bearish=(97.5, 98.25),
        ote_bullish=(1.0, 2.0),
        trendline_bearish=99.1234,
        trendline_bullish=5.0,
    )

    assert ctx["ote"] == {"low": 97.5, "high": 98.25}
    assert ctx["trendline"] == 99.123


def test_options_are_clamped_to_the_caps() -> None:
    long_frame = frame([FLAT] * 100 + [*FVG_SETUP, TOUCH_LAST])
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")
    row = replace(row, bar_time=str(long_frame["time"].iloc[-1]))

    ctx = build_context(
        long_frame,
        row,
        structure,
        state,
        _alternating(60, 100.0),
        timeframe="1h",
        candle_count=10_000,
        max_swings_per_side=10_000,
    )

    assert len(ctx["candles"]) == MAX_CANDLES
    assert len(ctx["swings"]["highs"]) == MAX_SWINGS_PER_SIDE
    assert len(ctx["swings"]["lows"]) == MAX_SWINGS_PER_SIDE


def test_negative_options_give_empty_sections() -> None:
    ctx = _context(BULL_FVG, "bull FVG", candle_count=-5, max_swings_per_side=-1)

    assert ctx["candles"] == []
    assert ctx["swings"] == {"highs": [], "lows": []}


def test_six_decimal_prices_stay_under_the_ceiling_in_the_worst_case() -> None:
    small = frame([(0.123456, 0.223456, 0.023456, 0.123456)] * 400)
    row, structure, state, _ = _pipeline(BULL_FVG, "bull FVG")
    row = replace(row, price=0.123456, bar_time=str(small["time"].iloc[-1]))
    swings = _alternating(50, 0.123456)

    ctx = build_context(small, row, structure, state, swings, timeframe="1h")

    assert len(ctx["candles"]) == MAX_CANDLES
    assert len(_dump(ctx)) < MAX_CONTEXT_CHARS


def test_payload_over_the_ceiling_raises_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_module, "MAX_CONTEXT_CHARS", 500)

    with pytest.raises(ContextTooLargeError):
        _context(BULL_FVG, "bull FVG")


@pytest.mark.parametrize("symbol", ["", "EUR USD", "EUR/USD", "A" * 33, "EUR\nUSD", "ignore this"])
def test_bad_symbols_are_rejected(symbol: str) -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    with pytest.raises(ValueError, match="symbol"):
        build_context(
            BULL_FVG, replace(row, instrument=symbol), structure, state, swings, timeframe="1h"
        )


def test_symbol_alphabet_allows_dots_dashes_and_underscores() -> None:
    assert _with(BULL_FVG, "bull FVG", instrument="BRK.B-X_1")["symbol"] == "BRK.B-X_1"


@pytest.mark.parametrize("timeframe", ["", "1 h", "x" * 9, "1h; drop"])
def test_bad_timeframes_are_rejected(timeframe: str) -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    with pytest.raises(ValueError, match="timeframe"):
        build_context(BULL_FVG, row, structure, state, swings, timeframe=timeframe)


def test_missing_columns_raise() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    with pytest.raises(ValueError, match="columns"):
        build_context(
            BULL_FVG.drop(columns=["high"]), row, structure, state, swings, timeframe="1h"
        )


def test_empty_frame_raises() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    with pytest.raises(ValueError, match="empty"):
        build_context(BULL_FVG.iloc[:0], row, structure, state, swings, timeframe="1h")


def test_last_candle_time_must_match_the_row() -> None:
    row, structure, state, swings = _pipeline(BULL_FVG, "bull FVG")

    with pytest.raises(ValueError, match="bar_time"):
        build_context(BULL_FVG.iloc[:-1], row, structure, state, swings, timeframe="1h")


def test_build_context_is_re_exported_from_the_package() -> None:
    assert exported_build_context is build_context
