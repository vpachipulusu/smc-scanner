"""Hand-built OHLC helpers shared by the tests."""

from collections.abc import Sequence

import pandas as pd
import pytest

Candle = tuple[float, float, float, float]  # open, high, low, close

FLAT: Candle = (100.0, 101.0, 99.0, 100.0)
ATR_WARMUP = 16  # enough flat candles for ATR(14) before a pattern starts


def frame(candles: Sequence[Candle], start: str = "2026-01-01") -> pd.DataFrame:
    """A normalised frame (RangeIndex, time column, volume 1) from (o, h, l, c) tuples."""
    times = pd.date_range(start, periods=len(candles), freq="1h")
    return pd.DataFrame(
        {
            "time": times,
            "open": [c[0] for c in candles],
            "high": [c[1] for c in candles],
            "low": [c[2] for c in candles],
            "close": [c[3] for c in candles],
            "volume": [1.0] * len(candles),
        }
    )


def with_warmup(candles: Sequence[Candle]) -> pd.DataFrame:
    return frame([FLAT] * ATR_WARMUP + list(candles))


# A bullish FVG at the middle candle (index ATR_WARMUP + 1): gap between 101 and 103.
FVG_SETUP: list[Candle] = [
    (100.0, 101.0, 99.0, 100.0),  # candle before: high 101 = gap bottom
    (100.0, 106.0, 100.0, 105.0),  # impulse candle (middle)
    (105.0, 107.0, 103.0, 106.0),  # candle after: low 103 = gap top
    (106.0, 108.0, 105.0, 107.0),  # first candle where a touch would count
    (107.0, 108.0, 104.0, 105.0),  # stays above the gap
]
FVG_TOP = 103.0
FVG_BOTTOM = 101.0
TOUCH_LAST: Candle = (105.0, 106.0, 102.5, 103.0)  # dips into the gap


@pytest.fixture
def fvg_touching() -> pd.DataFrame:
    return with_warmup([*FVG_SETUP, TOUCH_LAST])


@pytest.fixture
def fvg_tested_before() -> pd.DataFrame:
    tested = list(FVG_SETUP)
    tested[4] = (107.0, 108.0, 102.8, 105.0)  # earlier dip into the gap
    return with_warmup([*tested, TOUCH_LAST])


@pytest.fixture
def fvg_traded_through() -> pd.DataFrame:
    broken = list(FVG_SETUP)
    broken[4] = (107.0, 108.0, 100.5, 105.0)  # low below the gap bottom
    return with_warmup([*broken, TOUCH_LAST])


# A bullish OB: swing high at 105, a pullback whose lowest candle is the block
# (99.5-102), a close above 105 that confirms it, a move away, then a return.
OB_SETUP: list[Candle] = [
    (100.0, 103.0, 100.0, 102.0),
    (102.0, 105.0, 101.0, 104.0),  # swing high 105
    (104.0, 104.5, 101.0, 101.5),
    (101.5, 102.0, 99.5, 100.0),  # order block candle: top 102, bottom 99.5
    (100.0, 104.0, 99.8, 103.5),  # overlaps the block before price has moved away
    (103.5, 107.0, 103.0, 106.5),  # close above 105; low 103 > 102: moved away
    (106.5, 108.0, 105.0, 107.0),
    (107.0, 108.0, 104.0, 105.0),
]
OB_TOP = 102.0
OB_BOTTOM = 99.5
OB_TOUCH_LAST: Candle = (105.0, 106.0, 101.5, 103.0)


@pytest.fixture
def ob_touching() -> pd.DataFrame:
    return with_warmup([*OB_SETUP, OB_TOUCH_LAST])
