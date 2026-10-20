"""run_schedule: rules, dedupe, lock discipline, overlap guard and failure isolation."""

import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import FLAT, FVG_SETUP, TOUCH_LAST, frame
from schedule_support import (
    T0,
    FakeClock,
    build_deps,
    buy,
    hold,
    make_row,
    stored_schedule,
)

from smc_scanner.ai.analyst import AnalysisResult
from smc_scanner.ai.providers import AiError
from smc_scanner.ai.providers import FakeProvider as ReplayProvider
from smc_scanner.ai.store import StoreError
from smc_scanner.ai.verdict import AiVerdict
from smc_scanner.models import ScanRow
from smc_scanner.notify.telegram import SendResult
from smc_scanner.scanner import ScanOptions, scan_instrument
from smc_scanner.schedule.rules import SKIP_HOLD, SKIP_LOW_CONFIDENCE, SKIP_UNCHANGED
from smc_scanner.schedule.runner import RunDeps, RunGuard, ScanData, default_analyse, run_schedule
from smc_scanner.schedule.store import AlertKey, Schedule, SqliteScheduleRepository
from smc_scanner.schedule.timing import GRACE, next_run_after


def test_delivers_a_signal_and_schedules_the_next_run(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    schedule = stored_schedule(repo)

    report = run_schedule(schedule, deps)

    assert report.status == "ok"
    assert report.delivered == 1
    token, chat, text = rec.sent[0]
    assert chat == "42"
    assert "BUY" in text and "EURUSD" in text and "Advisory only" in text
    stored = repo.get(schedule.id or 0)
    assert stored is not None
    assert stored.last_run_at == T0
    assert stored.next_run_at == next_run_after(T0, "1h")


def test_schedule_chat_id_wins_over_the_default(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)

    run_schedule(stored_schedule(repo, telegram_chat_id="-100"), deps)

    assert rec.sent[0][1] == "-100"


def test_second_run_on_the_same_bar_sends_nothing(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    schedule = stored_schedule(repo)

    run_schedule(schedule, deps)
    again = run_schedule(schedule, deps)

    assert len(rec.sent) == 1
    assert again.delivered == 0
    assert again.skipped == (("EURUSD", "already_sent"),)


def test_a_new_bar_is_sent_again(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    schedule = stored_schedule(repo)
    run_schedule(schedule, deps)
    deps = deps_with_rows(deps, [make_row(bar_time="2026-03-01 12:00:00")])

    run_schedule(schedule, deps)

    assert len(rec.sent) == 2


def deps_with_rows(deps: RunDeps, rows: list[ScanRow]) -> RunDeps:
    def scan(_: Schedule) -> ScanData:
        return ScanData(rows=tuple(rows), frames={}, options=ScanOptions())

    return replace(deps, scan=scan)


def test_failed_send_is_logged_not_fatal_and_retried_next_run(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, send_ok=False)
    schedule = stored_schedule(repo)

    first = run_schedule(schedule, deps)
    second = run_schedule(schedule, deps)

    assert first.status == "ok"
    assert first.delivered == 0
    assert "send failed" in first.errors[0]
    assert len(rec.sent) == 2  # the claim was released, so the second run tried again
    assert second.status == "ok"
    assert repo.get(schedule.id or 0) is not None


def test_sender_raising_is_isolated(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)

    def explode(*_: str) -> object:
        raise RuntimeError("socket gone")

    report = run_schedule(stored_schedule(repo), replace(deps, send=explode))  # type: ignore[arg-type]

    assert report.status == "ok"
    assert report.delivered == 0
    assert any("RuntimeError" in e for e in report.errors)


def test_one_failed_send_does_not_stop_the_others(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, verdicts={"EURUSD": buy(), "XAUUSD": buy()})
    calls = {"n": 0}
    real = deps.send

    def flaky(token: str, chat: str, text: str) -> SendResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return SendResult(ok=False, error="first fails")
        return real(token, chat, text)

    report = run_schedule(stored_schedule(repo), replace(deps, send=flaky))

    assert report.delivered == 1
    assert len(report.errors) == 1


@pytest.mark.parametrize(
    ("verdict", "kwargs", "previous", "reason"),
    [
        (hold(), {}, {}, SKIP_HOLD),
        (buy(50), {"min_confidence": 60.0}, {}, SKIP_LOW_CONFIDENCE),
        (buy(), {"only_on_change": True}, {"EURUSD": "BUY"}, SKIP_UNCHANGED),
    ],
)
def test_rules_skip_with_a_reason_and_send_nothing(
    tmp_path: Path,
    verdict: AiVerdict,
    kwargs: dict[str, object],
    previous: dict[str, str],
    reason: str,
) -> None:
    deps, rec, repo = build_deps(tmp_path, verdicts={"EURUSD": verdict}, previous=previous)

    report = run_schedule(stored_schedule(repo, **kwargs), deps)

    assert rec.sent == []
    assert report.skipped == (("EURUSD", reason),)


def test_hold_is_sent_when_enabled_and_changed_signal_passes(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(
        tmp_path, verdicts={"EURUSD": hold(70)}, previous={"EURUSD": "BUY"}
    )

    report = run_schedule(stored_schedule(repo, send_hold=True, only_on_change=True), deps)

    assert report.delivered == 1


def test_unscored_or_failed_analyses_are_not_delivered(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    row = make_row()

    def analyse(*_: object) -> list[AnalysisResult]:
        return [
            AnalysisResult(row, "failed", error="AiError: x"),
            AnalysisResult(row, "skipped_low_score"),
            AnalysisResult(row, "skipped_cap"),
        ]

    report = run_schedule(stored_schedule(repo), replace(deps, analyse=analyse))

    assert rec.sent == []
    assert [reason for _, reason in report.skipped] == [
        "analysis_failed",
        "analysis_skipped_low_score",
        "analysis_skipped_cap",
    ]


def test_already_analysed_bar_is_still_delivered_once(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    row = make_row()

    def analyse(*_: object) -> list[AnalysisResult]:
        return [AnalysisResult(row, "skipped_duplicate", buy())]

    report = run_schedule(stored_schedule(repo), replace(deps, analyse=analyse))

    assert report.delivered == 1


def test_missing_token_or_chat_skips_delivery_without_claiming(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, chat=None)
    schedule = stored_schedule(repo)

    report = run_schedule(schedule, deps)

    assert report.skipped == (("EURUSD", "no_telegram_target"),)
    assert rec.sent == []
    deps_ok, rec_ok, _ = build_deps(tmp_path, chat="42")
    assert run_schedule(schedule, deps_ok).delivered == 1  # nothing was claimed


def test_lock_is_held_only_around_the_scan(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)

    run_schedule(stored_schedule(repo), deps)

    assert rec.locked_during_scan == [True]
    assert rec.locked_during_provider == [False]
    assert rec.locked_during_send == [False]
    assert not deps.scan_lock.locked()  # type: ignore[attr-defined]


def test_lock_is_released_when_the_scan_fails(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, scan_error=RuntimeError("mt5 down"))

    report = run_schedule(stored_schedule(repo), deps)

    assert report.status == "failed"
    assert "RuntimeError" in report.errors[0]
    assert not deps.scan_lock.locked()  # type: ignore[attr-defined]
    assert rec.sent == []


def test_failed_run_still_advances_the_schedule(tmp_path: Path) -> None:
    deps, _, repo = build_deps(tmp_path, scan_error=RuntimeError("mt5 down"))
    schedule = stored_schedule(repo)

    run_schedule(schedule, deps)

    stored = repo.get(schedule.id or 0)
    assert stored is not None
    assert stored.last_run_at == T0
    assert stored.next_run_at == next_run_after(T0, "1h")


def test_provider_factory_failure_is_a_failed_run(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)

    def broken() -> object:
        raise AiError("ANTHROPIC_API_KEY is not set")

    report = run_schedule(stored_schedule(repo), replace(deps, provider_factory=broken))  # type: ignore[arg-type]

    assert report.status == "failed"
    assert "ANTHROPIC_API_KEY" in report.errors[0]
    assert rec.sent == []


def test_provider_failure_leaves_a_failed_analysis_not_a_crashed_run(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, provider_fails=True)

    report = run_schedule(stored_schedule(repo), deps)

    assert report.status == "failed"
    assert rec.sent == []


def test_busy_scan_lock_skips_the_run_and_keeps_the_slot(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    schedule = stored_schedule(repo, next_run_at=T0)
    deps = replace(deps, lock_timeout=0.0)
    deps.scan_lock.acquire()
    try:
        report = run_schedule(schedule, deps)
    finally:
        deps.scan_lock.release()

    assert report.status == "busy"
    assert rec.scans == 0
    stored = repo.get(schedule.id or 0)
    assert stored is not None
    assert stored.next_run_at == T0  # still due; the next tick retries


def test_guard_blocks_a_reentrant_run_of_the_same_schedule(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    schedule = stored_schedule(repo)
    assert deps.guard.try_enter(schedule.id or 0)

    report = run_schedule(schedule, deps)

    assert report.status == "already_running"
    assert rec.scans == 0
    deps.guard.leave(schedule.id or 0)
    assert run_schedule(schedule, deps).status == "ok"


def test_overlapping_runs_never_execute_concurrently(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def hook() -> None:
        entered.set()
        assert release.wait(timeout=5)

    deps, rec, repo = build_deps(tmp_path, scan_hook=hook)
    schedule = stored_schedule(repo)
    reports: list[str] = []
    worker = threading.Thread(target=lambda: reports.append(run_schedule(schedule, deps).status))
    worker.start()
    assert entered.wait(timeout=5)

    overlapping = run_schedule(schedule, deps)
    release.set()
    worker.join(timeout=5)

    assert overlapping.status == "already_running"
    assert reports == ["ok"]
    assert rec.scans == 1


def test_guard_is_released_after_a_crash(tmp_path: Path) -> None:
    deps, _, repo = build_deps(tmp_path, scan_error=RuntimeError("x"))
    schedule = stored_schedule(repo)

    run_schedule(schedule, deps)

    assert deps.guard.try_enter(schedule.id or 0)


def test_run_guard_is_per_schedule() -> None:
    guard = RunGuard()

    assert guard.try_enter(1)
    assert not guard.try_enter(1)
    assert guard.try_enter(2)
    guard.leave(1)
    assert guard.try_enter(1)


def test_store_failure_when_marking_the_run_is_swallowed(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    schedule = stored_schedule(repo)

    class BrokenMark:
        def __getattr__(self, name: str) -> object:
            return getattr(repo, name)

        def mark_run(self, *_: object, **__: object) -> None:
            raise StoreError("disk full")

    report = run_schedule(schedule, replace(deps, repo=BrokenMark()))  # type: ignore[arg-type]

    assert report.status == "ok"
    assert report.recorded is False
    assert any("disk full" in e for e in report.errors)


def test_previous_action_lookup_failure_is_treated_as_no_history(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)

    def boom(*_: str) -> str | None:
        raise StoreError("locked")

    report = run_schedule(
        stored_schedule(repo, only_on_change=True), replace(deps, previous_action=boom)
    )

    assert report.delivered == 1


def test_schedule_needs_an_id(tmp_path: Path) -> None:
    deps, _, _ = build_deps(tmp_path)
    unsaved = Schedule(name="x", source="demo", tf="1h", symbols=("EURUSD",), frequency="1h")

    with pytest.raises(ValueError, match="id"):
        run_schedule(unsaved, deps)


# --- the real analyse path, with a replayed provider ---------------------------------

OHLC = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST])
OPTIONS = ScanOptions(swing_length=2)
HOLD_REPLY = '{"action": "HOLD", "confidence": 40, "reasons": ["weak"], "summary": "No edge."}'


def test_default_analyse_saves_once_and_a_rerun_sends_nothing(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    provider = ReplayProvider([HOLD_REPLY])
    rows = tuple(scan_instrument("EURUSD", OHLC, OPTIONS))
    assert rows

    def scan(_: Schedule) -> ScanData:
        return ScanData(rows=rows, frames={"EURUSD": OHLC}, options=OPTIONS)

    real = replace(
        deps,
        scan=scan,
        analyse=default_analyse,
        provider_factory=lambda: provider,
        clock=FakeClock(),
    )
    schedule = stored_schedule(repo, send_hold=True, min_score=0)

    first = run_schedule(schedule, real)
    second = run_schedule(schedule, real)

    assert first.delivered >= 1
    assert second.delivered == 0
    assert len(provider.calls) == len(rows)  # the second run did not call the model again
    assert all(reason == "already_sent" for _, reason in second.skipped)


def test_grace_is_a_few_seconds() -> None:
    assert timedelta(seconds=1) <= GRACE <= timedelta(seconds=30)


class _FlakyAlerts:
    """Repository whose alert calls raise StoreError for chosen symbols."""

    def __init__(
        self, repo: SqliteScheduleRepository, claim_fails: set[str], release_fails: bool = False
    ) -> None:
        self._repo = repo
        self._claim_fails = claim_fails
        self._release_fails = release_fails

    def __getattr__(self, name: str) -> object:
        return getattr(self._repo, name)

    def claim_alert(self, key: AlertKey, sent_at: datetime) -> bool:
        if key.symbol in self._claim_fails:
            raise StoreError("db locked")
        return self._repo.claim_alert(key, sent_at)

    def release_alert(self, key: AlertKey) -> None:
        if self._release_fails:
            raise StoreError("db locked")
        self._repo.release_alert(key)


def test_claim_store_error_is_isolated_per_symbol(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, verdicts={"EURUSD": buy(), "XAUUSD": buy()})
    flaky = replace(deps, repo=_FlakyAlerts(repo, {"EURUSD"}))  # type: ignore[arg-type]

    report = run_schedule(stored_schedule(repo, symbols=("EURUSD", "XAUUSD")), flaky)

    assert report.status == "ok"
    assert report.delivered == 1  # XAUUSD still went out
    assert len(rec.sent) == 1
    assert any(e.startswith("EURUSD: alert store error") for e in report.errors)


def test_release_store_error_after_failed_send_is_reported(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path, send_ok=False)
    flaky = replace(deps, repo=_FlakyAlerts(repo, set(), release_fails=True))  # type: ignore[arg-type]

    report = run_schedule(stored_schedule(repo), flaky)

    assert report.status == "ok"
    assert any("send failed" in e for e in report.errors)
    assert any("alert store error" in e for e in report.errors)


def test_stop_event_prevents_a_run_from_starting(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    deps.stop_event.set()
    schedule = stored_schedule(repo, next_run_at=T0)

    report = run_schedule(schedule, deps)

    assert report.status == "stopped"
    assert rec.scans == 0
    assert repo.get(schedule.id or 0).next_run_at == T0  # type: ignore[union-attr]


def test_stop_event_ends_the_wait_for_the_scan_lock(tmp_path: Path) -> None:
    deps, rec, repo = build_deps(tmp_path)
    deps = replace(deps, lock_timeout=60.0)
    deps.scan_lock.acquire()
    timer = threading.Timer(0.2, deps.stop_event.set)
    timer.start()
    try:
        report = run_schedule(stored_schedule(repo), deps)
    finally:
        timer.cancel()
        deps.scan_lock.release()

    assert report.status == "stopped"
    assert rec.scans == 0
