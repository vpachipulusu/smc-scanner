"""Strategy backtesting: point-in-time replay, outcome labelling, statistics, a report, null
baselines and a walk-forward verdict.

Pure functions over OHLC frames; the only I/O is the loader handed to ``run_backtest``.
This package must not import ``api``, ``schedule`` or ``ai``.
"""

from smc_scanner.backtest.baseline import (
    direction_flipped,
    flipped_signals,
    random_entries,
    random_signals,
)
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
from smc_scanner.backtest.sweep import SweepPoint, sweep, sweep_variants
from smc_scanner.backtest.walkforward import (
    SplitKind,
    SymbolWindow,
    Verdict,
    WalkForwardResult,
    split_by_symbols,
    split_by_time,
    split_outcomes,
    verdict,
    walk_forward,
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
    "SplitKind",
    "SweepPoint",
    "SymbolBacktest",
    "SymbolWindow",
    "Verdict",
    "WalkForwardResult",
    "ZoneKey",
    "bootstrap_ci",
    "direction_flipped",
    "flipped_signals",
    "label",
    "max_drawdown",
    "profit_factor",
    "random_entries",
    "random_signals",
    "replay",
    "run_backtest",
    "scan_at",
    "split_by_symbols",
    "split_by_time",
    "split_outcomes",
    "summarise",
    "sweep",
    "sweep_variants",
    "verdict",
    "walk_forward",
    "zone_key",
]
