"""Per-instrument scan and watchlist loop. Pure functions over OHLC frames; no I/O here
except logging."""

import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import pandas as pd

from smc_scanner.config import (
    DEFAULT_NEAR_ATR,
    DEFAULT_SWING_LENGTH,
    MIN_BARS,
    neighbour_timeframes,
)
from smc_scanner.loaders.base import Loader
from smc_scanner.models import BULLISH, Bias, ScanRow
from smc_scanner.mtf import htf_allows, htf_bias
from smc_scanner.scoring import score_zone
from smc_scanner.structure import analyse_structure, confirmed_swing_frame, confirmed_swings
from smc_scanner.zones import evaluate_zones, select_hits

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanOptions:
    swing_length: int = DEFAULT_SWING_LENGTH
    near_atr: float = DEFAULT_NEAR_ATR
    all_touches: bool = False

    def __post_init__(self) -> None:
        if self.swing_length < 1:
            raise ValueError("swing_length must be at least 1")
        if not math.isfinite(self.near_atr) or self.near_atr < 0:
            raise ValueError("near_atr must be a finite, non-negative number")


@dataclass(frozen=True)
class ScanFailure:
    symbol: str
    error: str


@dataclass(frozen=True)
class ScanResult:
    """Rows from the symbols that loaded, plus one failure per symbol that did not."""

    rows: tuple[ScanRow, ...]
    failures: tuple[ScanFailure, ...]
    scanned: int
    # With ``mtf``: the higher-timeframe bias per symbol that had a hit (None = unknown).
    htf_bias: Mapping[str, Bias | None] = field(default_factory=dict)

    @property
    def all_failed(self) -> bool:
        """True when nothing loaded at all (an outage looks different from "no hits")."""
        return self.scanned == 0 and bool(self.failures)


def scan_instrument(symbol: str, ohlc: pd.DataFrame, options: ScanOptions) -> list[ScanRow]:
    """Rows for every zone the latest candle is TOUCHING or NEAR, unsorted."""
    if len(ohlc) < MIN_BARS:
        raise ValueError(f"{symbol}: need at least {MIN_BARS} candles, got {len(ohlc)}")
    swings = confirmed_swings(ohlc, options.swing_length)
    structure = analyse_structure(ohlc, swings)
    valid = evaluate_zones(
        ohlc, confirmed_swing_frame(ohlc, swings), structure.atr, options.near_atr
    )
    last_index = len(ohlc) - 1
    close = float(ohlc["close"].iloc[last_index])
    bar_time = str(ohlc["time"].iloc[last_index])
    rows: list[ScanRow] = []
    for state in select_hits(valid, options.all_touches):
        if state.status is None:  # select_hits guarantees a status; keeps the type narrow
            continue
        confluence = score_zone(state, structure, valid, ohlc)
        side = "bull" if state.zone.direction == BULLISH else "bear"
        rows.append(
            ScanRow(
                instrument=symbol,
                status=state.status,
                zone=f"{side} {state.zone.kind}",
                zone_low=state.zone.bottom,
                zone_high=state.zone.top,
                price=close,
                dist_atr=state.distance_atr,
                bias=structure.bias,
                in_ote=confluence.in_ote,
                trendline_ok=confluence.trendline_ok,
                ob_fvg=confluence.stacked,
                score=confluence.score,
                zone_age=last_index - state.zone.formed_index,
                prior_touches=state.prior_touches,
                bar_time=bar_time,
            )
        )
    return rows


def sort_rows(rows: Iterable[ScanRow]) -> list[ScanRow]:
    """TOUCHING first, then higher score, then smaller distance."""
    return sorted(rows, key=lambda row: (row.status != "TOUCHING", -row.score, row.dist_atr))


def _load_htf_bias(
    loader: Loader, symbol: str, higher: str | None, bars: int, options: ScanOptions
) -> Bias | None:
    """The higher timeframe's bias, or None when there is none or it cannot be loaded."""
    if higher is None:
        return None
    try:
        return htf_bias(loader.load(symbol, higher, bars), options.swing_length)
    except Exception as exc:  # noqa: BLE001 - a missing HTF must not fail the symbol
        log.warning("%r: no %s bias (%s)", symbol, higher, type(exc).__name__)
        return None


def _prefetch_lower(
    loader: Loader, rows: Iterable[ScanRow], lower: str | None, bars: int, min_score: int
) -> None:
    """Load the lower timeframe for the symbols with a row the AI may analyse, so the analyst
    can read it from the loader's cache after the loader is closed."""
    if lower is None:
        return
    for symbol in dict.fromkeys(row.instrument for row in rows if row.score >= min_score):
        try:
            loader.load(symbol, lower, bars)
        except Exception as exc:  # noqa: BLE001 - the AI block is optional
            log.warning("%r: no %s data (%s)", symbol, lower, type(exc).__name__)


def scan_watchlist(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    options: ScanOptions,
    *,
    mtf: bool = False,
    require_htf_aligned: bool = False,
    ltf_min_score: int | None = None,
) -> ScanResult:
    """Scan each symbol in turn. A failing symbol is logged, recorded and skipped.

    ``mtf`` adds the higher timeframe's bias for every symbol with a hit (``ScanResult.htf_bias``).
    ``require_htf_aligned`` (needs ``mtf``) then drops rows the HTF does not confirm; an unknown
    HTF passes. ``ltf_min_score`` (with ``mtf``) loads the lower timeframe for hits scoring at
    least that, for the analyst; nothing is computed from it here.
    """
    if require_htf_aligned and not mtf:
        raise ValueError("require_htf_aligned needs mtf")
    higher, lower = neighbour_timeframes(timeframe) if mtf else (None, None)
    rows: list[ScanRow] = []
    failures: list[ScanFailure] = []
    htf: dict[str, Bias | None] = {}
    scanned = 0
    for symbol in symbols:
        try:
            ohlc = loader.load(symbol, timeframe, bars)
            found = scan_instrument(symbol, ohlc, options)
            if mtf and found:
                htf[symbol] = _load_htf_bias(loader, symbol, higher, bars, options)
                if require_htf_aligned:
                    found = [row for row in found if htf_allows(row, htf[symbol])]
            rows.extend(found)
            scanned += 1
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the scan
            message = f"{type(exc).__name__}: {exc}"
            log.error("%r: skipped (%s)", symbol, message)
            failures.append(ScanFailure(symbol=symbol, error=message))
    if mtf and ltf_min_score is not None:
        _prefetch_lower(loader, rows, lower, bars, ltf_min_score)
    return ScanResult(
        rows=tuple(sort_rows(rows)), failures=tuple(failures), scanned=scanned, htf_bias=htf
    )


def run_scan(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    options: ScanOptions,
    *,
    mtf: bool = False,
    require_htf_aligned: bool = False,
    ltf_min_score: int | None = None,
) -> ScanResult:
    """``scan_watchlist`` with the loader closed afterwards, whatever happens."""
    try:
        return scan_watchlist(
            loader,
            symbols,
            timeframe,
            bars,
            options,
            mtf=mtf,
            require_htf_aligned=require_htf_aligned,
            ltf_min_score=ltf_min_score,
        )
    finally:
        loader.close()
