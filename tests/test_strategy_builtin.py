"""Shipped strategy presets: valid, resolvable, read-only, and smc-default as specified."""

import pandas as pd
import pytest
from conftest import Candle, frame
from mtf_support import TfLoader

from smc_scanner.config import DEFAULT_DEMO_SYMBOLS, DEFAULT_NEAR_ATR, DEFAULT_SWING_LENGTH
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.strategy import DEFAULT_STRATEGY_SLUG, Strategy
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES, PRESETS
from smc_scanner.strategy.conditions import resolve
from smc_scanner.strategy.engine import (
    scan_instrument_with_strategy,
    scan_watchlist_with_strategy,
    uses_mtf,
)


def test_presets_are_listed_in_order_and_keyed_by_slug() -> None:
    assert [preset.slug for preset in PRESETS] == [
        "smc-default",
        "fresh-ob-trend",
        "fvg-ote-reversal",
        "htf-aligned-touch",
        "valid-ob",
    ]
    assert list(BUILTIN_STRATEGIES) == [preset.slug for preset in PRESETS]
    assert all(BUILTIN_STRATEGIES[preset.slug] is preset for preset in PRESETS)


def test_builtin_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        BUILTIN_STRATEGIES["mine"] = PRESETS[0]  # type: ignore[index]


def test_smc_default_is_todays_scan() -> None:
    preset = BUILTIN_STRATEGIES[DEFAULT_STRATEGY_SLUG]

    assert preset.zone_kinds == ("FVG", "OB")
    assert preset.statuses == ("TOUCHING", "NEAR")
    assert (preset.swing_length, preset.near_atr) == (DEFAULT_SWING_LENGTH, DEFAULT_NEAR_ATR)
    assert preset.require == ()
    assert [ref.key for ref in preset.score] == ["aligned", "in_ote", "trendline_ok", "stacked"]
    assert preset.min_score == 0
    assert (preset.mtf, preset.require_htf_aligned) == (False, False)


def test_valid_ob_is_as_specified() -> None:
    preset = BUILTIN_STRATEGIES["valid-ob"]

    assert preset.name == "Valid order block"
    assert preset.zone_kinds == ("OB",)
    assert preset.statuses == ("TOUCHING", "NEAR")
    assert (preset.swing_length, preset.near_atr) == (DEFAULT_SWING_LENGTH, DEFAULT_NEAR_ATR)
    assert [ref.key for ref in preset.require] == [
        "aligned",
        "fresh",
        "ob_swept_prior",
        "displacement_fvg",
    ]
    assert [ref.key for ref in preset.score] == [
        "bos_confirmed",
        "in_ote",
        "trendline_ok",
        "htf_aligned",
    ]
    assert preset.min_score == 1
    assert (preset.mtf, preset.require_htf_aligned) == (False, False)


def test_valid_ob_scans_fresh_zones_only() -> None:
    assert BUILTIN_STRATEGIES["valid-ob"].to_scan_options().all_touches is False


def _path(closes: list[float], start: float) -> list[Candle]:
    """Candles that walk ``closes``, each opening at the previous close with 0.3 wicks."""
    candles: list[Candle] = []
    for close in closes:
        candles.append((start, max(start, close) + 0.3, min(start, close) - 0.3, close))
        start = close
    return candles


def _leg(start: float, end: float, bars: int) -> list[float]:
    return [start + (end - start) * (step + 1) / bars for step in range(bars)]


def _valid_ob_frame(third: Candle) -> pd.DataFrame:
    """HH + HL swings, then a pullback whose last candle (the block, 107-108.8) sweeps the prior
    low; an impulse with ``third`` after it, a rally that breaks structure and a first return."""
    trend = _leg(100, 112, 12) + _leg(112, 104, 12) + _leg(104, 118, 12) + _leg(118, 108, 12)
    block: Candle = (108.0, 108.8, 107.0, 107.5)
    impulse: Candle = (107.5, 111.0, 107.4, 110.8)
    rally = _path(_leg(third[3], 124, 10) + _leg(124, 110.5, 12), start=third[3])
    first_return: Candle = (110.5, 110.8, 108.6, 109.0)  # low 108.6 touches the block top
    return frame([*_path(trend, 100.0), block, impulse, third, *rally, first_return])


def test_valid_ob_finds_the_one_valid_block() -> None:
    ohlc = _valid_ob_frame((110.8, 114.3, 109.5, 114.0))  # low 109.5 leaves a gap above 108.8

    rows = scan_instrument_with_strategy("X", ohlc, BUILTIN_STRATEGIES["valid-ob"])

    assert [(row.zone, row.status, row.zone_low, row.zone_high) for row in rows] == [
        ("bull OB", "TOUCHING", 107.0, 108.8)
    ]
    assert rows[0].conditions == {
        "aligned": True,
        "fresh": True,
        "ob_swept_prior": True,
        "displacement_fvg": True,
        "bos_confirmed": True,
        "in_ote": False,
        "trendline_ok": False,
        "htf_aligned": True,  # no higher timeframe given: unknown passes
    }
    assert rows[0].score == 2


def test_valid_ob_watchlist_scan_reads_the_break_of_structure() -> None:
    ohlc = _valid_ob_frame((110.8, 114.3, 109.5, 114.0))
    loader = TfLoader({("X", "1h"): ohlc})  # no 4h frame: the HTF is unknown and passes

    result = scan_watchlist_with_strategy(loader, ["X"], "1h", 100, BUILTIN_STRATEGIES["valid-ob"])

    assert [row.conditions["bos_confirmed"] for row in result.rows] == [True]
    assert ("X", "4h") in loader.calls  # htf_aligned loads the higher timeframe


def test_valid_ob_drops_the_block_when_the_third_candle_re_enters_it() -> None:
    ohlc = _valid_ob_frame((110.8, 114.3, 108.5, 114.0))  # low 108.5 is inside the block

    assert scan_instrument_with_strategy("X", ohlc, BUILTIN_STRATEGIES["valid-ob"]) == []
    # The block is still a fresh, aligned OB: only the missing FVG drops it.
    fresh = scan_instrument_with_strategy("X", ohlc, BUILTIN_STRATEGIES["fresh-ob-trend"])
    assert [(row.zone, row.zone_low, row.zone_high) for row in fresh] == [("bull OB", 107.0, 108.8)]


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset.slug)
def test_every_preset_is_builtin_valid_and_resolvable(preset: Strategy) -> None:
    assert preset.builtin is True
    assert Strategy.model_validate_json(preset.model_dump_json()) == preset
    for ref in (*preset.require, *preset.score):
        assert resolve(ref).key == ref.key


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset.slug)
def test_presets_using_htf_aligned_load_the_higher_timeframe(preset: Strategy) -> None:
    if "htf_aligned" in preset.condition_keys():
        assert uses_mtf(preset) is True


@pytest.fixture(scope="module")
def demo_frames() -> dict[str, pd.DataFrame]:
    loader = DemoLoader()
    return {symbol: loader.load(symbol, "1h", 500) for symbol in DEFAULT_DEMO_SYMBOLS}


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset.slug)
def test_preset_rows_honour_the_preset(
    preset: Strategy, demo_frames: dict[str, pd.DataFrame]
) -> None:
    for symbol, ohlc in demo_frames.items():
        for row in scan_instrument_with_strategy(symbol, ohlc, preset):
            assert row.strategy == preset.slug
            assert row.zone.split()[1] in preset.zone_kinds
            assert row.status in preset.statuses
            assert all(row.conditions[ref.key] for ref in preset.require)
            assert row.score >= preset.min_score
            assert set(row.conditions) == set(preset.condition_keys())
