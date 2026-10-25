"""``smc-backtest`` command line: backtest strategies over a watchlist and print one table.

Each strategy is walked forward: in-sample vs out-of-sample, against the random-entry and
direction-flipped baselines, with a verdict. Every symbol is loaded once and shared by the
strategies. ``--out`` writes one CSV of per-signal rows per
strategy (spreadsheet formulas neutralised) and a JSON summary; ``--save`` stores each summary in
the database ``SMC_DB_PATH`` names. Screening research only; it never places trades.
"""

import argparse
import csv
import json
import logging
import math
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final

import pandas as pd
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.table import Table
from rich.text import Text

from smc_scanner.ai.store import StoreError, db_path_from_env
from smc_scanner.backtest.jobs import (
    MAX_SEED,
    SPLIT_KINDS,
    PreloadedLoader,
    SplitSpec,
    WalkForwardRunner,
    baselines_of,
    preload,
    scrub_failures,
    walk_forward_runner,
)
from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.backtest.report import ROW_COLUMNS, run_backtest
from smc_scanner.backtest.store import (
    JsonObject,
    NewBacktest,
    SqliteBacktestRepository,
    Verdict,
    parse_verdict,
    without_signals,
)
from smc_scanner.backtest.walkforward import DEFAULT_TRAIN_FRACTION
from smc_scanner.cli import StrategyChoiceError, load_strategy, resolve_symbols
from smc_scanner.config import (
    DEFAULT_BARS,
    DEFAULT_SOURCE,
    DEFAULT_TIMEFRAME,
    MAX_BARS,
    MAX_SYMBOLS,
    MIN_BARS,
    SOURCES,
    SYMBOL_PATTERN,
    TIMEFRAMES,
)
from smc_scanner.loaders import LoaderError, make_loader
from smc_scanner.report import csv_safe
from smc_scanner.strategy import SLUG_PATTERN, Strategy
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES
from smc_scanner.watchlist import DEFAULT_WATCHLIST, WatchlistError

log = logging.getLogger("smc_scanner")

EXIT_OK: Final = 0
EXIT_FAILED: Final = 1
EXIT_INTERRUPTED: Final = 130  # 128 + SIGINT, the shell convention
SPREAD_COLUMN: Final = "spread"
SUMMARY_FILE: Final = "summary.json"
NO_VALUE: Final = "-"
_DEFAULT_RULES = ExitRules()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smc-backtest",
        description="Backtest strategies on past candles: hit rate, expectancy in R with a "
        "bootstrap interval, walk-forward and baselines. Research only; never places trades.",
    )
    parser.add_argument("--source", choices=SOURCES, default=DEFAULT_SOURCE)
    parser.add_argument("--symbols", nargs="+", metavar="SYMBOL", help="override the watchlist")
    parser.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--tf", choices=TIMEFRAMES, default=DEFAULT_TIMEFRAME)
    parser.add_argument(
        "--bars",
        type=int,
        help=f"candles per symbol (default {MAX_BARS} for csv, else {DEFAULT_BARS})",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        metavar="SLUG",
        help="strategy to test; repeat for several (default: every built-in)",
    )
    parser.add_argument("--rr", type=float, default=_DEFAULT_RULES.rr, help="target in R")
    parser.add_argument(
        "--stop-buffer-atr", type=float, default=_DEFAULT_RULES.stop_buffer_atr, metavar="ATR"
    )
    parser.add_argument(
        "--time-stop", type=int, default=_DEFAULT_RULES.time_stop_bars, metavar="BARS"
    )
    parser.add_argument(
        "--spread",
        type=float,
        help="price units per trade (default: the mean spread column of csv files, else 0)",
    )
    parser.add_argument("--split", choices=SPLIT_KINDS, default="time")
    parser.add_argument("--train-fraction", type=float, default=DEFAULT_TRAIN_FRACTION)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stride", type=int, default=1, help="replay every Nth bar (faster)")
    parser.add_argument("--out", type=Path, metavar="DIR", help="write CSVs and a JSON summary")
    parser.add_argument("--save", action="store_true", help="store the summaries (SMC_DB_PATH)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


@dataclass(frozen=True)
class Settings:
    """The validated arguments."""

    source: str
    timeframe: str
    bars: int
    slugs: tuple[str, ...]
    rules: ExitRules  # spread 0 unless --spread was given
    spread_given: bool
    split: SplitSpec
    seed: int
    stride: int


def _check_symbols(symbols: Sequence[str], parser: argparse.ArgumentParser) -> None:
    """The API's symbol rules, so ``--save`` stores only symbols the API would accept."""
    if len(set(symbols)) > MAX_SYMBOLS:
        parser.error(f"--symbols takes at most {MAX_SYMBOLS} symbols")
    if not all(SYMBOL_PATTERN.match(symbol) for symbol in symbols):
        parser.error("--symbols must be 1-32 of A-Z, a-z, 0-9 or . _ # @ -")


def _settings(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Settings:
    bars = (
        args.bars if args.bars is not None else MAX_BARS if args.source == "csv" else DEFAULT_BARS
    )
    if not MIN_BARS <= bars <= MAX_BARS:
        parser.error(f"--bars must be between {MIN_BARS} and {MAX_BARS}")
    if not 0 <= args.seed <= MAX_SEED:
        parser.error(f"--seed must be between 0 and {MAX_SEED}")
    if args.stride < 1:
        parser.error("--stride must be at least 1")
    if args.source != "csv" and args.symbols:  # csv symbols are file paths
        _check_symbols(args.symbols, parser)
    slugs = tuple(dict.fromkeys(args.strategy or BUILTIN_STRATEGIES))
    if not all(SLUG_PATTERN.fullmatch(slug) for slug in slugs):
        parser.error("--strategy must be a slug: 1-32 of a-z, 0-9 or -, not starting with -")
    try:
        rules = ExitRules(
            rr=args.rr,
            stop_buffer_atr=args.stop_buffer_atr,
            time_stop_bars=args.time_stop,
            spread=0.0 if args.spread is None else args.spread,
        )
        split = SplitSpec(args.split, args.train_fraction)
    except ValueError as exc:  # fixed messages naming the limit, never the input
        parser.error(str(exc))
    return Settings(
        args.source,
        args.tf,
        bars,
        slugs,
        rules,
        args.spread is not None,
        split,
        args.seed,
        args.stride,
    )


def csv_spread(paths: Sequence[str], bars: int) -> float:
    """The mean ``spread`` over the last ``bars`` rows of the CSV files that have the column
    (resampled ticks do), or 0 when none has it. Unreadable files are left to the loader."""
    values: list[pd.Series] = []
    for path in paths:
        try:
            frame = pd.read_csv(path, usecols=lambda name: str(name).lower() == SPREAD_COLUMN)
        except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError):
            continue
        if frame.shape[1] == 1:
            values.append(pd.to_numeric(frame.iloc[-bars:, 0], errors="coerce"))
    if not values:
        return 0.0
    spread = float(pd.concat(values).mean())
    if len(values) > 1:
        log.info("one spread for %d files: their mean, %g", len(values), spread)
    return spread if math.isfinite(spread) and spread >= 0 else 0.0


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    stats: JsonObject  # strict JSON, failures scrubbed, with the per-signal rows when present
    verdict: Verdict | None
    duration_seconds: float


def _pooled(
    loader: PreloadedLoader,
    symbols: Sequence[str],
    settings: Settings,
    strategy: Strategy,
    rules: ExitRules,
) -> JsonObject:
    report = run_backtest(
        loader,
        symbols,
        settings.timeframe,
        settings.bars,
        strategy,
        rules,
        seed=settings.seed,
        stride=settings.stride,
    )
    return report.to_dict()


def run_strategy(
    loader: PreloadedLoader,
    symbols: Sequence[str],
    settings: Settings,
    strategy: Strategy,
    rules: ExitRules,
    runner: WalkForwardRunner,
    *,
    with_rows: bool = False,
) -> StrategyResult:
    """Walk ``strategy`` forward. The walk-forward keeps no per-signal rows, so ``with_rows``
    (``--out``) also replays the pooled backtest for them and its stats: that run then takes
    about twice as long."""
    started = time.monotonic()
    result = runner(
        loader,
        symbols,
        settings.timeframe,
        settings.bars,
        strategy,
        rules,
        split=settings.split,
        seed=settings.seed,
        stride=settings.stride,
    )
    stats, verdict = result.to_dict(), parse_verdict(result.verdict)
    if with_rows:
        pooled = _pooled(loader, symbols, settings, strategy, rules)
        stats = {**stats, "pooled": pooled["pooled"], "signals": pooled["signals"]}
    return StrategyResult(strategy.slug, scrub_failures(stats), verdict, time.monotonic() - started)


def _part(stats: JsonObject, *keys: str) -> JsonObject | None:
    value: Any = stats
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, dict) else None


def _number(part: JsonObject | None, key: str, fmt: str = "{:.2f}") -> str:
    value = None if part is None else part.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return NO_VALUE
    return fmt.format(value)


def _expectancy(part: JsonObject | None) -> str:
    text = _number(part, "expectancy_r", "{:+.3f}")
    low, high = _number(part, "ci_low", "{:+.3f}"), _number(part, "ci_high", "{:+.3f}")
    return text if low == NO_VALUE else f"{text} [{low}, {high}]"


def _headline(stats: JsonObject) -> JsonObject | None:
    """The stats the table leads with: pooled when present, else out-of-sample."""
    return _part(stats, "pooled") or _part(stats, "out_of_sample")


def render(results: Sequence[StrategyResult], title: str) -> Table:
    table = Table(title=title)
    columns = (
        "strategy",
        "n",
        "hit rate",
        "expectancy R [95% CI]",
        "PF",
        "max DD R",
        "in-sample R",
        "out-of-sample R",
        "random R",
        "flipped R",
        "verdict",
    )
    for column in columns:
        table.add_column(column)
    for result in results:
        stats = result.stats
        head = _headline(stats)
        baselines = baselines_of(stats)
        cells = (
            result.strategy,
            _number(head, "n", "{}"),
            _number(head, "hit_rate", "{:.0%}"),
            _expectancy(head),
            _number(head, "profit_factor"),
            _number(head, "max_drawdown_r"),
            _expectancy(_part(stats, "in_sample")),
            _expectancy(_part(stats, "out_of_sample")),
            _expectancy(_part(baselines, "random")),
            _expectancy(_part(baselines, "flipped")),
            result.verdict or NO_VALUE,
        )
        table.add_row(*(Text(cell) for cell in cells))  # Text: no console markup from slugs
    return table


def _signal_rows(stats: JsonObject) -> list[dict[str, Any]]:
    rows = stats.get("signals")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def write_outputs(results: Sequence[StrategyResult], settings: Settings, out: Path) -> None:
    """``<strategy>.csv`` per strategy and ``summary.json`` in ``out`` (created if missing)."""
    out.mkdir(parents=True, exist_ok=True)
    for result in results:
        with (out / f"{result.strategy}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ROW_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in _signal_rows(result.stats):
                writer.writerow(
                    {k: csv_safe(v) if isinstance(v, str) else v for k, v in row.items()}
                )
    summary = {
        "source": settings.source,
        "timeframe": settings.timeframe,
        "bars": settings.bars,
        "split": asdict(settings.split),
        "seed": settings.seed,
        "stride": settings.stride,
        "strategies": [
            {
                "strategy": result.strategy,
                "verdict": result.verdict,
                "duration_seconds": result.duration_seconds,
                "stats": without_signals(result.stats),
            }
            for result in results
        ],
    }
    text = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)
    (out / SUMMARY_FILE).write_text(text + "\n", encoding="utf-8")


def _renamed(value: Any, names: dict[str, str]) -> Any:
    """``value`` with every string that is a key of ``names`` replaced, at any depth."""
    if isinstance(value, str):
        return names.get(value, value)
    if isinstance(value, dict):
        return {key: _renamed(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, names) for item in value]
    return value


def save_results(
    results: Sequence[StrategyResult],
    settings: Settings,
    symbols: Sequence[str],
    rules: ExitRules,
) -> None:
    """Store each result as a finished row. A csv symbol is a file path: only its file name is
    stored, since the API lists these rows."""
    names = {s: Path(s).name for s in symbols} if settings.source == "csv" else {}
    repository = SqliteBacktestRepository(db_path_from_env())
    for result in results:
        repository.insert(
            NewBacktest(
                strategy=result.strategy,
                source=settings.source,
                timeframe=settings.timeframe,
                bars=settings.bars,
                symbols=tuple(names.get(s, s) for s in symbols),
                rules=asdict(rules),
                split=settings.split.kind,
                train_fraction=settings.split.train_fraction,
                seed=settings.seed,
                stride=settings.stride,
                status="done",
                stats=_renamed(without_signals(result.stats), names),
                verdict=result.verdict,
                duration_seconds=result.duration_seconds,
            )
        )


def run(args: argparse.Namespace, settings: Settings, console: Console) -> int:
    strategies = [load_strategy(slug) for slug in settings.slugs]
    symbols = list(dict.fromkeys(resolve_symbols(args, settings.source)))
    rules = settings.rules
    if not settings.spread_given and settings.source == "csv":
        rules = replace(rules, spread=csv_spread(symbols, settings.bars))
    if settings.split.kind == "symbols" and len(symbols) < 2:
        log.error("--split symbols needs at least 2 symbols")
        return EXIT_FAILED
    loader = preload(make_loader(settings.source), symbols, settings.timeframe, settings.bars)
    if not loader.loaded:
        log.error("no symbol could be loaded (%d tried)", len(symbols))
        return EXIT_FAILED
    runner = walk_forward_runner()
    with_rows = args.out is not None
    results = [
        run_strategy(loader, symbols, settings, strategy, rules, runner, with_rows=with_rows)
        for strategy in strategies
    ]
    title = f"SMC backtest {settings.source} {settings.timeframe} ({settings.bars} bars)"
    console.print(render(results, title))
    if args.out is not None:
        write_outputs(results, settings, args.out)
        console.print(f"saved {len(results)} CSV file(s) and {SUMMARY_FILE} to {args.out}")
    if args.save:
        save_results(results, settings, symbols, rules)
        console.print(f"stored {len(results)} backtest(s)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = _settings(args, parser)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        return run(args, settings, Console())
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except (WatchlistError, LoaderError, StrategyChoiceError) as exc:
        log.error("%s", exc)
        return EXIT_FAILED
    except StoreError as exc:
        log.error("%s", exc)  # names the database path, which is the operator's own
        return EXIT_FAILED
    except OSError as exc:
        log.error("file error: %s", exc)
        return EXIT_FAILED
    except ValueError as exc:  # e.g. stats over the store's size cap, or a bad argument value
        log.error("backtest failed: %s", exc)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
