"""Constants and timeframe maps shared by the scanner, loaders, CLI and API."""

import re
from typing import Final, Literal

Timeframe = Literal["5m", "15m", "30m", "1h", "4h", "1d"]
Source = Literal["mt5", "csv", "demo"]
# The API never takes file paths from a request, so it has no csv source.
ApiSource = Literal["mt5", "demo"]

TIMEFRAMES: Final[tuple[str, ...]] = ("5m", "15m", "30m", "1h", "4h", "1d")

TIMEFRAME_MINUTES: Final[dict[str, int]] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

# Attribute names on the MetaTrader5 module; resolved at runtime so tests can inject a fake.
MT5_TIMEFRAME_ATTR: Final[dict[str, str]] = {
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}

SOURCES: Final[tuple[str, ...]] = ("mt5", "csv", "demo")

# ``Final`` without an annotation keeps the Literal type, so these satisfy the Literals above.
DEFAULT_SOURCE: Final = "mt5"
DEFAULT_TIMEFRAME: Final = "1h"
DEFAULT_BARS: Final[int] = 500
DEFAULT_SWING_LENGTH: Final[int] = 10
DEFAULT_NEAR_ATR: Final[float] = 0.5
DEFAULT_OUTPUT_CSV: Final[str] = "scan_results.csv"

ATR_PERIOD: Final[int] = 14
OTE_LOW: Final[float] = 0.618
OTE_HIGH: Final[float] = 0.786

# How many timeframes behind the last tick the last bar may be before the loader warns.
STALE_BAR_MULTIPLIER: Final[int] = 2

DEFAULT_DEMO_SYMBOLS: Final[tuple[str, ...]] = ("EURUSD", "XAUUSD", "NAS100", "UK100", "BTCUSD")

# Fewest bars that make a scan possible at all: ATR(14) needs a previous close.
MIN_BARS: Final[int] = ATR_PERIOD + 1
MAX_BARS: Final[int] = 5000
# A backtest with a ``lookback`` window may replay a longer history; nothing else reads this.
MAX_BACKTEST_BARS: Final[int] = 200_000
# What the API accepts as a symbol, and how many per request; the CLI checks the same.
MAX_SYMBOLS: Final[int] = 50
SYMBOL_PATTERN: Final = re.compile(r"^[A-Za-z0-9._#@\-]{1,32}$")
MAX_SWING_LENGTH: Final[int] = 100
MAX_NEAR_ATR: Final[float] = 5.0


def neighbour_timeframes(timeframe: str) -> tuple[str | None, str | None]:
    """(higher, lower) timeframe next to ``timeframe`` in ``TIMEFRAMES``; None at either end."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    index = TIMEFRAMES.index(timeframe)
    higher = TIMEFRAMES[index + 1] if index + 1 < len(TIMEFRAMES) else None
    lower = TIMEFRAMES[index - 1] if index > 0 else None
    return higher, lower
