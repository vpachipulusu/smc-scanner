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

Run a single worker: the scan lock, run guard and cooldowns are process-local.
"""

import base64
import binascii
import logging
import math
import os
import re
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import datetime
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
from smc_scanner.notify.telegram import SendResult, send_test_message
from smc_scanner.scanner import ScanOptions, ScanResult, run_scan
from smc_scanner.schedule.joblog import (
    MAX_ERROR_CHARS as MAX_JOB_ERROR_CHARS,
)
from smc_scanner.schedule.joblog import (
    JobLogEntry,
    JobStatus,
    SqliteJobLogStore,
)
from smc_scanner.schedule.runner import (
    TOKEN_ENV as TELEGRAM_TOKEN_ENV,
)
from smc_scanner.schedule.runner import (
    AnalyseFn,
    Clock,
    RunDeps,
    RunGuard,
    ScanData,
    SchedulerService,
    default_analyse,
    make_scan_fn,
    run_schedule,
    telegram_settings_from_env,
)
from smc_scanner.schedule.store import (
    MAX_CONFIDENCE,
    MAX_NAME_CHARS,
    Schedule,
    ScheduleLimitError,
    ScheduleNotFoundError,
    SqliteScheduleRepository,
    previous_action,
)
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

SCHEDULE_NOT_FOUND_MESSAGE = "Schedule not found"
SCHEDULE_LIMIT_MESSAGE = "Schedule limit reached"
SCHEDULE_STORE_MESSAGE = "Schedule database unavailable"
ALREADY_RUNNING_MESSAGE = "This schedule is already running"
SCAN_IN_PROGRESS_MESSAGE = "A scan is already in progress"
STOPPING_MESSAGE = "The scheduler is shutting down"
TELEGRAM_FAILED_MESSAGE = "Telegram rejected the test message"
RUN_UNAVAILABLE_MESSAGE = "Run setup is invalid; see the server log"
TELEGRAM_COOLDOWN_MESSAGE = "A test message was sent a moment ago; try again shortly"
TELEGRAM_TEST_COOLDOWN_SECONDS = 5.0
RUN_NOW_COOLDOWN_SECONDS = 10.0
RUN_COOLDOWN_MESSAGE = "This schedule was run a moment ago; try again shortly"
_OMITTED: Any = None  # default of PATCH fields that are omittable but not nullable
DEFAULT_SCHEDULE_MIN_SCORE = 2
DEFAULT_LOGS_LIMIT = 50
MAX_LOGS_LIMIT = 100  # one below the job log's own cap, because one extra row detects "more"
RUN_NOW_LOCK_TIMEOUT_SECONDS = 0.0  # run-now answers 409 at once instead of queueing behind a scan
CHAT_ID_REGEX = r"^(?:-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$"

_scan_lock = threading.Lock()
_store_init_lock = threading.Lock()  # first-time schema setup must not race itself
_analyse_lock = (
    threading.Lock()
)  # one analysis phase at a time, so identical runs never double-call
_run_guard = RunGuard()  # shared by the scheduler and run-now: one run per schedule at a time


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


def _error_response(
    status_code: int, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
        headers=None if headers is None else dict(headers),
    )


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Error"
    return _error_response(exc.status_code, message, exc.headers)


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
        record=SqliteJobLogStore(db_path).record_run,
        guard=_run_guard,
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


# --- schedules --------------------------------------------------------------------------

ScheduleId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]
Frequency = Literal["15m", "1h", "4h", "1d"]  # kept equal to timing.FREQUENCIES by a test
SymbolName = Annotated[str, Field(pattern=SYMBOL_PATTERN.pattern)]
ChatId = Annotated[str, Field(pattern=CHAT_ID_REGEX)]
Symbols = Annotated[list[SymbolName], Field(min_length=1, max_length=MAX_SYMBOLS)]
SCHEDULE_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No schedule with that id"},
    503: {"model": ErrorResponse, "description": "Schedule database unavailable"},
}
STORE_ERROR_ONLY: dict[int | str, dict[str, Any]] = {503: SCHEDULE_ERRORS[503]}


class ScheduleCreate(BaseModel):
    """A new schedule. Every field but the first five has a default."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    source: ApiSource
    tf: Timeframe
    symbols: Symbols
    frequency: Frequency
    min_score: int = Field(default=DEFAULT_SCHEDULE_MIN_SCORE, ge=0, le=MAX_AI_MIN_SCORE)
    min_confidence: float = Field(default=0.0, ge=0, le=MAX_CONFIDENCE)
    only_on_change: bool = False
    send_hold: bool = False
    enabled: bool = True
    telegram_chat_id: ChatId | None = None


class ScheduleUpdate(BaseModel):
    """Any subset of the editable fields. Only ``telegram_chat_id`` may be null (it clears it)."""

    model_config = ConfigDict(extra="forbid")

    # Omittable but not nullable (the schema says so); an absent field is simply not in
    # ``model_fields_set``, so the ``_OMITTED`` default is never read.
    name: str = Field(default=_OMITTED, min_length=1, max_length=MAX_NAME_CHARS)
    source: ApiSource = _OMITTED
    tf: Timeframe = _OMITTED
    symbols: Symbols = _OMITTED
    frequency: Frequency = _OMITTED
    min_score: int = Field(default=_OMITTED, ge=0, le=MAX_AI_MIN_SCORE)
    min_confidence: float = Field(default=_OMITTED, ge=0, le=MAX_CONFIDENCE)
    only_on_change: bool = _OMITTED
    send_hold: bool = _OMITTED
    enabled: bool = _OMITTED
    telegram_chat_id: ChatId | None = None


class ScheduleOut(BaseModel):
    id: int
    name: str
    source: ApiSource
    tf: Timeframe
    symbols: list[str]
    frequency: Frequency
    min_score: int
    min_confidence: float
    only_on_change: bool
    send_hold: bool
    enabled: bool
    telegram_chat_id: str | None
    last_run_at: str | None = Field(max_length=MAX_LABEL_CHARS)
    next_run_at: str | None = Field(max_length=MAX_LABEL_CHARS)

    @classmethod
    def from_schedule(cls, schedule: Schedule) -> "ScheduleOut":
        return cls.model_validate(
            {
                **schedule.__dict__,
                "id": schedule.id or 0,
                "symbols": list(schedule.symbols),
                "last_run_at": _iso_or_none(schedule.last_run_at),
                "next_run_at": _iso_or_none(schedule.next_run_at),
            }
        )


class ScheduleList(BaseModel):
    items: list[ScheduleOut]


class DeleteResponse(BaseModel):
    deleted: Literal[True] = True


class RunOut(BaseModel):
    """What a run-now did. Error text is never returned here; see the job log."""

    status: Literal["ok", "failed"]
    rows: int
    delivered: int
    skipped: int
    error_count: int


class JobLogOut(BaseModel):
    """One job-log row. ``error`` is raw text (already redacted and bounded): render it as
    text, never as markup."""

    id: int
    schedule_id: int
    started_at: str = Field(max_length=MAX_LABEL_CHARS)
    finished_at: str = Field(max_length=MAX_LABEL_CHARS)
    duration_ms: int
    status: JobStatus
    hits: int
    delivered: int
    skipped: int
    skip_reason: str | None = Field(max_length=MAX_LABEL_CHARS)
    error: str | None = Field(max_length=MAX_JOB_ERROR_CHARS)

    @classmethod
    def from_entry(cls, entry: JobLogEntry) -> "JobLogOut":
        return cls(
            id=entry.id or 0,
            schedule_id=entry.schedule_id,
            started_at=entry.started_at.isoformat(),
            finished_at=entry.finished_at.isoformat(),
            duration_ms=entry.duration_ms,
            status=entry.status,
            hits=entry.hits,
            delivered=entry.delivered,
            skipped=entry.skipped,
            skip_reason=None if entry.skip_reason is None else _clip(entry.skip_reason),
            error=None if entry.error is None else _clip(entry.error, MAX_JOB_ERROR_CHARS),
        )


class JobLogPage(BaseModel):
    items: list[JobLogOut]
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)


class TelegramTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: ChatId | None = Field(default=None, description="default: TELEGRAM_CHAT_ID")


class TelegramTestResponse(BaseModel):
    sent: Literal[True] = True


RunDepsFactory = Callable[[], RunDeps]
TelegramSender = Callable[[str, str], SendResult]  # bot token, chat id

_schedule_update_lock = threading.Lock()
_telegram_test_lock = threading.Lock()
_telegram_test_at = -TELEGRAM_TEST_COOLDOWN_SECONDS  # monotonic time of the last test message


_run_now_lock = threading.Lock()
_run_now_at: dict[int, float] = {}  # schedule id -> monotonic time of its last run-now


def _take_run_now_slot(schedule_id: int) -> None:
    """429 with ``Retry-After`` when this schedule was run less than the cooldown ago."""
    with _run_now_lock:
        now = time.monotonic()
        for sid in [s for s, at in _run_now_at.items() if now - at >= RUN_NOW_COOLDOWN_SECONDS]:
            del _run_now_at[sid]  # expired entries, so the map stays small
        last = _run_now_at.get(schedule_id)
        if last is not None:
            wait = max(1, math.ceil(RUN_NOW_COOLDOWN_SECONDS - (now - last)))
            raise HTTPException(
                status_code=429, detail=RUN_COOLDOWN_MESSAGE, headers={"Retry-After": str(wait)}
            )
        _run_now_at[schedule_id] = now


def _take_telegram_test_slot() -> None:
    """429 when a test message went out less than the cooldown ago, so a loop cannot burn the
    bot's rate budget that real alerts share."""
    global _telegram_test_at
    with _telegram_test_lock:
        now = time.monotonic()
        if now - _telegram_test_at < TELEGRAM_TEST_COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail=TELEGRAM_COOLDOWN_MESSAGE)
        _telegram_test_at = now


def _iso_or_none(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _request_run_deps() -> RunDeps:
    """Fresh run dependencies for run-now: the shared scan lock and guard, the job log recorder."""
    try:
        with _store_init_lock:  # first-time schema setup of three stores must not race
            return _build_run_deps(db_path_from_env())
    except StoreError as exc:
        raise _schedule_store_unavailable(exc) from exc
    except ValueError as exc:  # e.g. a bad SMC_SERVER_TZ
        log.error("run-now configuration invalid: %s", exc)
        raise HTTPException(status_code=503, detail=RUN_UNAVAILABLE_MESSAGE) from exc


def get_run_deps_factory() -> RunDepsFactory:
    """A factory, so a missing schedule is a 404 before anything is built. Tests override it."""
    return _request_run_deps


def _send_telegram_test(token: str, chat_id: str) -> SendResult:
    return send_test_message(token, chat_id)


def get_telegram_sender() -> TelegramSender:
    """Tests override this so nothing leaves the machine."""
    return _send_telegram_test


RunDepsFactoryDep = Annotated[RunDepsFactory, Depends(get_run_deps_factory)]
TelegramSenderDep = Annotated[TelegramSender, Depends(get_telegram_sender)]


def _schedule_store_unavailable(exc: StoreError) -> HTTPException:
    log.error("schedule store failed: %s", exc)  # the path stays in the log
    return HTTPException(status_code=503, detail=SCHEDULE_STORE_MESSAGE)


@contextmanager
def _schedule_store_errors() -> Iterator[None]:
    """Map the stores' errors to the API's: not found, the cap, or a fixed 503."""
    try:
        yield
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=SCHEDULE_NOT_FOUND_MESSAGE) from exc
    except ScheduleLimitError as exc:
        raise HTTPException(status_code=409, detail=SCHEDULE_LIMIT_MESSAGE) from exc
    except StoreError as exc:
        raise _schedule_store_unavailable(exc) from exc


def _open_schedules() -> SqliteScheduleRepository:
    with _schedule_store_errors(), _store_init_lock:
        return SqliteScheduleRepository(db_path_from_env())


def _open_job_log() -> SqliteJobLogStore:
    with _schedule_store_errors(), _store_init_lock:
        return SqliteJobLogStore(db_path_from_env())


def _existing(repo: SqliteScheduleRepository, schedule_id: int) -> Schedule:
    with _schedule_store_errors():
        schedule = repo.get(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail=SCHEDULE_NOT_FOUND_MESSAGE)
    return schedule


def _invalid(exc: ValueError) -> HTTPException:
    log.info("invalid schedule: %s", exc)
    return HTTPException(status_code=422, detail=INVALID_REQUEST_MESSAGE)


@app.get("/schedules", response_model=ScheduleList, tags=["schedules"], responses=STORE_ERROR_ONLY)
def list_schedules(_: InternalKeyDep) -> ScheduleList:
    repo = _open_schedules()
    with _schedule_store_errors():
        found = repo.list_schedules()
    return ScheduleList(items=[ScheduleOut.from_schedule(s) for s in found])


@app.post(
    "/schedules",
    response_model=ScheduleOut,
    status_code=201,
    tags=["schedules"],
    responses={
        409: {"model": ErrorResponse, "description": "The schedule limit is reached"},
        **STORE_ERROR_ONLY,
    },
)
def create_schedule(body: ScheduleCreate, _: InternalKeyDep) -> ScheduleOut:
    try:
        schedule = Schedule(**{**body.model_dump(), "symbols": tuple(body.symbols)})
    except ValueError as exc:  # e.g. a blank name the field limits cannot see
        raise _invalid(exc) from exc
    repo = _open_schedules()
    with _schedule_store_errors():
        return ScheduleOut.from_schedule(repo.add(schedule))


@app.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleOut,
    tags=["schedules"],
    responses=SCHEDULE_ERRORS,
)
def get_schedule(schedule_id: ScheduleId, _: InternalKeyDep) -> ScheduleOut:
    return ScheduleOut.from_schedule(_existing(_open_schedules(), schedule_id))


@app.patch(
    "/schedules/{schedule_id}",
    response_model=ScheduleOut,
    tags=["schedules"],
    responses=SCHEDULE_ERRORS,
)
def update_schedule(
    schedule_id: ScheduleId, body: ScheduleUpdate, _: InternalKeyDep
) -> ScheduleOut:
    """Change some fields. Changing the frequency or the enabled flag picks a fresh next slot."""
    repo = _open_schedules()
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    if "symbols" in changes:
        changes["symbols"] = tuple(changes["symbols"])
    with _schedule_update_lock:  # read-merge-write must not interleave with another PATCH
        current = _existing(repo, schedule_id)
        try:
            merged = replace(current, **changes)  # re-runs the Schedule validation
        except ValueError as exc:
            raise _invalid(exc) from exc
        with _schedule_store_errors():
            return ScheduleOut.from_schedule(repo.update(merged))


@app.delete(
    "/schedules/{schedule_id}",
    response_model=DeleteResponse,
    tags=["schedules"],
    responses=SCHEDULE_ERRORS,
)
def delete_schedule(schedule_id: ScheduleId, _: InternalKeyDep) -> DeleteResponse:
    """Delete a schedule, its sent-alert marks and its job log."""
    repo = _open_schedules()
    with _schedule_store_errors():
        deleted = repo.delete(schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=SCHEDULE_NOT_FOUND_MESSAGE)
    try:
        _open_job_log().prune_schedule(schedule_id)
    except (HTTPException, StoreError) as exc:  # the next job-log open sweeps orphans anyway
        log.warning("job log of deleted schedule %s not pruned: %s", schedule_id, exc)
    return DeleteResponse()


@app.post(
    "/schedules/{schedule_id}/run",
    response_model=RunOut,
    tags=["schedules"],
    responses={
        **SCHEDULE_ERRORS,
        409: {"model": ErrorResponse, "description": "This schedule or a scan is already running"},
        429: {
            "model": ErrorResponse,
            "description": "This schedule was run a moment ago; see the Retry-After header",
            "headers": {
                "Retry-After": {
                    "description": "Seconds until this schedule may be run again",
                    "schema": {"type": "integer"},
                }
            },
        },
        503: {"model": ErrorResponse, "description": "Schedule database or run setup unavailable"},
    },
)
def run_schedule_now(
    schedule_id: ScheduleId, _: InternalKeyDep, make_deps: RunDepsFactoryDep
) -> RunOut:
    """Run the schedule once now, waiting for the result.

    Takes the same scan lock as ``/scan`` and never queues behind it: 409 when this schedule is
    already running or a scan holds the lock. A schedule can be run again only after a cooldown
    (429 with ``Retry-After``).

    A run that fails (scan or AI error) still answers 200 with ``status`` "failed": the client
    must check ``status``, not just the HTTP code. The error text is in the job log only.
    """
    schedule = _existing(_open_schedules(), schedule_id)
    _take_run_now_slot(schedule_id)
    deps = replace(make_deps(), lock_timeout=RUN_NOW_LOCK_TIMEOUT_SECONDS)
    report = run_schedule(schedule, deps)
    if report.status == "already_running":
        raise HTTPException(status_code=409, detail=ALREADY_RUNNING_MESSAGE)
    if report.status == "busy":
        raise HTTPException(status_code=409, detail=SCAN_IN_PROGRESS_MESSAGE)
    if report.status == "stopped":
        raise HTTPException(status_code=503, detail=STOPPING_MESSAGE)
    return RunOut(
        status=report.status,
        rows=report.rows,
        delivered=report.delivered,
        skipped=len(report.skipped),
        error_count=len(report.errors),
    )


@app.get(
    "/schedules/{schedule_id}/logs",
    response_model=JobLogPage,
    tags=["schedules"],
    responses=SCHEDULE_ERRORS,
)
def list_schedule_logs(
    schedule_id: ScheduleId,
    _: InternalKeyDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LOGS_LIMIT)] = DEFAULT_LOGS_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_CHARS)] = None,
) -> JobLogPage:
    """Job-log rows of one schedule, newest first. Pass ``next_cursor`` back for the next page."""
    before_id = None if cursor is None else _decode_cursor(cursor)
    _existing(_open_schedules(), schedule_id)
    logs = _open_job_log()
    with _schedule_store_errors():
        entries = logs.list_entries(schedule_id=schedule_id, limit=limit + 1, before_id=before_id)
    page = entries[:limit]
    more = len(entries) > limit and page[-1].id is not None
    return JobLogPage(
        items=[JobLogOut.from_entry(entry) for entry in page],
        next_cursor=_encode_cursor(page[-1].id or 0) if more else None,
    )


@app.post(
    "/telegram/test",
    response_model=TelegramTestResponse,
    tags=["telegram"],
    responses={
        422: {"model": ErrorResponse, "description": "Invalid chat id, or none to send to"},
        502: {"model": ErrorResponse, "description": "Telegram did not accept the message"},
        503: {"model": ErrorResponse, "description": "TELEGRAM_BOT_TOKEN is not set"},
        429: {"model": ErrorResponse, "description": "Another test message was sent just now"},
    },
)
def send_telegram_test(
    _: InternalKeyDep, send: TelegramSenderDep, body: TelegramTestRequest | None = None
) -> TelegramTestResponse:
    """Send a fixed test message to ``chat_id`` (default ``TELEGRAM_CHAT_ID``). The token is read
    from the environment only and never appears in a response or a log."""
    token, default_chat = telegram_settings_from_env()
    if not token:
        raise HTTPException(
            status_code=503, detail=f"Telegram is disabled: {TELEGRAM_TOKEN_ENV} is not set"
        )
    chat = (body.chat_id if body else None) or default_chat
    if not chat:
        raise HTTPException(status_code=422, detail="No chat id: pass chat_id or set the default")
    _take_telegram_test_slot()
    try:
        result = send(token, chat)
    except Exception as exc:  # the notifier never raises; a fake or a bug must not leak the token
        log.error("telegram test failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail=TELEGRAM_FAILED_MESSAGE) from None
    if not result.ok:
        raise HTTPException(status_code=502, detail=TELEGRAM_FAILED_MESSAGE)
    return TelegramTestResponse()
