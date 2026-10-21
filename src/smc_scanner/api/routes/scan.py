"""``/health``, ``/config`` and ``/scan``."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from smc_scanner import __version__
from smc_scanner.api.constants import (
    API_SOURCES,
    INVALID_REQUEST_MESSAGE,
    MAX_SYMBOLS,
    MAX_SYMBOLS_QUERY_LENGTH,
    NOTHING_LOADED_MESSAGE,
)
from smc_scanner.api.deps import InternalKeyDep, ScanRateDep, _ai_key_configured, _scan_lock
from smc_scanner.api.helpers import _symbols
from smc_scanner.api.schemas import (
    RETRY_AFTER_HEADER,
    ConfigResponse,
    ErrorResponse,
    HealthResponse,
    ScanDefaults,
    ScanFailureOut,
    ScanLimits,
    ScanResponse,
    ScanRowOut,
)
from smc_scanner.config import (
    DEFAULT_BARS,
    DEFAULT_NEAR_ATR,
    DEFAULT_SWING_LENGTH,
    DEFAULT_TIMEFRAME,
    MAX_BARS,
    MAX_NEAR_ATR,
    MAX_SWING_LENGTH,
    MIN_BARS,
    TIMEFRAMES,
    ApiSource,
    Timeframe,
)
from smc_scanner.loaders import make_loader
from smc_scanner.scanner import ScanOptions, ScanResult, run_scan
from smc_scanner.schedule.runner import (
    telegram_settings_from_env,
)
from smc_scanner.watchlist import DEFAULT_WATCHLIST, WatchlistError, resolve_symbols

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["scanner"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


def _watchlist_symbols(source: ApiSource) -> list[str]:
    try:
        return resolve_symbols(DEFAULT_WATCHLIST, source)
    except WatchlistError as exc:
        log.error("watchlist (%s): %s", source, exc)
        return []


@router.get("/config", response_model=ConfigResponse, tags=["scanner"])
def config(_: InternalKeyDep) -> ConfigResponse:
    """Choices, defaults and limits for the scan form, plus the watchlist per source."""
    return ConfigResponse(
        sources=list(API_SOURCES),
        timeframes=list(TIMEFRAMES),  # type: ignore[arg-type]
        defaults=ScanDefaults(
            source="mt5",
            tf=DEFAULT_TIMEFRAME,
            bars=DEFAULT_BARS,
            swing=DEFAULT_SWING_LENGTH,
            near=DEFAULT_NEAR_ATR,
        ),
        limits=ScanLimits(
            min_bars=MIN_BARS,
            max_bars=MAX_BARS,
            max_swing=MAX_SWING_LENGTH,
            max_near=MAX_NEAR_ATR,
            max_symbols=MAX_SYMBOLS,
        ),
        watchlist={source: _watchlist_symbols(source) for source in API_SOURCES},
        ai_enabled=_ai_key_configured(),
        telegram_enabled=bool(telegram_settings_from_env()[0]),
    )


def _to_response(source: ApiSource, tf: Timeframe, result: ScanResult) -> ScanResponse:
    return ScanResponse(
        source=source,
        tf=tf,
        count=len(result.rows),
        rows=[ScanRowOut.from_row(row, result.htf_bias.get(row.instrument)) for row in result.rows],
        failures=[ScanFailureOut(symbol=f.symbol, error=f.error) for f in result.failures],
    )


@router.get(
    "/scan",
    response_model=ScanResponse,
    tags=["scanner"],
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Invalid parameters, e.g. require_htf_aligned without mtf",
        },
        429: {
            "model": ErrorResponse,
            "description": "Too many scans; see the Retry-After header",
            "headers": RETRY_AFTER_HEADER,
        },
    },
)
def scan(
    _: InternalKeyDep,
    __: ScanRateDep,
    source: ApiSource = "mt5",
    tf: Timeframe = DEFAULT_TIMEFRAME,
    symbols: Annotated[
        str | None,
        Query(
            description="comma-separated; default watchlist", max_length=MAX_SYMBOLS_QUERY_LENGTH
        ),
    ] = None,
    bars: Annotated[int, Query(ge=MIN_BARS, le=MAX_BARS)] = DEFAULT_BARS,
    swing: Annotated[int, Query(ge=1, le=MAX_SWING_LENGTH)] = DEFAULT_SWING_LENGTH,
    near: Annotated[float, Query(ge=0, le=MAX_NEAR_ATR)] = DEFAULT_NEAR_ATR,
    all_touches: bool = False,
    mtf: Annotated[
        bool, Query(description="also report the higher-timeframe bias of each row")
    ] = False,
    require_htf_aligned: Annotated[
        bool, Query(description="drop rows the higher timeframe does not confirm; needs mtf")
    ] = False,
) -> ScanResponse:
    """Scan the given symbols (or the watchlist) on one timeframe.

    503 when no symbol could be loaded at all (terminal down, bad login); otherwise the
    per-symbol failures are listed next to the rows. With ``mtf`` each row carries ``htf_bias``;
    ``require_htf_aligned`` (422 without ``mtf``) drops rows it does not confirm, and rows whose
    higher timeframe is unknown are kept.
    """
    if require_htf_aligned and not mtf:
        raise HTTPException(status_code=422, detail=INVALID_REQUEST_MESSAGE)
    options = ScanOptions(swing_length=swing, near_atr=near, all_touches=all_touches)
    wanted = _symbols(source, symbols)
    with _scan_lock:
        result = run_scan(
            make_loader(source),
            wanted,
            tf,
            bars,
            options,
            mtf=mtf,
            require_htf_aligned=require_htf_aligned,
        )
    if result.all_failed:
        raise HTTPException(status_code=503, detail=NOTHING_LOADED_MESSAGE)
    return _to_response(source, tf, result)
