"""Run a backtest over a watchlist: load, replay, label and summarise per symbol and pooled.

The only I/O is the loader passed in, which the caller owns and closes. As in
``scanner.scan_watchlist``, a symbol that fails is logged once, recorded and skipped.
"""

import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Final

from smc_scanner.backtest._common import (
    check_args,
    chronological,
    json_safe,
    load_frame,
    run_each,
)
from smc_scanner.backtest.outcome import ExitRules, Outcome, label
from smc_scanner.backtest.replay import replay
from smc_scanner.backtest.stats import BacktestStats, summarise
from smc_scanner.loaders.base import Loader
from smc_scanner.scanner import ScanFailure, ScanOptions
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
    lookback: int | None = None  # bars each replay step scanned; None: the whole prefix

    def pooled_outcomes(self) -> list[Outcome]:
        """Every symbol's outcomes by signal time, then symbol: the order ``pooled`` uses."""
        return _pooled(self.symbols)

    def to_rows(self) -> list[dict[str, RowValue]]:
        """One flat record per signal (``ROW_COLUMNS``), symbol by symbol, for a CSV."""
        return [_row(outcome) for result in self.symbols for outcome in result.outcomes]

    def to_dict(self) -> dict[str, object]:
        """The whole report as strict-JSON data: a non-finite float becomes None."""
        safe: dict[str, object] = json_safe(
            {
                "timeframe": self.timeframe,
                "bars": self.bars,
                "strategy": self.strategy,
                "seed": self.seed,
                "stride": self.stride,
                "lookback": self.lookback,
                "rules": asdict(self.rules),
                "pooled": asdict(self.pooled),
                "symbols": [{"symbol": r.symbol, "stats": asdict(r.stats)} for r in self.symbols],
                "failures": [asdict(failure) for failure in self.failures],
                "signals": self.to_rows(),
            }
        )
        return safe


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
    lookback: int | None

    def run(self, symbol: str) -> SymbolBacktest:
        ohlc = load_frame(self.loader, symbol, self.timeframe, self.bars)
        signals = replay(
            symbol,
            ohlc,
            self.strategy,
            options=self.options,
            stride=self.stride,
            lookback=self.lookback,
        )
        outcomes = tuple(label(ohlc, signal, self.rules) for signal in signals)
        return SymbolBacktest(symbol, outcomes, summarise(outcomes, seed=self.seed))


def _pooled(results: Iterable[SymbolBacktest]) -> list[Outcome]:
    return chronological(outcome for result in results for outcome in result.outcomes)


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
    lookback: int | None = None,
) -> BacktestReport:
    """Backtest ``strategy`` on each symbol's last ``bars`` candles. ``options`` overrides the
    strategy's scan tuning, as in the live scan; ``stride`` > 1 replays approximately and
    ``lookback`` scans each step's last ``lookback`` bars, as a live scan with that ``bars``
    would (see ``replay``); with it, ``bars`` may exceed ``MAX_BARS``. Bad ``bars``, ``seed``,
    ``stride`` or ``lookback``, or an unknown condition, raise before anything loads. A symbol
    whose load, replay or labelling fails is logged, recorded and skipped whole."""
    check_args(bars, seed, stride, strategy, lookback=lookback)
    job = _Job(loader, timeframe, bars, strategy, rules, options, seed, stride, lookback)
    results, failures = run_each(symbols, lambda _, symbol: job.run(symbol), log)
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
        lookback=lookback,
    )
