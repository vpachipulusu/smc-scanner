"""CSV loader: ``time, open, high, low, close[, volume]``; the symbol is the file path.

Only the CLI and the watchlist feed paths to this loader; the API does not expose it. ``load``
keeps the last ``bars`` rows, as every loader does; ``read_all`` returns the whole file, for a
caller that wants every candle (a backtest with a ``lookback`` window may replay more than
``MAX_BARS``).
"""

from pathlib import Path

import pandas as pd

from smc_scanner.loaders.base import LoaderError, normalise


class CsvLoader:
    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        return self.read_all(symbol).tail(bars).reset_index(drop=True)

    def read_all(self, symbol: str) -> pd.DataFrame:
        """Every candle in the file ``symbol`` names, oldest first, normalised."""
        path = Path(symbol)
        if not path.is_file():
            raise LoaderError(f"CSV file not found: {path}")
        try:
            raw = pd.read_csv(path)
        except (
            pd.errors.ParserError,
            pd.errors.EmptyDataError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            raise LoaderError(f"cannot parse {path}: {exc}") from exc
        if "time" not in {str(column).lower() for column in raw.columns}:
            raise LoaderError(f"{path}: missing 'time' column")
        raw = raw.rename(columns={column: str(column).lower() for column in raw.columns})
        raw["time"] = pd.to_datetime(raw["time"], errors="coerce")
        if raw["time"].isna().any():
            raise LoaderError(f"{path}: unparseable timestamps in 'time'")
        return normalise(raw)

    def close(self) -> None:
        return None
