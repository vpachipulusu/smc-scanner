"""Run a backtest over a watchlist: load, replay, label and summarise per symbol and pooled.

The only I/O is the loader passed in, which the caller owns and closes. As in
``scanner.scan_watchlist``, a symbol that fails is logged once, recorded and skipped.
"""

import logging
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Final

import pandas as pd

from smc_scanner.backtest.outcome import ExitRules, Outcome, label
from smc_scanner.backtest.replay import replay
from smc_scanner.backtest.stats import BacktestStats, summarise
from smc_scanner.config import MAX_BARS, MIN_BARS
from smc_scanner.loaders.base import Loader
from smc_scanner.scanner import ScanFailure, ScanOptions
from smc_scanner.strategy.conditions import resolve_all
from smc_scanner.strategy.models import Strategy

log = logging.getLogger(__name__)

RowValue = str | int | float | bool | None
ROW_COLUMNS: Final = (
    "symbol",
    "bar_index",
    "bar_time",
    "zone",
    "kind",
    "direction",
    "formed_index",
    "zone_low",
    "zone_high",
    "status",
    "score",
    "entry",
    "stop",
    "target",
    "exit_price",
    "exit_reason",
    "r_multiple",
    "bars_held",
    "atr",
    "fwd_5_atr",
    "fwd_10_atr",
    "fwd_20_atr",
)


@dataclass(frozen=True)
class SymbolBacktest:
    symbol: str
    outcomes: tuple[Outcome, ...]  # in signal order
    stats: BacktestStats


@dataclass(frozen=True)
class BacktestReport:
    timeframe: str
    bars: int
    strategy: str
    rules: ExitRules
    seed: int
    stride: int
    symbols: tuple[SymbolBacktest, ...]
    pooled: BacktestStats  # every symbol's outcomes in signal-time order
    failures: tuple[ScanFailure, ...]

    def pooled_outcomes(self) -> list[Outcome]:
        """Every symbol's outcomes by signal time, then symbol: the order ``pooled`` uses."""
        return _pooled(self.symbols)

    def to_rows(self) -> list[dict[str, RowValue]]:
        """One flat record per signal (``ROW_COLUMNS``), symbol by symbol, for a CSV."""
        return [_row(outcome) for result in self.symbols for outcome in result.outcomes]

    def to_dict(self) -> dict[str, object]:
        """The whole report as strict-JSON data: a non-finite float becomes None."""
        safe: dict[str, object] = _json_safe(
            {
                "timeframe": self.timeframe,
                "bars": self.bars,
                "strategy": self.strategy,
                "seed": self.seed,
                "stride": self.stride,
                "rules": asdict(self.rules),
                "pooled": asdict(self.pooled),
                "symbols": [{"symbol": r.symbol, "stats": asdict(r.stats)} for r in self.symbols],
                "failures": [asdict(failure) for failure in self.failures],
                "signals": self.to_rows(),
            }
        )
        return safe


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


def _row(outcome: Outcome) -> dict[str, RowValue]:
    signal = outcome.signal
    values: tuple[RowValue, ...] = (
        signal.row.instrument,
        signal.bar_index,
        signal.bar_time,
        signal.row.zone,
        signal.zone.kind,
        signal.zone.direction,
        signal.zone.formed_index,
        signal.zone.bottom,
        signal.zone.top,
        signal.row.status,
        signal.row.score,
        outcome.entry,
        outcome.stop,
        outcome.target,
        outcome.exit_price,
        outcome.exit_reason,
        outcome.r_multiple,
        outcome.bars_held,
        outcome.atr,
        outcome.fwd_5_atr,
        outcome.fwd_10_atr,
        outcome.fwd_20_atr,
    )
    return dict(zip(ROW_COLUMNS, values, strict=True))


@dataclass(frozen=True)
class _Job:
    """Everything one symbol's backtest needs besides the symbol."""

    loader: Loader
    timeframe: str
    bars: int
    strategy: Strategy
    rules: ExitRules
    options: ScanOptions | None
    seed: int
    stride: int

    def run(self, symbol: str) -> SymbolBacktest:
        ohlc = self.loader.load(symbol, self.timeframe, self.bars)
        if len(ohlc) > self.bars:  # a loader returning more must not lift the bars cap
            ohlc = ohlc.iloc[-self.bars :].reset_index(drop=True)
        signals = replay(symbol, ohlc, self.strategy, options=self.options, stride=self.stride)
        outcomes = tuple(label(ohlc, signal, self.rules) for signal in signals)
        return SymbolBacktest(symbol, outcomes, summarise(outcomes, seed=self.seed))


def _pooled(results: Iterable[SymbolBacktest]) -> list[Outcome]:
    every = [outcome for result in results for outcome in result.outcomes]
    return sorted(every, key=lambda o: (pd.Timestamp(o.signal.bar_time), o.signal.row.instrument))


def _check_args(bars: int, seed: int, stride: int, strategy: Strategy) -> None:
    if not MIN_BARS <= bars <= MAX_BARS:
        raise ValueError(f"bars must be between {MIN_BARS} and {MAX_BARS}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if stride < 1:
        raise ValueError("stride must be at least 1")
    resolve_all((*strategy.require, *strategy.score))  # unknown conditions raise here


def run_backtest(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    strategy: Strategy,
    rules: ExitRules,
    *,
    options: ScanOptions | None = None,
    seed: int = 0,
    stride: int = 1,
) -> BacktestReport:
    """Backtest ``strategy`` on each symbol's last ``bars`` candles. ``options`` overrides the
    strategy's scan tuning, as in the live scan; ``stride`` > 1 replays approximately (see
    ``replay``). Bad ``bars``, ``seed`` or ``stride``, or an unknown condition, raise before
    anything loads. A symbol whose load, replay or labelling fails is logged, recorded and
    skipped whole."""
    _check_args(bars, seed, stride, strategy)
    job = _Job(loader, timeframe, bars, strategy, rules, options, seed, stride)
    results: list[SymbolBacktest] = []
    failures: list[ScanFailure] = []
    for symbol in symbols:
        try:
            results.append(job.run(symbol))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the backtest
            message = f"{type(exc).__name__}: {exc}"
            log.error("%r: skipped (%s)", symbol, message)
            failures.append(ScanFailure(symbol=symbol, error=message))
    return BacktestReport(
        timeframe=timeframe,
        bars=bars,
        strategy=strategy.slug,
        rules=rules,
        seed=seed,
        stride=stride,
        symbols=tuple(results),
        pooled=summarise(_pooled(results), seed=seed),
        failures=tuple(failures),
    )
