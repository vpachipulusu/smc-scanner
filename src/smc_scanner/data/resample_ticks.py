"""``smc-resample-ticks``: a Dukascopy tick export to per-timeframe candle CSVs.

The input is a Tick Data Suite export: a headerless ``timestamp,bid,ask`` CSV such as
``2003.05.05 00:00:00.773,1.60377,1.60417``, either plain or as the one CSV member of a zip that
is streamed in place (never extracted). Candles are keyed by their open time in the file's own
clock (GMT+2 with EU DST for these exports); there is no timezone conversion. ``volume`` is the
tick count and ``spread`` the mean ask - bid of the candle. ``<SYMBOL>_<tf>.csv`` files are read
unchanged by the CSV loader, which ignores the extra ``spread`` column. See ``docs/data.md``.
"""

import argparse
import bisect
import csv
import logging
import lzma
import os
import re
import sys
import warnings
import zipfile
import zlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import IO, Final, TextIO

import numpy as np
import pandas as pd

from smc_scanner.config import TIMEFRAME_MINUTES, TIMEFRAMES

log = logging.getLogger(__name__)

TIMESTAMP_FORMAT: Final = "%Y.%m.%d %H:%M:%S.%f"
OUTPUT_TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%S"
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "spread",
)
PRICE_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close")
# A fourth name catches a line with one extra field; pandas skips wider lines with a warning.
INPUT_COLUMNS: Final[tuple[str, ...]] = ("time", "bid", "ask", "extra")
WIDE_LINE_PATTERN: Final = re.compile(r"Skipping line (\d+)")
SYMBOL_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
PRICE_CHOICES: Final[tuple[str, ...]] = ("mid", "bid")
DEFAULT_PRICE: Final = "mid"
DEFAULT_CHUNK_ROWS: Final[int] = 1_000_000
MAX_CHUNK_ROWS: Final[int] = 20_000_000
MAX_SKIPPED_FRACTION: Final[float] = 0.0001  # 0.01% of lines
MAX_LOGGED_BAD_LINES: Final[int] = 50
# Line numbers of over-wide lines are kept to number later bad lines; cap that memory.
MAX_WIDE_LINES: Final[int] = 100_000
# A run whose skip rate is this many times the limit, after this many lines, stops early: a
# corrupt future timestamp would otherwise make every later tick "out of order" for hours.
ABORT_SKIPPED_FACTOR: Final[int] = 10
ABORT_MIN_LINES: Final[int] = 100_000
MAX_DECIMALS: Final[int] = 10
# The mean spread is kept to a hundredth of a point.
SPREAD_EXTRA_DECIMALS: Final[int] = 2
PART_SUFFIX: Final = ".part"
EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1


class ResampleError(Exception):
    """The export could not be turned into candle files; the message is safe to print."""


def default_symbol(source: Path) -> str:
    """``GBPUSD_GMT+2_EU-DST.zip`` -> ``GBPUSD``: the file name before the first ``_``."""
    return source.stem.split("_", 1)[0]


@dataclass(frozen=True)
class ResampleOptions:
    source: Path
    out_dir: Path
    symbol: str
    timeframes: tuple[str, ...] = TIMEFRAMES
    price: str = DEFAULT_PRICE
    start: date | None = None
    chunk_rows: int = DEFAULT_CHUNK_ROWS
    force: bool = False

    def __post_init__(self) -> None:
        if not SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError(
                f"symbol {self.symbol!r} must be 1-64 of A-Z, a-z, 0-9, '.', '_' or '-' "
                "starting with a letter or digit (pass --symbol)"
            )
        if not self.timeframes or any(tf not in TIMEFRAMES for tf in self.timeframes):
            raise ValueError(f"timeframes must be some of {', '.join(TIMEFRAMES)}")
        if self.price not in PRICE_CHOICES:
            raise ValueError(f"price must be one of {', '.join(PRICE_CHOICES)}")
        if not 1 <= self.chunk_rows <= MAX_CHUNK_ROWS:
            raise ValueError(f"--chunk-rows must be between 1 and {MAX_CHUNK_ROWS}")

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "ResampleOptions":
        return cls(
            source=args.source,
            out_dir=args.out,
            symbol=default_symbol(args.source) if args.symbol is None else args.symbol,
            timeframes=args.timeframes,
            price=args.price,
            start=args.start,
            chunk_rows=args.chunk_rows,
            force=args.force,
        )

    def target(self, timeframe: str) -> Path:
        return self.out_dir / f"{self.symbol}_{timeframe}.csv"


@dataclass(frozen=True)
class ResampleReport:
    lines: int
    skipped: int
    candles: dict[str, int]

    @property
    def skipped_fraction(self) -> float:
        return self.skipped / self.lines if self.lines else 0.0


@dataclass
class _Progress:
    """Counters carried from chunk to chunk while one file streams through."""

    lines: int = 0
    skipped: int = 0
    kept: int = 0
    decimals: int = 0
    last_time: pd.Timestamp | None = None
    wide_lines: list[int] = field(default_factory=list)

    def skip(self, line: int, reason: str) -> None:
        self.skipped += 1
        if self.skipped <= MAX_LOGGED_BAD_LINES:
            log.warning("line %d: %s, skipped", line, reason)
        if self.skipped == MAX_LOGGED_BAD_LINES:
            log.warning("further skipped lines are counted but not logged")


# --- reading -------------------------------------------------------------------------------


def _csv_member(archive: zipfile.ZipFile, source: Path) -> zipfile.ZipInfo:
    """The zip's single CSV member. Its name is only matched, never used as a path."""
    members = [
        info
        for info in archive.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".csv")
    ]
    if not members:
        raise ResampleError(f"{source}: no CSV member in the zip")
    if len(members) > 1:
        raise ResampleError(f"{source}: {len(members)} CSV members in the zip, expected one")
    return members[0]


@contextmanager
def open_ticks(source: Path) -> Iterator[IO[bytes]]:
    """A binary stream of the tick CSV: the file itself, or its zip member read in place."""
    if not source.is_file():
        raise ResampleError(f"tick file not found: {source}")
    if source.suffix.lower() != ".zip":
        with source.open("rb") as stream:
            yield stream
        return
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise ResampleError(f"{source}: not a readable zip file ({exc})") from exc
    with archive:
        member = _csv_member(archive, source)
        try:
            member_stream = archive.open(member)
        except (RuntimeError, NotImplementedError) as exc:  # encrypted or unknown compression
            raise ResampleError(f"{source}: cannot read {member.filename!r} ({exc})") from exc
        with member_stream:
            yield member_stream


def _raw_chunks(stream: IO[bytes], chunk_rows: int) -> Iterator[tuple[pd.DataFrame, list[int]]]:
    """(rows as text, line numbers of over-wide lines pandas skipped) per chunk.

    Blank lines are kept as empty rows so every row maps back to a line; the frame index counts
    the rows pandas returned, which is the line number minus the skipped wide lines before it.
    """
    try:
        reader = pd.read_csv(
            stream,
            header=None,
            names=list(INPUT_COLUMNS),
            dtype={"time": str},  # prices left to the C parser: floats unless a line is bad
            index_col=False,  # a wide first line must not turn columns into an index
            chunksize=chunk_rows,
            on_bad_lines="warn",
            skip_blank_lines=False,
            quoting=csv.QUOTE_NONE,
            encoding="latin-1",  # never fails to decode; odd bytes just fail to parse
        )
    except pd.errors.EmptyDataError:
        return
    with reader:
        while True:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", pd.errors.ParserWarning)
                try:
                    frame = reader.get_chunk()
                except StopIteration:
                    return
            wide = [
                int(number)
                for warning in caught
                for number in WIDE_LINE_PATTERN.findall(str(warning.message))
            ]
            yield frame, wide


# --- cleaning ------------------------------------------------------------------------------


def _line_numbers(rows: Sequence[int], wide_lines: list[int]) -> list[int]:
    """File line numbers (1-based) of returned rows, given the sorted skipped wide lines."""
    numbers = []
    for row in rows:
        line = row + 1
        while (shifted := row + 1 + bisect.bisect_right(wide_lines, line)) != line:
            line = shifted
        numbers.append(line)
    return numbers


def _note_wide_lines(wide: list[int], progress: _Progress) -> None:
    for line in wide:
        progress.skip(line, "too many fields")
    progress.wide_lines.extend(wide)
    progress.lines += len(wide)
    if len(progress.wide_lines) > MAX_WIDE_LINES:
        raise ResampleError(
            f"more than {MAX_WIDE_LINES:,} lines with too many fields: not a tick export?"
        )


def _decimals(prices: pd.Series) -> int:
    """Fewest decimals that hold every price of the chunk exactly (exports drop trailing 0s)."""
    values = prices.to_numpy(dtype=float)
    for decimals in range(MAX_DECIMALS):
        if np.allclose(np.round(values, decimals), values, rtol=1e-12, atol=0.0):
            return decimals
    return MAX_DECIMALS


def _parse(frame: pd.DataFrame) -> tuple[pd.DataFrame, "pd.Series[bool]"]:
    """Typed ``time, bid, ask`` and a mask of the rows that parsed cleanly."""
    parsed = pd.DataFrame(
        {
            "time": pd.to_datetime(frame["time"], format=TIMESTAMP_FORMAT, errors="coerce"),
            "bid": pd.to_numeric(frame["bid"], errors="coerce"),
            "ask": pd.to_numeric(frame["ask"], errors="coerce"),
        },
        index=frame.index,
    )
    prices = parsed[["bid", "ask"]].to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):  # NaN comparisons are simply False
        quoted = (
            np.isfinite(prices).all(axis=1) & (prices[:, 0] > 0) & (prices[:, 1] >= prices[:, 0])
        )
    valid = parsed["time"].notna() & frame["extra"].isna() & quoted
    return parsed, valid


def _out_of_order(times: pd.Series, last_time: pd.Timestamp | None) -> "pd.Series[bool]":
    """Ticks older than any tick before them (in this chunk or an earlier one)."""
    running = times.cummax().shift(1)
    if last_time is not None:
        running = running.where(running > last_time, last_time)
    return times < running


def _clean(frame: pd.DataFrame, wide: list[int], progress: _Progress) -> pd.DataFrame:
    """The chunk's well-formed, in-order ticks; every other line is counted and logged."""
    _note_wide_lines(wide, progress)
    progress.lines += len(frame)
    parsed, valid = _parse(frame)
    older = _out_of_order(parsed.loc[valid, "time"], progress.last_time)
    good = valid.copy()
    good.loc[older.index[older.to_numpy()]] = False
    rows = [int(row) for row in frame.index[~good.to_numpy()]]
    for row, line in zip(rows, _line_numbers(rows, progress.wide_lines), strict=True):
        progress.skip(line, "tick older than the one before" if valid[row] else "malformed tick")
    ticks = parsed[good]
    if not ticks.empty:
        latest = ticks["time"].max()
        if progress.last_time is None or latest > progress.last_time:
            progress.last_time = latest
        sampled = max(_decimals(ticks["bid"]), _decimals(ticks["ask"]))
        progress.decimals = max(progress.decimals, sampled)
    return ticks


def _price_ticks(ticks: pd.DataFrame, options: ResampleOptions) -> pd.DataFrame:
    """``time, price, spread`` from the start date on, price being mid or bid."""
    if options.start is not None:
        ticks = ticks[ticks["time"] >= pd.Timestamp(options.start)]
    price = ticks["bid"] if options.price == "bid" else (ticks["bid"] + ticks["ask"]) / 2
    return pd.DataFrame(
        {"time": ticks["time"], "price": price, "spread": ticks["ask"] - ticks["bid"]}
    )


# --- candles -------------------------------------------------------------------------------


def _aggregate(ticks: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Candles of one chunk keyed by bar open; ``spread_sum`` is divided by ``volume`` later."""
    bars = ticks["time"].dt.floor(f"{TIMEFRAME_MINUTES[timeframe]}min").rename("time")
    grouped = ticks.groupby(bars, sort=True)
    return grouped.agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("price", "size"),
        spread_sum=("spread", "sum"),
    ).reset_index()


def _stitch(pending: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """Joins the still-open candle with a chunk's candles; the open one may continue in it."""
    combined = pd.concat([pending, fresh], ignore_index=True)
    return (
        combined.groupby("time", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            spread_sum=("spread_sum", "sum"),
        )
        .reset_index()
    )


def _format(candles: pd.DataFrame, price_decimals: int, spread_decimals: int) -> pd.DataFrame:
    price_text = f"{{:.{price_decimals}f}}".format
    spread = candles["spread_sum"] / candles["volume"]
    return pd.DataFrame(
        {
            "time": candles["time"].dt.strftime(OUTPUT_TIME_FORMAT),
            **{column: candles[column].map(price_text) for column in PRICE_COLUMNS},
            "volume": candles["volume"],
            "spread": spread.map(f"{{:.{spread_decimals}f}}".format),
        }
    )


class _CandleFiles:
    """One ``.part`` file per timeframe, renamed into place only when the run completes.

    Only the newest candle of each timeframe stays in memory: it may continue in the next chunk.
    """

    def __init__(self, options: ResampleOptions) -> None:
        self._targets = {tf: options.target(tf) for tf in options.timeframes}
        self._parts = {tf: Path(f"{path}{PART_SUFFIX}") for tf, path in self._targets.items()}
        self._handles: dict[str, TextIO] = {}
        self._pending: dict[str, pd.DataFrame] = {}
        self._mid = options.price == "mid"
        self.counts = dict.fromkeys(options.timeframes, 0)

    def open(self) -> None:
        """Creates each ``.part`` afresh: a leftover one (or a link of that name) is removed
        rather than followed, and exclusive creation fails if another run races for it."""
        for timeframe, part in self._parts.items():
            if part.exists() or part.is_symlink():
                log.warning("removing leftover %s", part)
                part.unlink()
            handle = part.open("x", encoding="ascii", newline="")
            self._handles[timeframe] = handle
            handle.write(",".join(OUTPUT_COLUMNS) + "\n")

    def add(self, ticks: pd.DataFrame, decimals: int) -> None:
        if ticks.empty:
            return
        for timeframe in self._parts:
            fresh = _aggregate(ticks, timeframe)
            pending = self._pending.get(timeframe)
            candles = fresh if pending is None else _stitch(pending, fresh)
            self._write(timeframe, candles.iloc[:-1], decimals)
            self._pending[timeframe] = candles.iloc[-1:].copy()  # not a view of the chunk

    def _write(self, timeframe: str, candles: pd.DataFrame, decimals: int) -> None:
        if candles.empty:
            return
        # A mid of two prices has one more digit (a half point); keep it rather than round it.
        price_decimals = decimals + 1 if self._mid else decimals
        rows = _format(candles, price_decimals, decimals + SPREAD_EXTRA_DECIMALS)
        rows.to_csv(self._handles[timeframe], header=False, index=False, lineterminator="\n")
        self.counts[timeframe] += len(rows)

    def finish(self, decimals: int) -> None:
        """Writes the open candles and renames every file into place (one rename per
        timeframe: a rename failing part-way leaves the earlier timeframes replaced)."""
        for timeframe, pending in self._pending.items():
            self._write(timeframe, pending, decimals)
        self._close()
        for timeframe, part in self._parts.items():
            os.replace(part, self._targets[timeframe])

    def discard(self) -> None:
        try:
            self._close()
        finally:
            for part in self._parts.values():
                part.unlink(missing_ok=True)

    def _close(self) -> None:
        handles, self._handles = self._handles, {}
        failure: OSError | None = None
        for handle in handles.values():
            try:
                handle.close()
            except OSError as exc:  # e.g. disk full on the final flush; close the rest first
                failure = failure or exc
        if failure is not None:
            raise failure


# --- run -----------------------------------------------------------------------------------


def _check_targets(options: ResampleOptions) -> None:
    existing = [options.target(tf) for tf in options.timeframes if options.target(tf).exists()]
    if any(path.resolve() == options.source.resolve() for path in existing):
        raise ResampleError(f"{options.source}: the input would be overwritten by an output")
    if existing and not options.force:
        names = ", ".join(str(path) for path in existing)
        raise ResampleError(f"{names} already exist; pass --force to overwrite")


def _abort_if_hopeless(progress: _Progress) -> None:
    limit = ABORT_SKIPPED_FACTOR * MAX_SKIPPED_FRACTION * progress.lines
    if progress.lines >= ABORT_MIN_LINES and progress.skipped > limit:
        raise ResampleError(
            f"{progress.skipped:,} of {progress.lines:,} lines skipped so far; stopping "
            "(a corrupt timestamp makes every later tick out of order)"
        )


def _stream(options: ResampleOptions, files: _CandleFiles) -> _Progress:
    progress = _Progress()
    try:
        with open_ticks(options.source) as stream:
            for number, (frame, wide) in enumerate(_raw_chunks(stream, options.chunk_rows), 1):
                ticks = _price_ticks(_clean(frame, wide, progress), options)
                progress.kept += len(ticks)
                files.add(ticks, progress.decimals)
                at = "-" if progress.last_time is None else f"{progress.last_time:%Y-%m-%d}"
                log.info("chunk %d: %s lines read, at %s", number, f"{progress.lines:,}", at)
                _abort_if_hopeless(progress)
    except (zipfile.BadZipFile, zlib.error, lzma.LZMAError, EOFError, pd.errors.ParserError) as exc:
        raise ResampleError(f"{options.source}: read failed ({exc})") from exc
    return progress


def resample(options: ResampleOptions) -> ResampleReport:
    """Streams ``options.source`` into one candle CSV per timeframe under ``options.out_dir``.

    Existing outputs are kept unless ``force``; a failed run leaves no partial files behind.
    """
    _check_targets(options)
    options.out_dir.mkdir(parents=True, exist_ok=True)
    files = _CandleFiles(options)
    try:
        files.open()
        progress = _stream(options, files)
        if progress.kept == 0:
            raise ResampleError(f"{options.source}: no ticks to resample")
        files.finish(progress.decimals)
    except BaseException:
        files.discard()
        raise
    return ResampleReport(lines=progress.lines, skipped=progress.skipped, candles=files.counts)


# --- command line --------------------------------------------------------------------------


def _timeframes(text: str) -> tuple[str, ...]:
    chosen = tuple(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))
    unknown = [tf for tf in chosen if tf not in TIMEFRAMES]
    if not chosen or unknown:
        raise argparse.ArgumentTypeError(
            f"{text!r}: pick from {', '.join(TIMEFRAMES)}, comma-separated"
        )
    return chosen


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smc-resample-ticks",
        description="Turn a Dukascopy tick export (timestamp,bid,ask; .zip or .csv) into "
        "<SYMBOL>_<tf>.csv candle files for the csv source. Times stay in the file's clock.",
    )
    parser.add_argument("source", type=Path, help="tick export, .zip (read in place) or .csv")
    parser.add_argument("--out", type=Path, required=True, help="directory for the candle files")
    parser.add_argument("--symbol", help="output name (default: file name before the first _)")
    parser.add_argument(
        "--timeframes", type=_timeframes, default=TIMEFRAMES, help="comma-separated list"
    )
    parser.add_argument("--price", choices=PRICE_CHOICES, default=DEFAULT_PRICE)
    parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, metavar="YYYY-MM-DD", help="first day"
    )
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS, metavar="N")
    parser.add_argument("--force", action="store_true", help="overwrite existing candle files")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _verdict(report: ResampleReport) -> int:
    for timeframe, count in report.candles.items():
        log.info("%s: %s candles", timeframe, f"{count:,}")
    summary = f"{report.skipped:,} of {report.lines:,} lines skipped"
    if report.skipped_fraction > MAX_SKIPPED_FRACTION:
        log.error(
            "%s (%.4f%%), above the %.2f%% limit",
            summary,
            100 * report.skipped_fraction,
            100 * MAX_SKIPPED_FRACTION,
        )
        return EXIT_FAILED
    log.info("%s", summary)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        options = ResampleOptions.from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        report = resample(options)
    except (ResampleError, OSError) as exc:
        log.error("%s", exc)
        return EXIT_FAILED
    return _verdict(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
