"""Helpers the backtest runners share: argument checks, loading, ordering, the failure loop and
strict-JSON conversion. Internal to the package; not re-exported."""

import logging
import math
from collections.abc import Callable, Iterable
from typing import Any, Final

import pandas as pd

from smc_scanner.backtest.outcome import Outcome
from smc_scanner.config import MAX_BARS, MIN_BARS
from smc_scanner.loaders.base import Loader
from smc_scanner.scanner import ScanFailure
from smc_scanner.strategy.conditions import resolve_all
from smc_scanner.strategy.models import Strategy

MAX_SEED: Final = 2**32 - 1  # numpy seeds any size, but a bound keeps it cheap and JSON-exact


def _bounded_int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def check_seed(seed: object) -> int:
    """``seed`` as an int from 0 to ``MAX_SEED``; bools and other types are rejected."""
    if not isinstance(seed, int) or not _bounded_int(seed, 0, MAX_SEED):
        raise ValueError(f"seed must be an integer from 0 to {MAX_SEED}")
    return seed


def check_args(bars: int, seed: int, stride: int, strategy: Strategy) -> None:
    """Raise on bad ``bars``, ``seed`` or ``stride``, or an unknown condition or param."""
    if not _bounded_int(bars, MIN_BARS, MAX_BARS):
        raise ValueError(f"bars must be an integer between {MIN_BARS} and {MAX_BARS}")
    check_seed(seed)
    if not _bounded_int(stride, 1, MAX_BARS):
        raise ValueError(f"stride must be an integer between 1 and {MAX_BARS}")
    resolve_all((*strategy.require, *strategy.score))  # unknown conditions raise here


def distinct_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    """The symbols in input order, first occurrence kept. One bare string is rejected: it
    would iterate into one-letter symbols."""
    if isinstance(symbols, str | bytes):
        raise ValueError("symbols must be a collection of symbols, not one string")
    return tuple(dict.fromkeys(symbols))


def load_frame(loader: Loader, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    ohlc = loader.load(symbol, timeframe, bars)
    if len(ohlc) > bars:  # a loader returning more must not lift the bars cap
        ohlc = ohlc.iloc[-bars:].reset_index(drop=True)
    return ohlc


def chronological(outcomes: Iterable[Outcome]) -> list[Outcome]:
    """Outcomes by signal time, then symbol: the order pooled stats are summarised in."""
    return sorted(
        outcomes, key=lambda o: (pd.Timestamp(o.signal.bar_time), o.signal.row.instrument)
    )


def run_each[R](
    symbols: Iterable[str], run: Callable[[int, str], R], log: logging.Logger
) -> tuple[list[R], list[ScanFailure]]:
    """``run(position, symbol)`` for each symbol. One that raises is logged once, recorded as a
    ``ScanFailure`` (raw exception text: sanitise before it leaves the process) and skipped,
    as in ``scanner.scan_watchlist``."""
    results: list[R] = []
    failures: list[ScanFailure] = []
    for position, symbol in enumerate(symbols):
        try:
            results.append(run(position, symbol))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
            message = f"{type(exc).__name__}: {exc}"
            log.error("%r: skipped (%r)", symbol, message)  # %r: no forged log lines
            failures.append(ScanFailure(symbol=symbol, error=message))
    return results, failures


def json_safe(value: Any) -> Any:
    """``value`` with every non-finite float turned into None and tuples into lists."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value
