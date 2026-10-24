"""``/health``, ``/config`` and ``/scan``."""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from smc_scanner import __version__
from smc_scanner.ai.store import StoreError
from smc_scanner.api.constants import (
    API_SOURCES,
    INVALID_REQUEST_MESSAGE,
    MAX_SYMBOLS,
    MAX_SYMBOLS_QUERY_LENGTH,
    NOTHING_LOADED_MESSAGE,
    SLUG_REGEX,
)
from smc_scanner.api.deps import (
    InternalKeyDep,
    ScanRateDep,
    StrategyServiceDep,
    _ai_key_configured,
    _scan_lock,
)
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
from smc_scanner.api.strategy_deps import resolve_strategy
from smc_scanner.api.strategy_schemas import ConditionInfoOut, StrategySummary
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
from smc_scanner.scanner import ScanOptions, ScanResult
from smc_scanner.schedule.runner import (
    telegram_settings_from_env,
)
from smc_scanner.strategy.builtin import PRESETS
from smc_scanner.strategy.conditions import conditions
from smc_scanner.strategy.engine import run_scan_with_strategy
from smc_scanner.strategy.models import Strategy
from smc_scanner.strategy.service import StrategyService
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


def _strategy_summaries(service: StrategyService) -> list[StrategySummary]:
    """Every strategy, or the built-ins alone when the store cannot be read: the scan form
    must load even then."""
    try:
        found: tuple[Strategy, ...] = service.list()
    except StoreError as exc:
        log.warning("strategies unavailable for /config: %s", type(exc).__name__)
        found = PRESETS
    return [StrategySummary.from_strategy(strategy) for strategy in found]


@router.get("/config", response_model=ConfigResponse, tags=["scanner"])
def config(_: InternalKeyDep, service: StrategyServiceDep) -> ConfigResponse:
    """Choices, defaults and limits for the scan form, the watchlist per source, and the
    strategy and condition catalogues."""
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
        strategies=_strategy_summaries(service),
        conditions=[ConditionInfoOut.from_info(info) for info in conditions()],
    )


def _to_response(
    source: ApiSource, tf: Timeframe, strategy: Strategy, result: ScanResult
) -> ScanResponse:
    return ScanResponse(
        source=source,
        tf=tf,
        strategy=strategy.slug,
        count=len(result.rows),
        rows=[ScanRowOut.from_row(row, result.htf_bias.get(row.instrument)) for row in result.rows],
        failures=[ScanFailureOut(symbol=f.symbol, error=f.error) for f in result.failures],
    )


@dataclass(frozen=True)
class _ScanRequest:
    source: ApiSource
    symbols: list[str]
    tf: Timeframe
    bars: int
    mtf: bool
    require_htf_aligned: bool


def _locked_scan(request: _ScanRequest, strategy: Strategy, options: ScanOptions) -> ScanResult:
    """The scan under the scan lock: the MT5 connection is process-wide."""
    with _scan_lock:
        return run_scan_with_strategy(
            make_loader(request.source),
            request.symbols,
            request.tf,
            request.bars,
            strategy,
            options=options,
            mtf=request.mtf,
            require_htf_aligned=request.require_htf_aligned,
        )


@router.get(
    "/scan",
    response_model=ScanResponse,
    tags=["scanner"],
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Invalid parameters, e.g. require_htf_aligned without mtf, or an "
            "unknown strategy",
        },
        429: {
            "model": ErrorResponse,
            "description": "Too many scans; see the Retry-After header",
            "headers": RETRY_AFTER_HEADER,
        },
        503: {"model": ErrorResponse, "description": "Nothing loaded, or no strategy database"},
    },
)
def scan(
    _: InternalKeyDep,
    __: ScanRateDep,
    service: StrategyServiceDep,
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
    strategy: Annotated[
        str | None, Query(pattern=SLUG_REGEX, description="strategy slug; default smc-default")
    ] = None,
) -> ScanResponse:
    """Scan the given symbols (or the watchlist) on one timeframe.

    503 when no symbol could be loaded at all (terminal down, bad login); otherwise the
    per-symbol failures are listed next to the rows. With ``mtf`` each row carries ``htf_bias``;
    ``require_htf_aligned`` (422 without ``mtf``) drops rows it does not confirm, and rows whose
    higher timeframe is unknown are kept. ``strategy`` (422 when unknown) picks and scores the
    rows; the scan tuning stays this request's, and a strategy may turn ``mtf`` on, never off.
    """
    if require_htf_aligned and not mtf:
        raise HTTPException(status_code=422, detail=INVALID_REQUEST_MESSAGE)
    chosen = resolve_strategy(service, strategy)
    options = ScanOptions(swing_length=swing, near_atr=near, all_touches=all_touches)
    request = _ScanRequest(source, _symbols(source, symbols), tf, bars, mtf, require_htf_aligned)
    result = _locked_scan(request, chosen, options)
    if result.all_failed:
        raise HTTPException(status_code=503, detail=NOTHING_LOADED_MESSAGE)
    return _to_response(source, tf, chosen, result)
