"""ATR, confirmed swings, bias, OTE band and trendline."""

import pandas as pd
import pytest
from conftest import FLAT, Candle, frame

from smc_scanner.models import BEARISH, BULLISH, Swing
from smc_scanner.structure import (
    analyse_structure,
    atr,
    bias_from_swings,
    confirmed_swings,
    ote_band,
    trendline_value,
)


def _zigzag(levels: list[float], width: int = 3) -> pd.DataFrame:
    """Candles whose highs/lows walk between successive levels, ``width`` candles per leg."""
    candles: list[Candle] = []
    for start, end in zip(levels, levels[1:], strict=False):
        for step in range(width):
            a = start + (end - start) * step / width
            b = start + (end - start) * (step + 1) / width
            candles.append((a, max(a, b) + 0.1, min(a, b) - 0.1, b))
    return frame(candles)


def test_atr_is_mean_true_range_of_last_period() -> None:
    ohlc = frame([FLAT] * 20)

    assert atr(ohlc) == pytest.approx(2.0)


def test_atr_needs_enough_candles() -> None:
    with pytest.raises(ValueError, match="needs at least"):
        atr(frame([FLAT] * 5))


def test_first_last_and_unconfirmed_swings_are_ignored() -> None:
    ohlc = _zigzag([100, 110, 102, 115, 105, 118, 108, 120, 110], width=4)
    swing_length = 3

    swings = confirmed_swings(ohlc, swing_length)

    assert swings
    assert all(swing.index > 0 for swing in swings)
    assert all(swing.index <= len(ohlc) - 1 - swing_length for swing in swings)
    kinds = [swing.kind for swing in swings]
    assert BULLISH in kinds and BEARISH in kinds


def test_bias_higher_highs_and_lows_is_bullish() -> None:
    swings = [
        Swing(1, BULLISH, 110),
        Swing(3, BEARISH, 102),
        Swing(5, BULLISH, 115),
        Swing(7, BEARISH, 105),
    ]
    assert bias_from_swings(swings) == "bullish"


def test_bias_lower_highs_and_lows_is_bearish() -> None:
    swings = [
        Swing(1, BULLISH, 115),
        Swing(3, BEARISH, 105),
        Swing(5, BULLISH, 110),
        Swing(7, BEARISH, 100),
    ]
    assert bias_from_swings(swings) == "bearish"


def test_bias_mixed_is_range() -> None:
    swings = [
        Swing(1, BULLISH, 110),
        Swing(3, BEARISH, 105),
        Swing(5, BULLISH, 115),
        Swing(7, BEARISH, 100),
    ]
    assert bias_from_swings(swings) == "range"


def test_bias_equal_levels_is_range_not_bearish() -> None:
    swings = [
        Swing(1, BULLISH, 110),
        Swing(3, BEARISH, 100),
        Swing(5, BULLISH, 110),
        Swing(7, BEARISH, 100),
    ]
    assert bias_from_swings(swings) == "range"


def test_bias_without_two_of_each_is_range() -> None:
    assert bias_from_swings([Swing(1, BULLISH, 110), Swing(3, BEARISH, 102)]) == "range"


def test_bullish_ote_from_last_swing_low_to_highest_high_since() -> None:
    ohlc = frame([FLAT] * 3 + [(100, 120, 100, 119), (119, 119.5, 118, 118)])
    swings = [Swing(2, BEARISH, 100.0)]

    band = ote_band(ohlc, swings, BULLISH)

    assert band is not None
    low, high = band
    assert low == pytest.approx(120 - 0.786 * 20)
    assert high == pytest.approx(120 - 0.618 * 20)


def test_bearish_ote_is_mirrored() -> None:
    ohlc = frame([FLAT] * 3 + [(100, 100, 80, 81), (81, 82, 80.5, 81)])
    swings = [Swing(2, BULLISH, 100.0)]

    band = ote_band(ohlc, swings, BEARISH)

    assert band is not None
    low, high = band
    assert low == pytest.approx(80 + 0.618 * 20)
    assert high == pytest.approx(80 + 0.786 * 20)


def test_ote_is_none_without_anchor_or_range() -> None:
    ohlc = frame([FLAT] * 5)
    assert ote_band(ohlc, [], BULLISH) is None
    assert ote_band(ohlc, [Swing(4, BEARISH, 101.0)], BULLISH) is None


def test_trendline_projects_through_last_two_swing_lows() -> None:
    ohlc = frame([FLAT] * 11)
    swings = [Swing(2, BEARISH, 100.0), Swing(6, BEARISH, 102.0)]

    assert trendline_value(ohlc, swings, BULLISH) == pytest.approx(104.0)  # +0.5 per candle


def test_trendline_is_none_with_fewer_than_two_swings() -> None:
    assert trendline_value(frame([FLAT] * 5), [Swing(1, BEARISH, 100.0)], BULLISH) is None


def test_analyse_structure_bundles_everything() -> None:
    ohlc = frame([FLAT] * 20)
    structure = analyse_structure(ohlc, [])

    assert structure.atr == pytest.approx(2.0)
    assert structure.bias == "range"
    assert structure.ote_bullish is None
    assert structure.trendline_bearish is None
