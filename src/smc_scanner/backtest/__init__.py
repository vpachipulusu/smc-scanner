"""Strategy backtesting: point-in-time replay, outcome labelling, statistics and a report.

Pure functions over OHLC frames; the only I/O is the loader handed to ``run_backtest``.
This package must not import ``api``, ``schedule`` or ``ai``.
"""

from smc_scanner.backtest.outcome import FORWARD_HORIZONS, ExitReason, ExitRules, Outcome, label
from smc_scanner.backtest.replay import Signal, ZoneKey, replay, scan_at, zone_key
from smc_scanner.backtest.report import (
    ROW_COLUMNS,
    BacktestReport,
    SymbolBacktest,
    run_backtest,
)
from smc_scanner.backtest.stats import (
    BacktestStats,
    bootstrap_ci,
    max_drawdown,
    profit_factor,
    summarise,
)

__all__ = [
    "FORWARD_HORIZONS",
    "ROW_COLUMNS",
    "BacktestReport",
    "BacktestStats",
    "ExitReason",
    "ExitRules",
    "Outcome",
    "Signal",
    "SymbolBacktest",
    "ZoneKey",
    "bootstrap_ci",
    "label",
    "max_drawdown",
    "profit_factor",
    "replay",
    "run_backtest",
    "scan_at",
    "summarise",
    "zone_key",
]
