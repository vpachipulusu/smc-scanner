"""FastAPI wrapper over ``run_scan`` for the Next.js frontend (``nextjs-frontend/``).

    uvicorn smc_scanner.api:app --host 127.0.0.1 --port 8000

Only the Next.js *server* calls this API (the browser never does), the same split as
StoreCart: no CORS, loopback-only hosts (``SMC_API_ALLOWED_HOSTS``, default
``127.0.0.1,localhost``), and an optional shared key. When ``SMC_INTERNAL_KEY`` is set,
``/scan`` and ``/config`` require it in ``X-Internal-Key``; unset means open on loopback,
which is fine for a single-user machine.

Every error body is ``{"success": false, "error": "..."}`` so the generated TypeScript
client and the frontend's ``callBackend`` see one shape. Sources are ``mt5`` and ``demo``;
the csv source takes file paths, so it is CLI-only. Scans are serialised with a lock
because the MT5 connection is process-wide.
"""

import logging
import os
import re
import secrets
import threading
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from smc_scanner import __version__
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
from smc_scanner.models import Bias, ScanRow, Status
from smc_scanner.scanner import ScanOptions, ScanResult, run_scan
from smc_scanner.watchlist import DEFAULT_WATCHLIST, WatchlistError, resolve_symbols

log = logging.getLogger(__name__)
load_dotenv()

API_SOURCES: tuple[ApiSource, ...] = ("mt5", "demo")
MAX_SYMBOLS = 50
MAX_SYMBOLS_QUERY_LENGTH = 1000
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9._#@\-]{1,32}$")
DEFAULT_ALLOWED_HOSTS = "127.0.0.1,localhost"
INTERNAL_KEY_HEADER = "X-Internal-Key"
INTERNAL_KEY_ENV = "SMC_INTERNAL_KEY"

INVALID_REQUEST_MESSAGE = "Invalid request"
INTERNAL_ERROR_MESSAGE = "Internal server error"
NOTHING_LOADED_MESSAGE = "No symbol could be loaded; see the scanner log"
WATCHLIST_MESSAGE = "Watchlist is missing or invalid"

_scan_lock = threading.Lock()


# --- response models (the generated client is built from these) ---------------------


class ErrorResponse(BaseModel):
    """Body of every error response."""

    success: Literal[False] = False
    error: str


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or wrong internal key"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
    503: {"model": ErrorResponse, "description": "No symbol could be loaded"},
}


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ScanRowOut(BaseModel):
    instrument: str
    status: Status
    zone: str
    zone_low: float
    zone_high: float
    price: float
    dist_atr: float
    bias: Bias
    in_ote: bool
    trendline_ok: bool
    ob_fvg: bool
    score: int
    zone_age: int
    prior_touches: int
    bar_time: str

    @classmethod
    def from_row(cls, row: ScanRow) -> "ScanRowOut":
        return cls.model_validate(row, from_attributes=True)


class ScanFailureOut(BaseModel):
    symbol: str
    error: str


class ScanResponse(BaseModel):
    source: ApiSource
    tf: Timeframe
    count: int
    rows: list[ScanRowOut]
    failures: list[ScanFailureOut]


class ScanDefaults(BaseModel):
    source: ApiSource
    tf: Timeframe
    bars: int
    swing: int
    near: float


class ScanLimits(BaseModel):
    min_bars: int
    max_bars: int
    max_swing: int
    max_near: float
    max_symbols: int


class ConfigResponse(BaseModel):
    """What the scan form needs: choices, defaults, limits and the watchlist per source."""

    sources: list[ApiSource]
    timeframes: list[Timeframe]
    defaults: ScanDefaults
    limits: ScanLimits
    watchlist: dict[str, list[str]]


# --- app -------------------------------------------------------------------------------


def _operation_id(route: APIRoute) -> str:
    """``health``, ``config``, ``scan``: the generated SDK function names."""
    return route.name


def _allowed_hosts() -> list[str]:
    raw = os.environ.get("SMC_API_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)
    return [host.strip() for host in raw.split(",") if host.strip()]


def _error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"success": False, "error": message})


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Error"
    return _error_response(exc.status_code, message)


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    log.info("invalid request: %s", exc.errors())
    return _error_response(422, INVALID_REQUEST_MESSAGE)


async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled exception", exc_info=exc)
    return _error_response(500, INTERNAL_ERROR_MESSAGE)


def require_internal_key(
    key: Annotated[str | None, Header(alias=INTERNAL_KEY_HEADER)] = None,
) -> None:
    """Constant-time check of ``X-Internal-Key`` against ``SMC_INTERNAL_KEY``; no-op when unset."""
    configured = os.environ.get(INTERNAL_KEY_ENV, "")
    if not configured:
        return
    if not secrets.compare_digest((key or "").encode(), configured.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


InternalKeyDep = Annotated[None, Depends(require_internal_key)]

app = FastAPI(
    title="SMC scanner",
    version=__version__,
    description="Screens a watchlist for price touching or near fresh order blocks and "
    "fair value gaps. Read-only; it never places trades.",
    generate_unique_id_function=_operation_id,
    responses=ERROR_RESPONSES,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, _unhandled_handler)


@app.get("/health", response_model=HealthResponse, tags=["scanner"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


def _watchlist_symbols(source: ApiSource) -> list[str]:
    try:
        return resolve_symbols(DEFAULT_WATCHLIST, source)
    except WatchlistError as exc:
        log.error("watchlist (%s): %s", source, exc)
        return []


@app.get("/config", response_model=ConfigResponse, tags=["scanner"])
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
    )


def _symbols(source: ApiSource, raw: str | None) -> list[str]:
    if raw:
        symbols = [part.strip() for part in raw.split(",") if part.strip()]
        if len(symbols) > MAX_SYMBOLS:
            raise HTTPException(status_code=422, detail=f"At most {MAX_SYMBOLS} symbols")
        bad = [symbol for symbol in symbols if not SYMBOL_PATTERN.match(symbol)]
        if bad:
            raise HTTPException(status_code=422, detail=f"Invalid symbol name: {bad[0]!r}")
        return symbols
    try:
        return resolve_symbols(DEFAULT_WATCHLIST, source)
    except WatchlistError as exc:
        log.error("watchlist: %s", exc)
        raise HTTPException(status_code=500, detail=WATCHLIST_MESSAGE) from exc


def _to_response(source: ApiSource, tf: Timeframe, result: ScanResult) -> ScanResponse:
    return ScanResponse(
        source=source,
        tf=tf,
        count=len(result.rows),
        rows=[ScanRowOut.from_row(row) for row in result.rows],
        failures=[ScanFailureOut(symbol=f.symbol, error=f.error) for f in result.failures],
    )


@app.get("/scan", response_model=ScanResponse, tags=["scanner"])
def scan(
    _: InternalKeyDep,
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
) -> ScanResponse:
    """Scan the given symbols (or the watchlist) on one timeframe.

    503 when no symbol could be loaded at all (terminal down, bad login); otherwise the
    per-symbol failures are listed next to the rows.
    """
    options = ScanOptions(swing_length=swing, near_atr=near, all_touches=all_touches)
    wanted = _symbols(source, symbols)
    with _scan_lock:
        result = run_scan(make_loader(source), wanted, tf, bars, options)
    if result.all_failed:
        raise HTTPException(status_code=503, detail=NOTHING_LOADED_MESSAGE)
    return _to_response(source, tf, result)
