"""Dependencies the routes inject: key check, rate limits, stores and factories."""

import logging
import os
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path as FsPath
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from smc_scanner.ai.analyst import (
    AnalysisResult,
    CalendarLookup,
)
from smc_scanner.ai.budget import (
    BudgetConfigError,
    BudgetExceededError,
    BudgetGuard,
    limits_from_env,
)
from smc_scanner.ai.providers import API_KEY_ENV, AiError, AiProvider, make_provider
from smc_scanner.ai.store import (
    AnalysisStore,
    SqliteAnalysisStore,
    StoreError,
    db_path_from_env,
)
from smc_scanner.api.constants import (
    AI_PROVIDER_NAME,
    AI_UNAVAILABLE_MESSAGE,
    ANALYSE_LOCK_POLL_SECONDS,
    ANALYSE_RATE_LIMIT,
    BUDGET_CONFIG_MESSAGE,
    BUDGET_MESSAGE,
    CALENDAR_RATE_LIMIT,
    INTERNAL_KEY_ENV,
    INTERNAL_KEY_HEADER,
    JOURNAL_LIMIT_MESSAGE,
    JOURNAL_NOT_FOUND_MESSAGE,
    JOURNAL_RATE_LIMIT,
    JOURNAL_STATS_RATE_LIMIT,
    JOURNAL_STORE_MESSAGE,
    RATE_LIMIT_MESSAGE,
    RUN_UNAVAILABLE_MESSAGE,
    SCAN_RATE_LIMIT,
    SCHEDULE_LIMIT_MESSAGE,
    SCHEDULE_NOT_FOUND_MESSAGE,
    SCHEDULE_STORE_MESSAGE,
    STORE_UNAVAILABLE_MESSAGE,
    STRATEGIES_RATE_LIMIT,
)
from smc_scanner.api.strategy_deps import strategy_service_for
from smc_scanner.econ_calendar.forexfactory import ForexFactoryCalendarSource
from smc_scanner.econ_calendar.models import CalendarEvent, CalendarSource
from smc_scanner.econ_calendar.service import CalendarService
from smc_scanner.econ_calendar.store import SqliteCalendarStore, StoredCalendar
from smc_scanner.journal.store import (
    JournalLimitError,
    JournalNotFoundError,
    JournalStore,
    SqliteJournalStore,
)
from smc_scanner.notify.telegram import SendResult, send_test_message
from smc_scanner.ratelimit import RateLimiter
from smc_scanner.schedule.joblog import (
    SqliteJobLogStore,
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
    Schedule,
    ScheduleLimitError,
    ScheduleNotFoundError,
    SqliteScheduleRepository,
    previous_action,
)
from smc_scanner.schedule.timing import server_zone_from_env
from smc_scanner.strategy.service import StrategyService

log = logging.getLogger(__name__)

_scan_lock = threading.Lock()
_store_init_lock = threading.Lock()  # first-time schema setup must not race itself
_analyse_lock = (
    threading.Lock()
)  # one analysis phase at a time, so identical runs never double-call
_run_guard = RunGuard()  # shared by the scheduler and run-now: one run per schedule at a time

RATE_LIMITERS: dict[str, RateLimiter] = {
    "scan": RateLimiter(*SCAN_RATE_LIMIT),
    "analyse": RateLimiter(*ANALYSE_RATE_LIMIT),
    "journal": RateLimiter(*JOURNAL_RATE_LIMIT),
    "journal_stats": RateLimiter(*JOURNAL_STATS_RATE_LIMIT),
    "calendar": RateLimiter(*CALENDAR_RATE_LIMIT),
    "strategies": RateLimiter(*STRATEGIES_RATE_LIMIT),
}


def reset_rate_limits() -> None:
    """Empty every endpoint's window (tests)."""
    for limiter in RATE_LIMITERS.values():
        limiter.reset()


def _rate_limit(name: str) -> Callable[[], None]:
    """A dependency that takes one hit from the named limiter, looked up per request so tests
    can swap it. List it after ``InternalKeyDep``: unauthenticated calls must not use the quota."""

    def take() -> None:
        wait = RATE_LIMITERS[name].take()
        if wait is not None:
            raise HTTPException(
                status_code=429, detail=RATE_LIMIT_MESSAGE, headers={"Retry-After": str(wait)}
            )

    return take


ScanRateDep = Annotated[None, Depends(_rate_limit("scan"))]
AnalyseRateDep = Annotated[None, Depends(_rate_limit("analyse"))]
JournalRateDep = Annotated[None, Depends(_rate_limit("journal"))]
JournalStatsRateDep = Annotated[None, Depends(_rate_limit("journal_stats"))]
CalendarRateDep = Annotated[None, Depends(_rate_limit("calendar"))]
StrategiesRateDep = Annotated[None, Depends(_rate_limit("strategies"))]


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


class _NoCache:
    """Stands in when the database cannot hold the calendar cache: keeps the last week in
    memory, so the hourly refresh and the stale fallback still work."""

    def __init__(self) -> None:
        self._stored = StoredCalendar((), None)

    def load(self) -> StoredCalendar:
        return self._stored

    def replace(self, events: list[CalendarEvent], fetched_at: datetime) -> None:
        self._stored = StoredCalendar(tuple(events), fetched_at)


_calendar_source_factory: Callable[[], CalendarSource] = ForexFactoryCalendarSource  # tests swap
_calendar_services: dict[FsPath | None, CalendarService] = {}  # None: no usable database path
_calendar_lock = threading.Lock()  # not _store_init_lock: run-now holds that while building deps


def _calendar_service_for(db_path: FsPath | None) -> CalendarService:
    """The process-wide calendar service for this database: one per path, so the hourly refresh,
    the fetch lock and the failure backoff are shared by every request and scheduled run. A cache
    that cannot be opened degrades to no cache, never to an error."""
    with _calendar_lock:
        service = _calendar_services.get(db_path)
        if service is None:
            try:
                cache: SqliteCalendarStore | _NoCache = (
                    _NoCache() if db_path is None else SqliteCalendarStore(db_path)
                )
            except StoreError as exc:
                log.warning("calendar cache unavailable: %s", type(exc).__name__)
                cache = _NoCache()
            service = CalendarService(_calendar_source_factory(), cache)
            _calendar_services[db_path] = service
        return service


def get_calendar_service() -> CalendarService:
    """The calendar service on the shared database. Tests override this dependency."""
    try:
        path = db_path_from_env()
    except StoreError as exc:
        log.warning("calendar database path invalid: %s", type(exc).__name__)
        return _calendar_service_for(None)
    return _calendar_service_for(path)


CalendarServiceDep = Annotated[CalendarService, Depends(get_calendar_service)]


def _analyse_under_lock(
    stop: threading.Event, budget: BudgetGuard, calendar: CalendarLookup | None = None
) -> AnalyseFn:
    """``default_analyse`` under the lock ``/analyse`` uses, so a scheduled run and a request for
    the same hit never both call the provider. Waiting for the lock gives up once ``stop`` is set,
    so shutdown is not held up behind a slow ``/analyse``. Every analysis phase holds that lock,
    so reservations never overlap and each phase may use its own guard over the same stored
    usage."""

    def analyse(
        data: ScanData, schedule: Schedule, provider: AiProvider, store: AnalysisStore, clock: Clock
    ) -> list[AnalysisResult]:
        while not _analyse_lock.acquire(timeout=ANALYSE_LOCK_POLL_SECONDS):
            if stop.is_set():
                raise RuntimeError("stopped while waiting for the analysis lock")
        try:
            return default_analyse(data, schedule, provider, store, clock, budget, calendar)
        finally:
            _analyse_lock.release()

    return analyse


def _build_run_deps(db_path: FsPath, stop: threading.Event | None = None) -> RunDeps:
    """Everything a scheduled run needs; the scan lock is the one ``/scan`` uses. The Telegram
    token comes from the environment only and is never logged."""
    token, chat = telegram_settings_from_env()
    stop = stop or threading.Event()
    analysis_store = SqliteAnalysisStore(db_path)
    budget = BudgetGuard(
        limits_from_env(), analysis_store.usage_for_day
    )  # invalid caps: ValueError
    return RunDeps(
        repo=SqliteScheduleRepository(db_path),
        record=SqliteJobLogStore(db_path).record_run,
        guard=_run_guard,
        analysis_store=analysis_store,
        provider_factory=partial(make_provider, AI_PROVIDER_NAME),
        scan=make_scan_fn(),
        analyse=_analyse_under_lock(stop, budget, _calendar_service_for(db_path).snapshot),
        scan_lock=_scan_lock,
        previous_action=partial(previous_action, db_path),
        telegram_token=token,
        default_chat_id=chat,
        zone=server_zone_from_env(),
        stop_event=stop,
        strategies=strategy_service_for(lambda: db_path, init_lock=_store_init_lock),
    )


def _build_scheduler() -> SchedulerService:
    deps = _build_run_deps(db_path_from_env())
    return SchedulerService(
        deps.repo, partial(run_schedule, deps=deps), zone=deps.zone, stop_event=deps.stop_event
    )


def _ai_key_configured() -> bool:
    """Whether the AI provider key is set. Shared by /config and the 503 detail of /analyse."""
    return bool(os.environ.get(API_KEY_ENV, "").strip())


ProviderFactory = Callable[[], AiProvider]


def _build_provider() -> AiProvider:
    """The Claude provider, or 503 naming the missing key variable. AiError text is only
    logged: a fixed message goes to the client."""
    try:
        return make_provider(AI_PROVIDER_NAME)
    except AiError as exc:
        log.error("AI analysis unavailable: %s", exc)
        if not _ai_key_configured():
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


def _budget_guard(store: SqliteAnalysisStore) -> BudgetGuard:
    """The daily caps from the environment over the store's usage. A bad setting is a 503,
    never silently unlimited. Built per request: the analysis lock serialises the phases that
    reserve, so a shared guard would add nothing."""
    try:
        return BudgetGuard(limits_from_env(), store.usage_for_day)
    except BudgetConfigError as exc:
        log.error("AI budget configuration invalid: %s", exc)  # names the variable, not the value
        raise HTTPException(status_code=503, detail=BUDGET_CONFIG_MESSAGE) from exc


def _budget_refused(exc: BudgetExceededError) -> HTTPException:
    log.warning("AI request refused: %s", exc)
    return HTTPException(
        status_code=429,
        detail=BUDGET_MESSAGE,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


RunDepsFactory = Callable[[], RunDeps]
TelegramSender = Callable[[str, str], SendResult]  # bot token, chat id


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


def _journal_store_unavailable(exc: StoreError) -> HTTPException:
    log.error("journal store failed: %s", exc)  # the path stays in the log
    return HTTPException(status_code=503, detail=JOURNAL_STORE_MESSAGE)


@contextmanager
def _journal_store_errors() -> Iterator[None]:
    """Map the journal store's errors to the API's: not found, the cap, or a fixed 503."""
    try:
        yield
    except JournalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=JOURNAL_NOT_FOUND_MESSAGE) from exc
    except JournalLimitError as exc:
        raise HTTPException(status_code=409, detail=JOURNAL_LIMIT_MESSAGE) from exc
    except StoreError as exc:
        raise _journal_store_unavailable(exc) from exc


def get_journal_store() -> JournalStore:
    """The journal store on the shared database file. Tests override this dependency."""
    with _journal_store_errors(), _store_init_lock:
        return SqliteJournalStore(db_path_from_env())


JournalStoreDep = Annotated[JournalStore, Depends(get_journal_store)]


_strategy_services: dict[FsPath, StrategyService] = {}
_strategy_services_lock = threading.Lock()


def get_strategy_service() -> StrategyService:
    """Built-in plus stored strategies on the shared database: one service per path, so the
    schema setup runs once per process. The file is opened on the first call that needs stored
    strategies (a listing, a stored slug), so resolving a built-in never touches it. Use a service
    outside ``_store_init_lock``: its first open takes that lock. Tests override this."""
    try:
        path = db_path_from_env()
    except StoreError:  # surfaces (as a 503) only when a stored strategy is asked for
        return strategy_service_for(db_path_from_env)
    with _strategy_services_lock:
        service = _strategy_services.get(path)
        if service is None:
            service = strategy_service_for(lambda: path, init_lock=_store_init_lock)
            _strategy_services[path] = service
        return service


StrategyServiceDep = Annotated[StrategyService, Depends(get_strategy_service)]
