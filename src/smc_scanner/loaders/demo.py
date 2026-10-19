"""Demo loader: seeded simulated candles so the scanner runs with no keys or terminal.

A random walk with occasional impulse moves, which naturally leaves fair value gaps and
order blocks behind. The seed is derived from the symbol so each symbol is stable across
runs but different from the others. It also builds the MT5-shaped structured array so
the MT5 conversion path is exercised without a terminal.
"""

import zlib

import numpy as np
import pandas as pd

from smc_scanner.config import TIMEFRAME_MINUTES
from smc_scanner.loaders.base import LoaderError, normalise

# Rough price levels so demo output looks like the real instrument.
DEMO_START_PRICES: dict[str, float] = {
    "EURUSD": 1.08,
    "XAUUSD": 2400.0,
    "NAS100": 18000.0,
    "UK100": 8200.0,
    "BTCUSD": 65000.0,
}
DEFAULT_START_PRICE = 100.0
STEP_FRACTION = 0.002  # per-candle move as a fraction of price
IMPULSE_PROBABILITY = 0.04
IMPULSE_FRACTION = 0.012

MT5_RATES_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<u8"),
        ("spread", "<i4"),
        ("real_volume", "<u8"),
    ]
)


def _seed(symbol: str) -> int:
    return zlib.crc32(symbol.upper().encode("utf-8"))


def simulate_rates(symbol: str, timeframe: str, bars: int, seed: int | None = None) -> np.ndarray:
    """Structured array with the same dtype MT5's ``copy_rates_from_pos`` returns."""
    if timeframe not in TIMEFRAME_MINUTES:
        raise LoaderError(f"unsupported timeframe {timeframe!r}")
    rng = np.random.default_rng(_seed(symbol) if seed is None else seed)
    price = DEMO_START_PRICES.get(symbol.upper(), DEFAULT_START_PRICE)
    minutes = TIMEFRAME_MINUTES[timeframe]
    end = pd.Timestamp.now(tz="UTC").floor(f"{minutes}min").tz_localize(None)
    times = pd.date_range(end=end, periods=bars, freq=f"{minutes}min")

    rates = np.zeros(bars, dtype=MT5_RATES_DTYPE)
    for i in range(bars):
        step = price * STEP_FRACTION
        impulse = rng.random() < IMPULSE_PROBABILITY
        move = rng.normal(0, step) + (
            rng.choice([-1, 1]) * price * IMPULSE_FRACTION if impulse else 0.0
        )
        open_ = price
        close = price + move
        wick = abs(rng.normal(0, step / 2))
        high = max(open_, close) + wick
        low = min(open_, close) - wick
        rates[i] = (
            int(times[i].timestamp()),
            open_,
            high,
            low,
            close,
            int(rng.integers(100, 1000)),
            2,
            0,
        )
        price = close
    return rates


class DemoLoader:
    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        raw = pd.DataFrame(simulate_rates(symbol, timeframe, bars, self._seed))
        raw["time"] = pd.to_datetime(raw["time"], unit="s")
        raw = raw.rename(columns={"tick_volume": "volume"})
        return normalise(raw[["time", "open", "high", "low", "close", "volume"]])

    def close(self) -> None:
        return None
