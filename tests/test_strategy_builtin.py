"""Shipped strategy presets: valid, resolvable, read-only, and smc-default as specified."""

import pandas as pd
import pytest

from smc_scanner.config import DEFAULT_DEMO_SYMBOLS, DEFAULT_NEAR_ATR, DEFAULT_SWING_LENGTH
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.strategy import DEFAULT_STRATEGY_SLUG, Strategy
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES, PRESETS
from smc_scanner.strategy.conditions import resolve
from smc_scanner.strategy.engine import scan_instrument_with_strategy


def test_presets_are_listed_in_order_and_keyed_by_slug() -> None:
    assert [preset.slug for preset in PRESETS] == [
        "smc-default",
        "fresh-ob-trend",
        "fvg-ote-reversal",
        "htf-aligned-touch",
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


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset.slug)
def test_every_preset_is_builtin_valid_and_resolvable(preset: Strategy) -> None:
    assert preset.builtin is True
    assert Strategy.model_validate_json(preset.model_dump_json()) == preset
    for ref in (*preset.require, *preset.score):
        assert resolve(ref).key == ref.key


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset.slug)
def test_presets_using_htf_aligned_turn_on_mtf(preset: Strategy) -> None:
    if "htf_aligned" in preset.condition_keys():
        assert preset.mtf is True


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
