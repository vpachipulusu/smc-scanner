"""``smc-scan`` command line: scan once or every N minutes, print a table, save a CSV."""

import argparse
import logging
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from rich.console import Console

from smc_scanner.config import (
    DEFAULT_BARS,
    DEFAULT_NEAR_ATR,
    DEFAULT_OUTPUT_CSV,
    DEFAULT_SOURCE,
    DEFAULT_SWING_LENGTH,
    DEFAULT_TIMEFRAME,
    MAX_BARS,
    MAX_NEAR_ATR,
    MAX_SWING_LENGTH,
    MIN_BARS,
    SOURCES,
    TIMEFRAMES,
)
from smc_scanner.loaders import LoaderError, make_loader
from smc_scanner.report import render_table, write_csv
from smc_scanner.scanner import ScanOptions, ScanResult, run_scan
from smc_scanner.watchlist import DEFAULT_WATCHLIST, WatchlistError
from smc_scanner.watchlist import resolve_symbols as watchlist_symbols

log = logging.getLogger("smc_scanner")

SECONDS_PER_MINUTE = 60
EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smc-scan",
        description="Report instruments touching or near a fresh order block or fair value "
        "gap. Screening only; never places trades.",
    )
    parser.add_argument("--source", choices=SOURCES, default=DEFAULT_SOURCE)
    parser.add_argument("--demo", action="store_true", help="simulated prices, no keys needed")
    parser.add_argument("--symbols", nargs="+", metavar="SYMBOL", help="override the watchlist")
    parser.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--tf", choices=TIMEFRAMES, default=DEFAULT_TIMEFRAME)
    parser.add_argument("--bars", type=int, default=DEFAULT_BARS)
    parser.add_argument("--swing", type=int, default=DEFAULT_SWING_LENGTH)
    parser.add_argument("--near", type=float, default=DEFAULT_NEAR_ATR, help="NEAR limit in ATR")
    parser.add_argument("--all-touches", action="store_true", help="include zones touched before")
    parser.add_argument("--every", type=int, metavar="N", help="rescan every N minutes")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUTPUT_CSV), help="CSV path")
    parser.add_argument(
        "--include-forming", action="store_true", help="MT5: also scan the still-forming candle"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not MIN_BARS <= args.bars <= MAX_BARS:
        parser.error(f"--bars must be between {MIN_BARS} and {MAX_BARS}")
    if not 1 <= args.swing <= MAX_SWING_LENGTH:
        parser.error(f"--swing must be between 1 and {MAX_SWING_LENGTH}")
    if not math.isfinite(args.near) or not 0 <= args.near <= MAX_NEAR_ATR:
        parser.error(f"--near must be between 0 and {MAX_NEAR_ATR}")
    if args.every is not None and args.every < 1:
        parser.error("--every must be at least 1 minute")


def resolve_symbols(args: argparse.Namespace, source: str) -> list[str]:
    if args.symbols:
        return list(args.symbols)
    return watchlist_symbols(args.watchlist, source)


def _report(result: ScanResult, args: argparse.Namespace, source: str, console: Console) -> int:
    """Print the table and save the CSV. The CSV is left untouched when nothing loaded, so
    an outage never overwrites the previous results with an empty file."""
    if result.all_failed:
        log.error(
            "no symbol could be loaded (%d failed); keeping %s", len(result.failures), args.out
        )
        return EXIT_FAILED
    console.print(render_table(result.rows, title=f"SMC scan {source} {args.tf}"))
    try:
        write_csv(result.rows, args.out)
    except OSError as exc:
        log.error("could not write %s: %s", args.out, exc)
        return EXIT_FAILED
    console.print(f"saved {len(result.rows)} rows to {args.out}")
    if result.failures:
        console.print(f"{len(result.failures)} symbol(s) skipped, see log")
    return EXIT_OK


def run_once(args: argparse.Namespace, source: str, symbols: list[str], console: Console) -> int:
    options = ScanOptions(swing_length=args.swing, near_atr=args.near, all_touches=args.all_touches)
    result = run_scan(
        make_loader(source, closed_only=not args.include_forming),
        symbols,
        args.tf,
        args.bars,
        options,
    )
    return _report(result, args, source, console)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate(args, parser)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    source = "demo" if args.demo else args.source
    console = Console()
    try:
        symbols = resolve_symbols(args, source)
        if args.every is None:
            return run_once(args, source, symbols, console)
        while True:
            run_once(args, source, symbols, console)  # a failed cycle is logged, not fatal
            console.print(f"next scan in {args.every} min (Ctrl-C to stop)")
            time.sleep(args.every * SECONDS_PER_MINUTE)
    except KeyboardInterrupt:
        console.print("stopped")
        return EXIT_OK
    except (WatchlistError, LoaderError) as exc:
        log.error("%s", exc)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
