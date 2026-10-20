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

import base64
import binascii
import logging
import os
import re
import secrets
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path as FsPath
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from smc_scanner import __version__
from smc_scanner.ai.analyst import (
    DEFAULT_MAX_ROWS,
    DEFAULT_MIN_SCORE,
    AnalysisResult,
    analyse_hits,
    hit_inputs_from_ohlc,
)
from smc_scanner.ai.analyst import Status as AiStatus
from smc_scanner.ai.providers import API_KEY_ENV, AiError, AiProvider, make_provider
from smc_scanner.ai.store import (
    AnalysisRecord,
    AnalysisStore,
    SqliteAnalysisStore,
    StoreError,
    db_path_from_env,
)
from smc_scanner.ai.verdict import CONFIDENCE_MAX, CONFIDENCE_MIN, Action, AiVerdict
from smc_scanner.ai_cli import MAX_NOTE_CHARS, SKIP_NOTES, FrameCache
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
from smc_scanner.schedule.runner import (
    AnalyseFn,
    Clock,
    RunDeps,
    ScanData,
    SchedulerService,
    default_analyse,
    make_scan_fn,
    run_schedule,
    telegram_settings_from_env,
)
from smc_scanner.schedule.store import Schedule, SqliteScheduleRepository, previous_action
from smc_scanner.schedule.timing import server_zone_from_env
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
SCHEDULER_ENV = "SMC_SCHEDULER"
SCHEDULER_TRUTHY = frozenset({"1", "true", "yes", "on"})
SCHEDULER_FALSY = frozenset({"0", "false", "no", "off"})
ANALYSE_LOCK_POLL_SECONDS = 1.0

INVALID_REQUEST_MESSAGE = "Invalid request"
INTERNAL_ERROR_MESSAGE = "Internal server error"
NOTHING_LOADED_MESSAGE = "No symbol could be loaded; see the scanner log"
WATCHLIST_MESSAGE = "Watchlist is missing or invalid"
STORE_UNAVAILABLE_MESSAGE = "Analysis database unavailable"
AI_FAILED_MESSAGE = "AI provider failed"
NOT_FOUND_MESSAGE = "Analysis not found"
INVALID_CURSOR_MESSAGE = "Invalid cursor"

AI_PROVIDER_NAME = "claude"  # the only provider the API offers; the fake one is CLI/demo-only
MAX_AI_MIN_SCORE = 4
MAX_AI_ROWS = 20
DEFAULT_ANALYSES_LIMIT = 50
MAX_ANALYSES_LIMIT = 200
MAX_CURSOR_CHARS = 64
MAX_LABEL_CHARS = 100
MAX_ROW_ID = 2**63 - 1  # SQLite INTEGER; larger ids would overflow the driver
AI_UNAVAILABLE_MESSAGE = "AI analysis is unavailable; see the server log"
CURSOR_PREFIX = "id:"

_scan_lock = threading.Lock()
_store_init_lock = threading.Lock()  # first-time schema setup must not race itself
_analyse_lock = (
    threading.Lock()
)  # one analysis phase at a time, so identical runs never double-call


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
    bar_time: str = Field(max_length=MAX_LABEL_CHARS)

    @classmethod
    def from_row(cls, row: ScanRow) -> "ScanRowOut":
        return cls.model_validate(row, from_attributes=True)


class ScanFailureOut(BaseModel):
    symbol: str = Field(max_length=MAX_LABEL_CHARS)
    error: str


class ScanResponse(BaseModel):
    source: ApiSource
    tf: Timeframe
    count: int
    rows: list[ScanRowOut]
    failures: list[ScanFailureOut]


class AiResultOut(BaseModel):
    """What the analyst did with one row: its status, the verdict if there is one, a short note."""

    status: AiStatus
    verdict: AiVerdict | None
    note: str = Field(max_length=MAX_NOTE_CHARS)


class AnalysedRowOut(ScanRowOut):
    """A scan row plus its AI result. A subclass rather than a nullable field on ``ScanRowOut``,
    which ``/scan`` also returns and where it would always be null."""

    ai: AiResultOut


class AnalyseRequest(BaseModel):
    """The ``/scan`` parameters as a JSON body, plus the analyst's knobs."""

    model_config = ConfigDict(extra="forbid")

    source: ApiSource = "mt5"
    tf: Timeframe = DEFAULT_TIMEFRAME
    symbols: (
        Annotated[
            list[Annotated[str, Field(max_length=32)]], Field(min_length=1, max_length=MAX_SYMBOLS)
        ]
        | None
    ) = None
    bars: int = Field(default=DEFAULT_BARS, ge=MIN_BARS, le=MAX_BARS)
    swing: int = Field(default=DEFAULT_SWING_LENGTH, ge=1, le=MAX_SWING_LENGTH)
    near: float = Field(default=DEFAULT_NEAR_ATR, ge=0, le=MAX_NEAR_ATR)
    all_touches: bool = False
    provider: Literal["claude"] | None = None
    min_score: int = Field(default=DEFAULT_MIN_SCORE, ge=0, le=MAX_AI_MIN_SCORE)
    max_rows: int = Field(default=DEFAULT_MAX_ROWS, ge=1, le=MAX_AI_ROWS)


class AnalyseResponse(BaseModel):
    source: ApiSource
    tf: Timeframe
    count: int
    rows: list[AnalysedRowOut]
    failures: list[ScanFailureOut]


class AnalysisOut(BaseModel):
    """One stored analysis. The context, token counts and error text stay in the database."""

    id: int
    created_at: str = Field(max_length=MAX_LABEL_CHARS)
    symbol: str
    tf: str = Field(max_length=MAX_LABEL_CHARS)
    zone_kind: str = Field(max_length=MAX_LABEL_CHARS)
    zone: str = Field(max_length=MAX_LABEL_CHARS)
    zone_low: float
    zone_high: float
    bar_time: str
    provider: str = Field(max_length=MAX_LABEL_CHARS)
    model: str = Field(max_length=MAX_LABEL_CHARS)
    prompt_version: str = Field(max_length=MAX_LABEL_CHARS)
    attempts: int
    status: Literal["ok", "failed"]
    verdict: AiVerdict | None


class AnalysisPage(BaseModel):
    items: list[AnalysisOut]
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)


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


def _scheduler_enabled() -> bool:
    value = os.environ.get(SCHEDULER_ENV, "").strip().lower()
    if value and value not in SCHEDULER_TRUTHY and value not in SCHEDULER_FALSY:
        log.warning("%s has an unrecognised value, the scheduler stays off", SCHEDULER_ENV)
    return value in SCHEDULER_TRUTHY


def _analyse_under_lock(stop: threading.Event) -> AnalyseFn:
    """``default_analyse`` under the lock ``/analyse`` uses, so a scheduled run and a request for
    the same hit never both call the provider. Waiting for the lock gives up once ``stop`` is set,
    so shutdown is not held up behind a slow ``/analyse``."""

    def analyse(
        data: ScanData, schedule: Schedule, provider: AiProvider, store: AnalysisStore, clock: Clock
    ) -> list[AnalysisResult]:
        while not _analyse_lock.acquire(timeout=ANALYSE_LOCK_POLL_SECONDS):
            if stop.is_set():
                raise RuntimeError("stopped while waiting for the analysis lock")
        try:
            return default_analyse(data, schedule, provider, store, clock)
        finally:
            _analyse_lock.release()

    return analyse


def _build_run_deps(db_path: FsPath, stop: threading.Event | None = None) -> RunDeps:
    """Everything a scheduled run needs; the scan lock is the one ``/scan`` uses. The Telegram
    token comes from the environment only and is never logged."""
    token, chat = telegram_settings_from_env()
    stop = stop or threading.Event()
    return RunDeps(
        repo=SqliteScheduleRepository(db_path),
        analysis_store=SqliteAnalysisStore(db_path),
        provider_factory=partial(make_provider, AI_PROVIDER_NAME),
        scan=make_scan_fn(),
        analyse=_analyse_under_lock(stop),
        scan_lock=_scan_lock,
        previous_action=partial(previous_action, db_path),
        telegram_token=token,
        default_chat_id=chat,
        zone=server_zone_from_env(),
        stop_event=stop,
    )


def _build_scheduler() -> SchedulerService:
    deps = _build_run_deps(db_path_from_env())
    return SchedulerService(
        deps.repo, partial(run_schedule, deps=deps), zone=deps.zone, stop_event=deps.stop_event
    )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the scheduler for the life of the app when ``SMC_SCHEDULER`` is on (off by default).
    A fresh service is built per startup, so start-stop-start works."""
    if not _scheduler_enabled():
        yield
        return
    if os.environ.get("WEB_CONCURRENCY", "1").strip() not in {"", "1"}:
        log.warning("%s with several workers: every worker would scan and alert", SCHEDULER_ENV)
    service = _build_scheduler()  # misconfiguration fails startup loudly: the user opted in
    try:
        service.start()
        yield
    finally:
        service.stop()


app = FastAPI(
    lifespan=_lifespan,
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


# --- analyses ---------------------------------------------------------------------------


ProviderFactory = Callable[[], AiProvider]


def _build_provider() -> AiProvider:
    """The Claude provider, or 503 naming the missing key variable. AiError text is only
    logged: a fixed message goes to the client."""
    try:
        return make_provider(AI_PROVIDER_NAME)
    except AiError as exc:
        log.error("AI analysis unavailable: %s", exc)
        if not os.environ.get(API_KEY_ENV, "").strip():
            detail = f"AI analysis is disabled: {API_KEY_ENV} is not set"
        else:
            detail = AI_UNAVAILABLE_MESSAGE
        raise HTTPException(status_code=503, detail=detail) from exc


def get_provider_factory() -> ProviderFactory:
    """A factory rather than a provider, so the body is validated (422) before the key is
    checked (503). Tests override this dependency."""
    return _build_provider


ProviderFactoryDep = Annotated[ProviderFactory, Depends(get_provider_factory)]


def _open_store(*, read_only: bool) -> SqliteAnalysisStore:
    try:
        path = db_path_from_env()
        if read_only:
            return SqliteAnalysisStore.open_read_only(path)
        with _store_init_lock:
            return SqliteAnalysisStore(path)
    except StoreError as exc:
        log.error("analysis store unavailable: %s", exc)  # the path stays in the log
        raise HTTPException(status_code=503, detail=STORE_UNAVAILABLE_MESSAGE) from exc


def _store_unavailable(exc: StoreError) -> HTTPException:
    log.error("analysis store failed: %s", exc)
    return HTTPException(status_code=503, detail=STORE_UNAVAILABLE_MESSAGE)


def _note(result: AnalysisResult) -> str:
    verdict = result.verdict
    if result.status == "failed":
        return "analysis failed, see the server log"
    if verdict is not None and verdict.downgraded:
        return (verdict.downgrade_reason or "")[:MAX_NOTE_CHARS]
    if result.status == "analysed" and result.error:
        return "not saved, it will be retried"
    return SKIP_NOTES.get(result.status, "")


def _analysed_row(result: AnalysisResult) -> AnalysedRowOut:
    ai = AiResultOut(status=result.status, verdict=result.verdict, note=_note(result))
    return AnalysedRowOut(**ScanRowOut.from_row(result.row).model_dump(), ai=ai)


def _provider_failed_everywhere(results: list[AnalysisResult]) -> bool:
    """Something failed and nothing worked: no verdict made or reused."""
    if not any(result.status == "failed" for result in results):
        return False
    return not any(result.status in {"analysed", "skipped_duplicate"} for result in results)


@app.post(
    "/analyse",
    response_model=AnalyseResponse,
    tags=["analyses"],
    responses={
        502: {"model": ErrorResponse, "description": "The AI provider failed for the whole run"},
        503: {"model": ErrorResponse, "description": "Nothing loaded, AI disabled or no database"},
    },
)
def analyse(
    body: AnalyseRequest, _: InternalKeyDep, make_ai_provider: ProviderFactoryDep
) -> AnalyseResponse:
    """Scan, then ask the AI about the best hits; every row comes back with its AI result.

    The scan runs under the scan lock, which is released before any provider call. The
    analysis phase is serialised by its own lock, so concurrent identical runs queue and the
    second one finds the first one's verdicts instead of calling the provider again.
    """
    provider = make_ai_provider()
    store = _open_store(read_only=False)
    options = ScanOptions(swing_length=body.swing, near_atr=body.near, all_touches=body.all_touches)
    wanted = _symbols(body.source, ",".join(body.symbols) if body.symbols else None)
    with _scan_lock:
        frames = FrameCache(make_loader(body.source))
        result = run_scan(frames, wanted, body.tf, body.bars, options)
    if result.all_failed:
        raise HTTPException(status_code=503, detail=NOTHING_LOADED_MESSAGE)
    try:
        with _analyse_lock:
            results = analyse_hits(
                result.rows,
                lambda row: hit_inputs_from_ohlc(frames.frames[row.instrument], row, options),
                provider,
                store,
                timeframe=body.tf,
                min_score=body.min_score,
                max_rows=body.max_rows,
            )
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    if _provider_failed_everywhere(results):
        raise HTTPException(status_code=502, detail=AI_FAILED_MESSAGE)
    return AnalyseResponse(
        source=body.source,
        tf=body.tf,
        count=len(results),
        rows=[_analysed_row(r) for r in results],
        failures=[ScanFailureOut(symbol=f.symbol, error=f.error) for f in result.failures],
    )


def _clip(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    return text[:limit]


def _stored_verdict(record: AnalysisRecord) -> AiVerdict | None:
    if record.verdict is None:
        return None
    try:
        return AiVerdict.model_validate(record.verdict)
    except ValueError:
        log.warning("stored verdict %s does not validate", record.id)
        return None


def _analysis_out(record: AnalysisRecord) -> AnalysisOut:
    verdict = _stored_verdict(record)
    key = record.key
    label = record.zone.get("label")
    return AnalysisOut(
        id=record.id or 0,
        created_at=record.created_at,
        symbol=key.symbol,
        tf=key.tf,
        zone_kind=key.zone_kind,
        zone=_clip(label if isinstance(label, str) else key.zone_kind),
        zone_low=key.zone_low,
        zone_high=key.zone_high,
        bar_time=key.bar_time,
        provider=_clip(record.provider),
        model=_clip(record.model),
        prompt_version=_clip(record.prompt_version),
        attempts=record.attempts,
        status="ok" if verdict is not None and record.error is None else "failed",
        verdict=verdict,
    )


def _encode_cursor(record_id: int) -> str:
    return base64.urlsafe_b64encode(f"{CURSOR_PREFIX}{record_id}".encode()).decode()


def _decode_cursor(cursor: str) -> int:
    """The id behind an opaque cursor; anything else is a 422."""
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE) from exc
    number = text.removeprefix(CURSOR_PREFIX)
    if not text.startswith(CURSOR_PREFIX) or not number.isascii() or not number.isdigit():
        raise HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE)
    value = int(number)
    if value > MAX_ROW_ID:
        raise HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE)
    return value


@app.get("/analyses", response_model=AnalysisPage, tags=["analyses"])
def list_analyses(
    _: InternalKeyDep,
    symbol: Annotated[str | None, Query(pattern=SYMBOL_PATTERN.pattern)] = None,
    action: Action | None = None,
    min_confidence: Annotated[float | None, Query(ge=CONFIDENCE_MIN, le=CONFIDENCE_MAX)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ANALYSES_LIMIT)] = DEFAULT_ANALYSES_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_CHARS)] = None,
) -> AnalysisPage:
    """Stored analyses, newest first. Pass ``next_cursor`` back to get the following page."""
    before_id = None if cursor is None else _decode_cursor(cursor)
    store = _open_store(read_only=True)
    try:
        records = store.list_filtered(
            symbol=symbol,
            action=action,
            min_confidence=min_confidence,
            before_id=before_id,
            limit=limit + 1,
        )
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    page = records[:limit]
    more = len(records) > limit and page[-1].id is not None
    return AnalysisPage(
        items=[_analysis_out(record) for record in page],
        next_cursor=_encode_cursor(page[-1].id or 0) if more else None,
    )


@app.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisOut,
    tags=["analyses"],
    responses={404: {"model": ErrorResponse, "description": "No analysis with that id"}},
)
def get_analysis(
    analysis_id: Annotated[int, Path(ge=1, le=MAX_ROW_ID)], _: InternalKeyDep
) -> AnalysisOut:
    store = _open_store(read_only=True)
    try:
        record = store.get_by_id(analysis_id)
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MESSAGE)
    return _analysis_out(record)
