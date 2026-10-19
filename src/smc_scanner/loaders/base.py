"""Loader protocol and the OHLC normalisation every source goes through."""

from typing import Protocol

import numpy as np
import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = ("time", "open", "high", "low", "close")
PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")


class LoaderError(Exception):
    """A source could not deliver candles for a symbol."""


class Loader(Protocol):
    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        """Return at most ``bars`` candles, oldest first, normalised (see ``normalise``)."""
        ...

    def close(self) -> None:
        """Release any connection; a no-op for sources without one."""
        ...


def normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Lower-case columns, numeric prices, a ``volume`` column, ascending time, RangeIndex.

    Rejects missing or non-finite prices, ``high < low`` and duplicate column names;
    duplicate timestamps keep the last row. The library slices Series positionally, so a
    RangeIndex is required; ``time`` is kept as a plain column.
    """
    renamed = frame.rename(columns={column: str(column).lower() for column in frame.columns})
    if renamed.columns.duplicated().any():
        raise LoaderError("duplicate column names after lower-casing")
    missing = [column for column in REQUIRED_COLUMNS if column not in renamed.columns]
    if missing:
        raise LoaderError(f"missing columns: {', '.join(missing)}")
    if renamed.empty:
        raise LoaderError("no candles returned")

    ordered = renamed.sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    prices = {
        column: pd.to_numeric(ordered[column], errors="coerce").to_numpy(dtype=float)
        for column in PRICE_COLUMNS
    }
    volume = (
        pd.to_numeric(ordered["volume"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        if "volume" in ordered.columns
        else 1.0
    )
    result = pd.DataFrame({"time": ordered["time"].to_numpy(), **prices, "volume": volume})
    price_values = result[list(PRICE_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(price_values).all():
        raise LoaderError("non-numeric, missing or infinite price values")
    if (result["high"] < result["low"]).any():
        raise LoaderError("high below low in at least one candle")
    return result
