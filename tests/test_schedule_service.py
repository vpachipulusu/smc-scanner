"""SchedulerService: tick selection, missed-run collapse, isolation, start/stop."""

from datetime import UTC, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from schedule_support import T0, FakeClock, build_deps, stored_schedule

from smc_scanner.ai.store import StoreError
from smc_scanner.schedule.runner import RunReport, SchedulerService, run_schedule
from smc_scanner.schedule.store import Schedule
from smc_scanner.schedule.timing import next_run_after


def _service(tmp_path: Path, **kwargs: object):  # type: ignore[no-untyped-def]
    clock = FakeClock()
    deps, rec, repo = build_deps(tmp_path, clock=clock, **kwargs)  # type: ignore[arg-type]
    service = SchedulerService(
        repo, lambda s: run_schedule(s, deps), clock=clock, tick_seconds=3600
    )
    return service, rec, repo, clock


def test_reload_gives_unscheduled_schedules_a_slot_without_running_them(tmp_path: Path) -> None:
    service, rec, repo, _ = _service(tmp_path)
    schedule = stored_schedule(repo)

    service.reload()

    stored = repo.get(schedule.id or 0)
    assert stored is not None
    assert stored.next_run_at == next_run_after(T0, "1h")
    assert stored.last_run_at is None
    assert rec.scans == 0


def test_tick_runs_only_due_enabled_schedules(tmp_path: Path) -> None:
    service, rec, repo, clock = _service(tmp_path)
    due = stored_schedule(repo, name="due", next_run_at=T0)
    stored_schedule(repo, name="later", next_run_at=T0 + timedelta(minutes=5))
    stored_schedule(repo, name="paused", enabled=False, next_run_at=T0)
    stored_schedule(repo, name="unscheduled")

    ran = service.tick()

    assert ran == 1
    assert rec.scans == 1
    assert repo.get(due.id or 0).last_run_at == clock.now


def test_missed_runs_after_downtime_run_once(tmp_path: Path) -> None:
    service, rec, repo, clock = _service(tmp_path)
    stored_schedule(repo, next_run_at=T0 - timedelta(hours=9))

    first = service.tick()
    second = service.tick()

    assert (first, second) == (1, 0)
    assert rec.scans == 1


def test_next_slot_is_reached_after_time_passes(tmp_path: Path) -> None:
    service, rec, repo, clock = _service(tmp_path)
    stored_schedule(repo, next_run_at=T0)
    service.tick()

    clock.advance(timedelta(hours=1))

    assert service.tick() == 1
    assert rec.scans == 2


def test_a_crashing_run_does_not_stop_other_schedules_and_still_advances(tmp_path: Path) -> None:
    clock = FakeClock()
    deps, rec, repo = build_deps(tmp_path, clock=clock)
    bad = stored_schedule(repo, name="bad", next_run_at=T0)
    good = stored_schedule(repo, name="good", next_run_at=T0)
    seen: list[str] = []

    def run(schedule: Schedule) -> RunReport:
        seen.append(schedule.name)
        if schedule.name == "bad":
            raise RuntimeError("boom")
        return run_schedule(schedule, deps)

    service = SchedulerService(repo, run, clock=clock, tick_seconds=3600)

    ran = service.tick()

    assert seen == ["bad", "good"]
    assert ran == 1
    advanced = repo.get(bad.id or 0)
    assert advanced is not None and advanced.next_run_at == next_run_after(T0, "1h")
    assert repo.get(good.id or 0).last_run_at == T0  # type: ignore[union-attr]


def test_busy_run_keeps_the_slot_for_the_next_tick(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    schedule = stored_schedule(repo, next_run_at=T0)
    service = SchedulerService(
        repo, lambda s: RunReport(s.id or 0, "busy"), clock=clock, tick_seconds=3600
    )

    assert service.tick() == 0
    assert repo.get(schedule.id or 0).next_run_at == T0  # type: ignore[union-attr]


def test_tick_never_raises_when_the_repository_fails(tmp_path: Path) -> None:
    service, _, repo, _ = _service(tmp_path)

    class Broken:
        def list_schedules(self, *, enabled_only: bool = False) -> list[Schedule]:
            raise RuntimeError("db gone")

    broken = SchedulerService(Broken(), lambda s: RunReport(0, "ok"), tick_seconds=3600)  # type: ignore[arg-type]

    assert broken.tick() == 0


def test_overlapping_ticks_do_not_run_twice(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    stored_schedule(repo, next_run_at=T0)
    holder: list[SchedulerService] = []
    inner: list[int] = []

    def run(schedule: Schedule) -> RunReport:
        inner.append(holder[0].tick())  # a tick arriving while one is running
        return RunReport(schedule.id or 0, "ok")

    service = SchedulerService(repo, run, clock=clock, tick_seconds=3600)
    holder.append(service)

    assert service.tick() == 1
    assert inner == [0]


def test_start_and_stop_are_idempotent_and_reflect_state(tmp_path: Path) -> None:
    service, rec, repo, _ = _service(tmp_path)
    schedule = stored_schedule(repo)

    service.start()
    service.start()
    assert service.running
    assert repo.get(schedule.id or 0).next_run_at is not None
    service.stop()
    service.stop()

    assert not service.running
    assert rec.scans == 0  # a long tick interval: nothing ran during the test


def test_busy_scan_lock_ends_the_tick_so_waits_do_not_stack(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    first = stored_schedule(repo, name="a", next_run_at=T0)
    second = stored_schedule(repo, name="b", next_run_at=T0)
    seen: list[str] = []

    def run(schedule: Schedule) -> RunReport:
        seen.append(schedule.name)
        return RunReport(schedule.id or 0, "busy")

    service = SchedulerService(repo, run, clock=clock, tick_seconds=3600)

    assert service.tick() == 0
    assert seen == ["a"]  # b was not tried this tick; it stays due
    assert repo.get(second.id or 0).next_run_at == T0  # type: ignore[union-attr]
    assert first.id is not None


def test_start_stop_start_works_with_a_fresh_scheduler_each_time(tmp_path: Path) -> None:
    built: list[BackgroundScheduler] = []

    def factory() -> BackgroundScheduler:
        scheduler = BackgroundScheduler(timezone=UTC)
        built.append(scheduler)
        return scheduler

    _, _, repo = build_deps(tmp_path)
    service = SchedulerService(
        repo, lambda s: RunReport(s.id or 0, "ok"), tick_seconds=3600, scheduler_factory=factory
    )

    service.start()
    service.stop()
    assert not service.running
    service.start()

    assert service.running
    assert len(built) == 2 and built[0] is not built[1]
    assert not service.stop_event.is_set()  # start() clears the flag from the earlier stop
    service.stop()
    assert service.stop_event.is_set()


def test_unrecorded_run_is_held_back_until_the_next_slot(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    stored_schedule(repo, next_run_at=T0)
    runs: list[int] = []

    def run(s: Schedule) -> RunReport:
        runs.append(1)
        return RunReport(s.id or 0, "ok", recorded=False)  # the store write failed

    service = SchedulerService(repo, run, clock=clock, tick_seconds=3600)

    service.tick()
    service.tick()
    clock.advance(timedelta(minutes=30))
    service.tick()
    assert len(runs) == 1  # no hot loop while the slot is stale in the store

    clock.advance(timedelta(hours=1))
    service.tick()
    assert len(runs) == 2


def test_a_crashing_run_with_a_broken_store_is_held_back_too(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    stored_schedule(repo, next_run_at=T0)
    runs: list[int] = []

    class BrokenMark:
        def __getattr__(self, name: str) -> object:
            return getattr(repo, name)

        def mark_run(self, *_: object, **__: object) -> None:
            raise StoreError("disk full")

    def run(_: Schedule) -> RunReport:
        runs.append(1)
        raise RuntimeError("boom")

    service = SchedulerService(BrokenMark(), run, clock=clock, tick_seconds=3600)  # type: ignore[arg-type]

    service.tick()
    service.tick()

    assert len(runs) == 1


def test_tick_gives_a_new_schedule_a_slot_instead_of_ignoring_it(tmp_path: Path) -> None:
    service, rec, repo, clock = _service(tmp_path)
    fresh = stored_schedule(repo)  # added after start; no slot yet

    service.tick()
    assert rec.scans == 0
    assert repo.get(fresh.id or 0).next_run_at is not None

    clock.advance(timedelta(hours=1, minutes=1))
    assert service.tick() == 1


def test_a_schedule_paused_after_listing_is_not_run(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    schedule = stored_schedule(repo, next_run_at=T0)
    seen: list[str] = []

    class Racy:
        """Lists the schedule as due, then it is paused before the tick re-reads it."""

        def __getattr__(self, name: str) -> object:
            return getattr(repo, name)

        def list_schedules(self, *, enabled_only: bool = False) -> list[Schedule]:
            listed = repo.list_schedules(enabled_only=enabled_only)
            repo.update(Schedule(**{**schedule.__dict__, "enabled": False}))
            return listed

    def run(s: Schedule) -> RunReport:
        seen.append(s.name)
        return RunReport(0, "ok")

    service = SchedulerService(Racy(), run, clock=clock)  # type: ignore[arg-type]

    assert service.tick() == 0
    assert seen == []


def test_stop_event_ends_a_tick_between_schedules(tmp_path: Path) -> None:
    clock = FakeClock()
    _, _, repo = build_deps(tmp_path, clock=clock)
    stored_schedule(repo, name="a", next_run_at=T0)
    stored_schedule(repo, name="b", next_run_at=T0)
    seen: list[str] = []
    holder: list[SchedulerService] = []

    def run(schedule: Schedule) -> RunReport:
        seen.append(schedule.name)
        holder[0].stop_event.set()  # stop requested while the first run is going
        return RunReport(schedule.id or 0, "ok")

    service = SchedulerService(repo, run, clock=clock, tick_seconds=3600)
    holder.append(service)

    service.tick()

    assert seen == ["a"]
