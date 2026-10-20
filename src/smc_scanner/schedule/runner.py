"""Run a schedule: scan closed bars, analyse hits, apply the rules, deliver to Telegram.

Locking contract
    ``scan_lock`` (the app's ``api._scan_lock``, a ``threading.Lock``) is held ONLY around the scan
    / MT5 part, so a scheduled scan and a ``/scan`` request never use the terminal at the same
    time. It is never held during LLM or Telegram calls. If it cannot be taken within
    ``lock_timeout`` the run reports ``busy`` and leaves the slot due, so the next tick retries.
    A per-schedule ``RunGuard`` stops two runs of the same schedule overlapping.

Scope of phase A: provider (LLM) and MT5 call timeouts are NOT enforced here; they belong to
    the provider and loader. Only the wait for ``scan_lock`` is bounded (``lock_timeout``).

Failure contract
    ``run_schedule`` never raises (except ValueError for a schedule without an id). Scan, AI,
    store and Telegram problems become a ``RunReport`` and a log line; a failed run still
    advances ``last_run_at``/``next_run_at`` so it cannot hot-loop. A failed send releases its
    dedupe claim so a later run can retry it. Message bodies and the bot token are never logged.
    ``RunReport.errors`` holds exception text and must NEVER be returned to unauthenticated
    callers; show it only behind the internal key, or log it.

Alert gap
    A dedupe claim is written BEFORE the send (so two runs cannot both send). If the process dies
    between the claim and the send, that bar's alert is lost and not retried. A send that merely
    fails releases its claim and is retried.

Single process only
    ``SchedulerService`` keeps its state in memory and the guard is per process. Run exactly one
    worker (one uvicorn process, no ``--workers N``) or every worker would scan and alert.

Phase B contract for ``api.py`` (the FastAPI lifespan hook; not implemented here)
    Build once at startup, then only call ``start()`` and ``stop()``::

        repo = SqliteScheduleRepository(db_path_from_env())
        token, chat = telegram_settings_from_env()
        stop = threading.Event()
        deps = RunDeps(
            repo=repo,
            stop_event=stop,
            analysis_store=SqliteAnalysisStore(db_path),
            provider_factory=make_provider,
            scan=make_scan_fn(),
            scan_lock=_scan_lock,                     # the SAME object /scan uses
            previous_action=partial(previous_action, db_path),
            zone=server_zone_from_env(),   # SMC_SERVER_TZ: the broker clock for 4h/1d
            telegram_token=token,
            default_chat_id=chat,
        )
        service = SchedulerService(
            repo, partial(run_schedule, deps=deps), zone=server_zone_from_env(), stop_event=stop
        )
        # lifespan: service.start() before yield, service.stop() after
        # schedule CRUD endpoints: call service.reload() after any change

    Needed from api.py: the shared ``_scan_lock``, a lifespan context, and the resolved
    ``SMC_DB_PATH``. ``TELEGRAM_BOT_TOKEN`` (and optionally ``TELEGRAM_CHAT_ID``) come from the
    environment. Keep the service disabled in tests (do not start it from the default app).
"""

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Final, Literal, Protocol

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from smc_scanner.ai.analyst import AnalysisResult, HitInputs, analyse_hits, hit_inputs_from_ohlc
from smc_scanner.ai.providers import AiProvider
from smc_scanner.ai.store import AnalysisKey, AnalysisStore, StoreError
from smc_scanner.ai_cli import FrameCache
from smc_scanner.config import DEFAULT_BARS
from smc_scanner.loaders import make_loader
from smc_scanner.loaders.base import Loader
from smc_scanner.models import ScanRow
from smc_scanner.notify.telegram import SendResult, format_verdict_message, send_message
from smc_scanner.scanner import ScanOptions, run_scan
from smc_scanner.schedule.rules import decide
from smc_scanner.schedule.store import AlertKey, Schedule, ScheduleRepository
from smc_scanner.schedule.timing import GRACE, SERVER_ZONE, is_due, missed_slots, next_run_after

log = logging.getLogger(__name__)

TOKEN_ENV: Final = "TELEGRAM_BOT_TOKEN"
CHAT_ENV: Final = "TELEGRAM_CHAT_ID"
SCAN_LOCK_TIMEOUT_SECONDS: Final = 300.0
TICK_SECONDS: Final = 15
TICK_JOB_ID: Final = "smc-schedule-tick"
LOCK_POLL_SECONDS: Final = 1.0  # how often a waiting run looks at the stop flag
DELIVERABLE: Final = frozenset({"analysed", "skipped_duplicate"})
MAX_ERROR_CHARS: Final = 200

RunStatus = Literal["ok", "failed", "busy", "already_running", "stopped"]
_UNRECORDED = frozenset({"busy", "stopped"})  # runs that keep their slot
Clock = Callable[[], datetime]


class ScanLock(Protocol):
    """The slice of ``threading.Lock`` the runner uses."""

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class ScanData:
    """What a scan hands to the analyst: hit rows, the frames they came from, the options."""

    rows: tuple[ScanRow, ...]
    frames: Mapping[str, pd.DataFrame]
    options: ScanOptions


ScanFn = Callable[[Schedule], ScanData]
AnalyseFn = Callable[[ScanData, Schedule, AiProvider, AnalysisStore, Clock], list[AnalysisResult]]
Sender = Callable[[str, str, str], SendResult]  # bot token, chat id, HTML text
PreviousAction = Callable[[str, str, str], str | None]  # symbol, timeframe, bar time


@dataclass(frozen=True)
class RunReport:
    schedule_id: int
    status: RunStatus
    rows: int = 0
    delivered: int = 0
    skipped: tuple[tuple[str, str], ...] = ()  # (symbol, reason)
    errors: tuple[str, ...] = ()
    recorded: bool = True  # False when last/next run could not be written to the store


class RunGuard:
    """Non-reentrant guard: at most one run per schedule id at a time, per process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[int] = set()

    def try_enter(self, schedule_id: int) -> bool:
        with self._lock:
            if schedule_id in self._running:
                return False
            self._running.add(schedule_id)
            return True

    def leave(self, schedule_id: int) -> None:
        with self._lock:
            self._running.discard(schedule_id)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def default_analyse(
    data: ScanData,
    schedule: Schedule,
    provider: AiProvider,
    store: AnalysisStore,
    clock: Clock,
) -> list[AnalysisResult]:
    """``analyse_hits`` over the scanned frames, gated by the schedule's ``min_score``."""

    def source(row: ScanRow) -> HitInputs:
        return hit_inputs_from_ohlc(data.frames[row.instrument], row, data.options)

    return analyse_hits(
        data.rows, source, provider, store, timeframe=schedule.tf, min_score=schedule.min_score,
        now=clock,
    )  # fmt: skip


def _default_send(token: str, chat_id: str, text: str) -> SendResult:
    return send_message(token, chat_id, text)


@dataclass(frozen=True)
class RunDeps:
    """Everything a run needs, injected so tests use fakes, a temp DB and a fake clock."""

    repo: ScheduleRepository
    analysis_store: AnalysisStore
    provider_factory: Callable[[], AiProvider]
    scan: ScanFn
    scan_lock: ScanLock
    previous_action: PreviousAction
    telegram_token: str
    send: Sender = _default_send
    clock: Clock = _utc_now
    default_chat_id: str | None = None
    analyse: AnalyseFn = default_analyse
    guard: RunGuard = field(default_factory=RunGuard)
    zone: tzinfo = SERVER_ZONE
    grace: timedelta = GRACE
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock_timeout: float = SCAN_LOCK_TIMEOUT_SECONDS


def telegram_settings_from_env() -> tuple[str, str | None]:
    """(bot token, default chat id) from TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID; blank = unset."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    chat = os.environ.get(CHAT_ENV, "").strip()
    return token, chat or None


def make_scan_fn(
    *,
    loader_factory: Callable[[str], Loader] = make_loader,
    bars: int = DEFAULT_BARS,
    options: ScanOptions | None = None,
) -> ScanFn:
    """A scan over closed bars only (``make_loader`` defaults to ``closed_only=True``)."""
    chosen = options or ScanOptions()

    def scan(schedule: Schedule) -> ScanData:
        cache = FrameCache(loader_factory(schedule.source))
        result = run_scan(cache, schedule.symbols, schedule.tf, bars, chosen)
        if result.all_failed:
            raise RuntimeError("no symbol could be loaded")
        return ScanData(rows=result.rows, frames=dict(cache.frames), options=chosen)

    return scan


def _short(exc: BaseException) -> str:
    """Class name plus message, bounded; SDK and Telegram messages are token-free by contract."""
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]


def _acquire_scan_lock(deps: RunDeps) -> bool:
    """Wait up to ``lock_timeout`` for the scan lock, giving up early when stop is requested."""
    deadline = time.monotonic() + deps.lock_timeout
    while True:
        wait = min(LOCK_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
        if deps.scan_lock.acquire(timeout=wait):
            return True
        if deps.stop_event.is_set() or time.monotonic() >= deadline:
            return False


def _scan_under_lock(schedule: Schedule, deps: RunDeps) -> ScanData | RunReport:
    sid = schedule.id or 0
    if not _acquire_scan_lock(deps):
        if deps.stop_event.is_set():
            return RunReport(sid, "stopped")
        log.warning("schedule %s: scan lock busy, run postponed", sid)
        return RunReport(sid, "busy")
    try:
        return deps.scan(schedule)
    except Exception as exc:
        log.error("schedule %s: scan failed: %s", sid, type(exc).__name__)
        return RunReport(sid, "failed", errors=(_short(exc),))
    finally:
        deps.scan_lock.release()


def _alert_key(schedule_id: int, tf: str, row: ScanRow) -> AlertKey:
    key = AnalysisKey(row.instrument, tf, row.zone.split()[-1], row.zone_low, row.zone_high,
                      row.bar_time)  # fmt: skip
    zone_key = f"{key.zone_kind}:{key.zone_low!r}:{key.zone_high!r}"
    return AlertKey(schedule_id, key.symbol, key.tf, zone_key, key.bar_time)


def _previous(deps: RunDeps, row: ScanRow, tf: str) -> str | None:
    try:
        return deps.previous_action(row.instrument, tf, row.bar_time)
    except Exception as exc:
        log.warning("%s: no signal history (%s)", row.instrument, type(exc).__name__)
        return None


def _release(deps: RunDeps, key: AlertKey, out: "_Outcome") -> None:
    try:
        deps.repo.release_alert(key)
    except StoreError as exc:
        log.error("schedule %s: %s: could not release alert: %s", key.schedule_id, key.symbol, exc)
        out.errors.append(f"{key.symbol}: alert store error ({_short(exc)})")


def _send_one(deps: RunDeps, token: str, chat: str, text: str) -> SendResult:
    try:
        return deps.send(token, chat, text)
    except Exception as exc:  # a notifier must never take the run down
        return SendResult(ok=False, error=type(exc).__name__)


@dataclass
class _Outcome:
    delivered: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _deliver(
    schedule: Schedule, sid: int, results: list[AnalysisResult], deps: RunDeps
) -> _Outcome:
    out = _Outcome()
    chat = schedule.telegram_chat_id or deps.default_chat_id
    for result in results:
        row, verdict = result.row, result.verdict
        symbol = row.instrument
        if verdict is None or result.status not in DELIVERABLE:
            reason = "analysis_failed" if result.status == "failed" else f"analysis_{result.status}"
            out.skipped.append((symbol, reason))
            continue
        decision = decide(
            action=verdict.action,
            confidence=verdict.confidence,
            min_confidence=schedule.min_confidence,
            only_on_change=schedule.only_on_change,
            send_hold=schedule.send_hold,
            previous_action=_previous(deps, row, schedule.tf) if schedule.only_on_change else None,
        )
        if not decision.deliver:
            out.skipped.append((symbol, decision.skip_reason))
            continue
        if not deps.telegram_token or not chat:
            out.skipped.append((symbol, "no_telegram_target"))
            continue
        key = _alert_key(sid, schedule.tf, row)
        try:
            if not deps.repo.claim_alert(key, deps.clock()):
                out.skipped.append((symbol, "already_sent"))
                continue
        except StoreError as exc:  # cannot dedupe, so do not send; other symbols carry on
            log.error("schedule %s: %s: alert store error: %s", sid, symbol, exc)
            out.errors.append(f"{symbol}: alert store error ({_short(exc)})")
            continue
        text = format_verdict_message(
            symbol, schedule.tf, verdict, zone=(row.zone_low, row.zone_high)
        )
        sent = _send_one(deps, deps.telegram_token, chat, text)
        if sent.ok:
            out.delivered += 1
        else:
            out.errors.append(f"{symbol}: send failed ({sent.error})")
            _release(deps, key, out)  # let a later run retry this bar
    for symbol, reason in out.skipped:
        log.info("schedule %s: %s not sent (%s)", sid, symbol, reason)
    return out


def _finish(schedule: Schedule, deps: RunDeps, report: RunReport) -> RunReport:
    """Stamp last/next run. Postponed (busy/stopped) runs keep their slot.

    ``next_run_at`` is only stored if the schedule's frequency is unchanged since the run began
    (an edit mid-run clears it instead). If the store write fails the report says
    ``recorded=False`` so the service can back off rather than re-run the same slot every tick.
    """
    if report.status in _UNRECORDED:
        return report
    now = deps.clock()
    upcoming = next_run_after(now, schedule.frequency, grace=deps.grace, zone=deps.zone)
    try:
        deps.repo.mark_run(report.schedule_id, now, upcoming, frequency=schedule.frequency)
    except StoreError as exc:
        log.error("schedule %s: could not record the run: %s", report.schedule_id, exc)
        return replace(report, errors=(*report.errors, _short(exc)), recorded=False)
    return report


def _run_status(results: list[AnalysisResult], delivered: int) -> RunStatus:
    """ "failed" only when every analysis failed and nothing was delivered; else "ok"."""
    all_failed = bool(results) and all(r.status == "failed" for r in results)
    return "failed" if all_failed and not delivered else "ok"


def _run(schedule: Schedule, deps: RunDeps) -> RunReport:
    sid = schedule.id or 0
    scanned = _scan_under_lock(schedule, deps)
    if isinstance(scanned, RunReport):
        return scanned
    try:  # from here on no lock is held: the model and Telegram can be slow
        provider = deps.provider_factory()
        results = deps.analyse(scanned, schedule, provider, deps.analysis_store, deps.clock)
    except Exception as exc:
        log.error("schedule %s: analysis failed: %s", sid, type(exc).__name__)
        return RunReport(sid, "failed", rows=len(scanned.rows), errors=(_short(exc),))
    failed = [r for r in results if r.status == "failed"]
    outcome = _deliver(schedule, sid, results, deps)
    errors = [*(f"{r.row.instrument}: {r.error}" for r in failed), *outcome.errors]
    return RunReport(
        sid,
        _run_status(results, outcome.delivered),
        rows=len(scanned.rows),
        delivered=outcome.delivered,
        skipped=tuple(outcome.skipped),
        errors=tuple(errors),
    )


def run_schedule(schedule: Schedule, deps: RunDeps) -> RunReport:
    """One full run of ``schedule``. See the module docstring for the lock and failure contracts."""
    if schedule.id is None:
        raise ValueError("a schedule needs an id to run")
    sid = schedule.id
    if deps.stop_event.is_set():
        return RunReport(sid, "stopped")
    if not deps.guard.try_enter(sid):
        log.warning("schedule %s: still running, overlapping run skipped", sid)
        return RunReport(sid, "already_running")
    try:
        report = _run(schedule, deps)
    except Exception as exc:  # last resort: a scheduled run must not kill the scheduler thread
        log.exception("schedule %s: unexpected error", sid)
        report = RunReport(sid, "failed", errors=(_short(exc),))
    finally:
        deps.guard.leave(sid)
    return _finish(schedule, deps, report)


def _new_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(timezone=UTC)


class SchedulerService:
    """Calls due schedules from an APScheduler ``BackgroundScheduler`` tick (single process).

    One interval job (``tick_seconds``) re-reads the repository, gives any enabled schedule that
    has no slot its next slot, then runs each due schedule once, in order. Slots come from
    ``timing``, so downtime collapses into a single catch-up run.

    The first run that reports ``busy`` (scan lock held, e.g. by a slow ``/scan``) ends the
    tick: every other schedule needs the same lock, so a tick waits at most one ``lock_timeout``
    instead of one per schedule; the skipped schedules stay due for the next tick.

    ``stop()`` sets ``stop_event``: the tick stops between schedules, before a run, and while
    waiting for the scan lock. Pass the same event as ``RunDeps.stop_event``. A run already past
    the lock (LLM/Telegram) is not interrupted. ``start()`` builds a fresh scheduler from
    ``scheduler_factory`` every time, because APScheduler 3.x cannot restart after shutdown.

    If a run cannot record its times (store error) the schedule is held back in memory until
    its next slot, so a broken store cannot cause a scan and alert attempt on every tick.
    """

    def __init__(
        self,
        repo: ScheduleRepository,
        run: Callable[[Schedule], RunReport],
        *,
        clock: Clock = _utc_now,
        tick_seconds: int = TICK_SECONDS,
        zone: tzinfo = SERVER_ZONE,
        grace: timedelta = GRACE,
        scheduler_factory: Callable[[], BackgroundScheduler] = _new_scheduler,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._repo = repo
        self._run = run
        self._clock = clock
        self._tick_seconds = tick_seconds
        self._zone = zone
        self._grace = grace
        self._factory = scheduler_factory
        self._scheduler: BackgroundScheduler | None = None
        self.stop_event = stop_event or threading.Event()
        self._tick_lock = threading.Lock()
        self._hold_until: dict[int, datetime] = {}

    @property
    def running(self) -> bool:
        return self._scheduler is not None and bool(self._scheduler.running)

    def start(self) -> None:
        """Give every enabled schedule a slot, then begin ticking. Idempotent."""
        if self.running:
            return
        self.stop_event.clear()
        self.reload()
        scheduler = self._factory()
        scheduler.add_job(
            self.tick,
            IntervalTrigger(seconds=self._tick_seconds, timezone=UTC),
            id=TICK_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        log.info("scheduler started (tick every %ss)", self._tick_seconds)

    def stop(self) -> None:
        """Ask runs to stop and shut the scheduler down without waiting. Idempotent."""
        self.stop_event.set()
        scheduler, self._scheduler = self._scheduler, None
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("scheduler stopped")

    def reload(self) -> None:
        """Give every enabled schedule without a slot its next slot (no instant run)."""
        now = self._clock()
        for schedule in self._repo.list_schedules(enabled_only=True):
            if schedule.next_run_at is None and schedule.id is not None:
                self._repo.set_next_run(schedule.id, self._upcoming(schedule, now))

    def tick(self) -> int:
        """Run every due schedule once; returns how many ran. Never raises, never overlaps."""
        if not self._tick_lock.acquire(blocking=False):
            return 0
        try:
            self.reload()  # a schedule added or re-enabled since the last tick gets its slot
            return self._tick()
        except Exception:
            log.exception("scheduler tick failed")
            return 0
        finally:
            self._tick_lock.release()

    def _upcoming(self, schedule: Schedule, now: datetime) -> datetime:
        return next_run_after(now, schedule.frequency, grace=self._grace, zone=self._zone)

    def _tick(self) -> int:
        ran = 0
        for listed in self._repo.list_schedules(enabled_only=True):
            if self.stop_event.is_set():
                break
            now = self._clock()
            if not self._should_run(listed, now):
                continue
            schedule = self._repo.get(listed.id or 0)  # it may have been edited or paused
            if schedule is None or not schedule.enabled or not is_due(schedule.next_run_at, now):
                continue
            if self.stop_event.is_set():
                break
            late = missed_slots(schedule.next_run_at or now, now, schedule.frequency)
            if late:
                log.info("schedule %s: %s missed slot(s) collapsed into one run", schedule.id, late)
            try:
                report = self._run(schedule)
            except Exception:  # run_schedule never raises; this protects a custom run function
                log.exception("schedule %s: run crashed", schedule.id)
                self._advance(schedule, now)
                continue
            if report.status in ("busy", "stopped"):
                break
            if report.recorded:
                self._hold_until.pop(schedule.id or 0, None)
            else:
                self._hold(schedule, now)
            ran += report.status != "already_running"
        return ran

    def _should_run(self, schedule: Schedule, now: datetime) -> bool:
        if not is_due(schedule.next_run_at, now):
            return False
        hold = self._hold_until.get(schedule.id or 0)
        return hold is None or now >= hold

    def _hold(self, schedule: Schedule, now: datetime) -> None:
        """Skip this schedule until its next slot; logs once per hold."""
        sid = schedule.id or 0
        if sid not in self._hold_until or now >= self._hold_until[sid]:
            log.error("schedule %s: run not recorded; held until its next slot", sid)
        self._hold_until[sid] = self._upcoming(schedule, now)

    def _advance(self, schedule: Schedule, now: datetime) -> None:
        if schedule.id is None:
            return
        try:
            self._repo.mark_run(
                schedule.id, now, self._upcoming(schedule, now), frequency=schedule.frequency
            )
        except StoreError as exc:
            log.error("schedule %s: could not advance: %s", schedule.id, exc)
            self._hold(schedule, now)
