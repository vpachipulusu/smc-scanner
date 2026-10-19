"""Read-only MetaTrader 5 loader.

Attaches to the MT5 terminal running on this machine (``mt5.initialize()``). If the
terminal is not running, the optional ``MT5_PATH``, ``MT5_LOGIN``, ``MT5_PASSWORD`` and
``MT5_SERVER`` environment variables are passed to ``initialize`` so it can start and log
in. Use the account's *investor* (read-only) password there, never the master password.

Only these calls are used: ``initialize``, ``shutdown``, ``last_error``, ``symbol_select``
(which adds the symbol to the terminal's Market Watch), ``symbol_info_tick`` and
``copy_rates_from_pos``; never anything that trades. ``tests/test_readonly.py`` enforces
this with an AST check.

The MT5 Python API is one process-wide connection and is not thread-safe, so symbols are
scanned one at a time and the API serialises scans with a lock.

Position 0 of ``copy_rates_from_pos`` is the still-forming candle, so the scan's "latest
candle" is live and its status can change until the bar closes.
"""

import importlib
import logging
import os
from types import ModuleType
from typing import Any, Self

import numpy as np
import numpy.typing as npt
import pandas as pd

from smc_scanner.config import MT5_TIMEFRAME_ATTR, STALE_BAR_MULTIPLIER, TIMEFRAME_MINUTES
from smc_scanner.loaders.base import LoaderError, normalise

log = logging.getLogger(__name__)

MT5_MODULE_NAME = "MetaTrader5"
SECONDS_PER_MINUTE = 60


def _module() -> ModuleType:
    try:
        return importlib.import_module(MT5_MODULE_NAME)
    except ImportError as exc:  # pragma: no cover - only on non-Windows hosts
        raise LoaderError("MetaTrader5 package is not installed (Windows only)") from exc


def _init_kwargs() -> dict[str, Any]:
    """Optional terminal path and login read from the environment, never hardcoded."""
    kwargs: dict[str, Any] = {}
    path = os.environ.get("MT5_PATH")
    if path:
        kwargs["path"] = path
    login = os.environ.get("MT5_LOGIN")
    if login:
        try:
            kwargs["login"] = int(login)
        except ValueError as exc:
            raise LoaderError("MT5_LOGIN must be an integer account number") from exc
        kwargs["password"] = os.environ.get("MT5_PASSWORD", "")
        kwargs["server"] = os.environ.get("MT5_SERVER", "")
    return kwargs


class Mt5Loader:
    """Context-managed connection: ``with Mt5Loader() as loader: loader.load(...)``.

    A failed ``initialize`` is remembered, so a watchlist of fifty symbols does not retry
    the login fifty times (brokers lock accounts for that).
    """

    def __init__(self) -> None:
        self._mt5: ModuleType | None = None
        self._connect_error: LoaderError | None = None

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> ModuleType:
        if self._mt5 is not None:
            return self._mt5
        if self._connect_error is not None:
            raise self._connect_error
        mt5 = _module()
        if not mt5.initialize(**_init_kwargs()):
            self._connect_error = LoaderError(f"MT5 initialize failed: {mt5.last_error()}")
            raise self._connect_error
        self._mt5 = mt5
        log.info("connected to MT5 terminal")
        return mt5

    def close(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
            self._mt5 = None

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        mt5 = self.connect()
        if timeframe not in MT5_TIMEFRAME_ATTR:
            raise LoaderError(f"unsupported timeframe {timeframe!r}")
        if not mt5.symbol_select(symbol, True):
            raise LoaderError(f"unknown symbol {symbol!r}: {mt5.last_error()}")
        tf_value = getattr(mt5, MT5_TIMEFRAME_ATTR[timeframe])
        rates = mt5.copy_rates_from_pos(symbol, tf_value, 0, bars)
        if rates is None or len(rates) == 0:
            raise LoaderError(f"no candles for {symbol!r}: {mt5.last_error()}")
        _warn_if_stale(mt5, symbol, timeframe, int(rates["time"][-1]))
        return rates_to_frame(rates)


def rates_to_frame(rates: npt.NDArray[np.void]) -> pd.DataFrame:
    """Convert the structured array from ``copy_rates_from_pos`` to a normalised frame.

    ``time`` is broker server time in epoch seconds; it is kept as a naive timestamp.
    ``tick_volume`` becomes ``volume``.
    """
    raw = pd.DataFrame(rates)
    raw["time"] = pd.to_datetime(raw["time"], unit="s")
    if "tick_volume" in raw.columns:
        raw = raw.rename(columns={"tick_volume": "volume"})
    return normalise(raw[["time", "open", "high", "low", "close", "volume"]])


def _warn_if_stale(mt5: ModuleType, symbol: str, timeframe: str, last_bar_epoch: int) -> None:
    """Compare the last bar with the symbol's last tick (both broker time); warn when the
    bar is older than a couple of timeframes, which means a closed market or a dead feed."""
    tick = mt5.symbol_info_tick(symbol)
    tick_epoch = int(getattr(tick, "time", 0) or 0)
    if tick_epoch <= 0:
        return
    bar_seconds = TIMEFRAME_MINUTES[timeframe] * SECONDS_PER_MINUTE
    age = tick_epoch - (last_bar_epoch + bar_seconds)
    if age > STALE_BAR_MULTIPLIER * bar_seconds:
        log.warning(
            "%r: last bar is %d min behind the last tick; market may be closed or feed stale",
            symbol,
            age // SECONDS_PER_MINUTE,
        )
