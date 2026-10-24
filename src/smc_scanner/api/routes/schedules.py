"""Schedule CRUD, job logs, run-now and the Telegram test."""

import logging
import math
import threading
import time
from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from smc_scanner.ai.store import (
    StoreError,
)
from smc_scanner.api.constants import (
    ALREADY_RUNNING_MESSAGE,
    DEFAULT_LOGS_LIMIT,
    INVALID_REQUEST_MESSAGE,
    MAX_CURSOR_CHARS,
    MAX_LOGS_LIMIT,
    RUN_COOLDOWN_MESSAGE,
    RUN_NOW_COOLDOWN_SECONDS,
    RUN_NOW_LOCK_TIMEOUT_SECONDS,
    SCAN_IN_PROGRESS_MESSAGE,
    SCHEDULE_NOT_FOUND_MESSAGE,
    STOPPING_MESSAGE,
    TELEGRAM_COOLDOWN_MESSAGE,
    TELEGRAM_FAILED_MESSAGE,
    TELEGRAM_TEST_COOLDOWN_SECONDS,
)
from smc_scanner.api.deps import (
    InternalKeyDep,
    RunDepsFactoryDep,
    StrategyServiceDep,
    TelegramSenderDep,
    _existing,
    _open_job_log,
    _open_schedules,
    _schedule_store_errors,
)
from smc_scanner.api.helpers import _decode_cursor, _encode_cursor
from smc_scanner.api.schedule_schemas import (
    DeleteResponse,
    JobLogOut,
    JobLogPage,
    RunOut,
    ScheduleCreate,
    ScheduleId,
    ScheduleList,
    ScheduleOut,
    ScheduleUpdate,
    TelegramTestRequest,
    TelegramTestResponse,
)
from smc_scanner.api.schemas import ErrorResponse
from smc_scanner.api.strategy_deps import resolve_strategy
from smc_scanner.schedule.runner import (
    TOKEN_ENV as TELEGRAM_TOKEN_ENV,
)
from smc_scanner.schedule.runner import (
    run_schedule,
    telegram_settings_from_env,
)
from smc_scanner.schedule.store import (
    Schedule,
)

log = logging.getLogger(__name__)
router = APIRouter()

SCHEDULE_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No schedule with that id"},
    503: {"model": ErrorResponse, "description": "Schedule database unavailable"},
}
STORE_ERROR_ONLY: dict[int | str, dict[str, Any]] = {503: SCHEDULE_ERRORS[503]}


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


def _invalid(exc: ValueError) -> HTTPException:
    log.info("invalid schedule: %s", exc)
    return HTTPException(status_code=422, detail=INVALID_REQUEST_MESSAGE)


@router.get(
    "/schedules", response_model=ScheduleList, tags=["schedules"], responses=STORE_ERROR_ONLY
)
def list_schedules(_: InternalKeyDep) -> ScheduleList:
    repo = _open_schedules()
    with _schedule_store_errors():
        found = repo.list_schedules()
    return ScheduleList(items=[ScheduleOut.from_schedule(s) for s in found])


@router.post(
    "/schedules",
    response_model=ScheduleOut,
    status_code=201,
    tags=["schedules"],
    responses={
        409: {"model": ErrorResponse, "description": "The schedule limit is reached"},
        422: {"model": ErrorResponse, "description": "Invalid schedule, or an unknown strategy"},
        **STORE_ERROR_ONLY,
    },
)
def create_schedule(
    body: ScheduleCreate, _: InternalKeyDep, strategies: StrategyServiceDep
) -> ScheduleOut:
    resolve_strategy(strategies, body.strategy)  # 422 for a slug no strategy has
    try:
        schedule = Schedule(**{**body.model_dump(), "symbols": tuple(body.symbols)})
    except ValueError as exc:  # e.g. a blank name the field limits cannot see
        raise _invalid(exc) from exc
    repo = _open_schedules()
    with _schedule_store_errors():
        return ScheduleOut.from_schedule(repo.add(schedule))


@router.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleOut,
    tags=["schedules"],
    responses=SCHEDULE_ERRORS,
)
def get_schedule(schedule_id: ScheduleId, _: InternalKeyDep) -> ScheduleOut:
    return ScheduleOut.from_schedule(_existing(_open_schedules(), schedule_id))


@router.patch(
    "/schedules/{schedule_id}",
    response_model=ScheduleOut,
    tags=["schedules"],
    responses={
        **SCHEDULE_ERRORS,
        422: {"model": ErrorResponse, "description": "Invalid change, or an unknown strategy"},
    },
)
def update_schedule(
    schedule_id: ScheduleId,
    body: ScheduleUpdate,
    _: InternalKeyDep,
    strategies: StrategyServiceDep,
) -> ScheduleOut:
    """Change some fields. Changing the frequency or the enabled flag picks a fresh next slot."""
    repo = _open_schedules()
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    if "symbols" in changes:
        changes["symbols"] = tuple(changes["symbols"])
    with _schedule_update_lock:  # read-merge-write must not interleave with another PATCH
        current = _existing(repo, schedule_id)
        if "strategy" in changes:
            resolve_strategy(strategies, body.strategy)  # 422 for a slug no strategy has
        try:
            merged = replace(current, **changes)  # re-runs the Schedule validation
        except ValueError as exc:
            raise _invalid(exc) from exc
        with _schedule_store_errors():
            return ScheduleOut.from_schedule(repo.update(merged))


@router.delete(
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


@router.post(
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


@router.get(
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


@router.post(
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
