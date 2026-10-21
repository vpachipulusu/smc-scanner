"""SQLite cache and the refresh/stale/unavailable policy, driven by FakeCalendarSource."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from calendar_support import NOW, event

from smc_scanner.ai.store import SCHEMA_VERSION, StoreError
from smc_scanner.econ_calendar.fake import FakeCalendarSource
from smc_scanner.econ_calendar.models import CalendarEvent, CalendarSourceError
from smc_scanner.econ_calendar.service import (
    MAX_STALE,
    REFRESH_INTERVAL,
    RETRY_BACKOFF,
    CalendarService,
)
from smc_scanner.econ_calendar.store import SqliteCalendarStore

H = timedelta(hours=1)


def _store(tmp_path: Path) -> SqliteCalendarStore:
    return SqliteCalendarStore(tmp_path / "smc.db")


# --- store ---------------------------------------------------------------------------------


def test_store_round_trips_events_and_the_fetch_time(tmp_path: Path) -> None:
    store = _store(tmp_path)
    full = CalendarEvent(
        currency="EUR", impact="medium", time=NOW, title="CPI y/y", actual=2.1, forecast=2.0
    )

    store.replace([full, event(H)], NOW)
    stored = store.load()

    assert stored.fetched_at == NOW
    assert sorted(stored.events, key=lambda e: e.time) == [full, event(H)]


def test_store_replace_drops_older_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.replace([event(H), event(2 * H, title="Other")], NOW)

    store.replace([event(3 * H, title="Third")], NOW + H)

    stored = store.load()
    assert [e.title for e in stored.events] == ["Third"]
    assert stored.fetched_at == NOW + H


def test_store_deduplicates_identical_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.replace([event(H), event(H)], NOW)

    assert len(store.load().events) == 1


def test_empty_store_loads_nothing(tmp_path: Path) -> None:
    stored = _store(tmp_path).load()

    assert stored.events == () and stored.fetched_at is None


def test_store_does_not_touch_the_shared_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")

    SqliteCalendarStore(path).replace([event(H)], NOW)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION - 1


def test_store_refuses_a_newer_database(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(StoreError):
        SqliteCalendarStore(path)


def test_store_skips_corrupt_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.replace([event(H)], NOW)
    with sqlite3.connect(tmp_path / "smc.db") as conn:
        conn.execute("UPDATE calendar_events SET impact = 'bogus'")

    assert store.load().events == ()


def test_store_hostile_title_is_stored_as_data(tmp_path: Path) -> None:
    store = _store(tmp_path)
    nasty = "x'); DROP TABLE calendar_events;--"

    store.replace([event(H, title=nasty)], NOW)

    assert [e.title for e in store.load().events] == [nasty]


# --- service -------------------------------------------------------------------------------


def _service(tmp_path: Path, source: FakeCalendarSource) -> CalendarService:
    return CalendarService(source, _store(tmp_path))


def test_first_call_fetches_and_is_fresh(tmp_path: Path) -> None:
    source = FakeCalendarSource([event(H)])

    snapshot = _service(tmp_path, source).snapshot(NOW)

    assert snapshot.status == "fresh" and snapshot.events == (event(H),)
    assert snapshot.fetched_at == NOW
    assert source.calls == 1


def test_cache_is_used_within_the_refresh_interval(tmp_path: Path) -> None:
    source = FakeCalendarSource([event(H)])
    service = _service(tmp_path, source)
    service.snapshot(NOW)

    again = service.snapshot(NOW + REFRESH_INTERVAL - timedelta(seconds=1))

    assert again.status == "fresh" and source.calls == 1


def test_cache_is_shared_through_the_database(tmp_path: Path) -> None:
    first = FakeCalendarSource([event(H)])
    _service(tmp_path, first).snapshot(NOW)
    second = FakeCalendarSource([])

    snapshot = _service(tmp_path, second).snapshot(NOW + H / 2)

    assert snapshot.events == (event(H),) and second.calls == 0


def test_refetches_after_the_interval(tmp_path: Path) -> None:
    source = FakeCalendarSource([event(H)])
    service = _service(tmp_path, source)
    service.snapshot(NOW)

    service.snapshot(NOW + REFRESH_INTERVAL)

    assert source.calls == 2


def test_failure_with_a_cache_is_stale(tmp_path: Path) -> None:
    good = FakeCalendarSource([event(H)])
    _service(tmp_path, good).snapshot(NOW)
    broken = FakeCalendarSource(error=CalendarSourceError("down"))

    snapshot = _service(tmp_path, broken).snapshot(NOW + 2 * H)

    assert snapshot.status == "stale" and snapshot.events == (event(H),)
    assert snapshot.fetched_at == NOW


def test_failure_without_a_cache_is_unavailable(tmp_path: Path) -> None:
    broken = FakeCalendarSource(error=CalendarSourceError("down"))

    snapshot = _service(tmp_path, broken).snapshot(NOW)

    assert snapshot.status == "unavailable" and snapshot.events == ()
    assert snapshot.fetched_at is None


def test_a_cache_older_than_the_stale_limit_is_unavailable(tmp_path: Path) -> None:
    _service(tmp_path, FakeCalendarSource([event(H)])).snapshot(NOW)
    broken = FakeCalendarSource(error=CalendarSourceError("down"))

    snapshot = _service(tmp_path, broken).snapshot(NOW + MAX_STALE + H)

    assert snapshot.status == "unavailable" and snapshot.events == ()


def test_failed_fetches_are_not_retried_inside_the_backoff(tmp_path: Path) -> None:
    broken = FakeCalendarSource(error=CalendarSourceError("down"))
    service = _service(tmp_path, broken)
    service.snapshot(NOW)

    service.snapshot(NOW + RETRY_BACKOFF - timedelta(seconds=1))
    assert broken.calls == 1

    service.snapshot(NOW + RETRY_BACKOFF)
    assert broken.calls == 2


def test_an_unexpected_source_error_is_contained(tmp_path: Path) -> None:
    source = FakeCalendarSource(error=RuntimeError("boom"))

    snapshot = _service(tmp_path, source).snapshot(NOW)

    assert snapshot.status == "unavailable"


def test_a_broken_store_does_not_block_a_fresh_fetch(tmp_path: Path) -> None:
    class BrokenStore:
        def load(self) -> None:
            raise StoreError("unreadable")

        def replace(self, events: object, fetched_at: object) -> None:
            raise StoreError("read-only")

    service = CalendarService(FakeCalendarSource([event(H)]), BrokenStore())  # type: ignore[arg-type]

    snapshot = service.snapshot(NOW)

    assert snapshot.status == "fresh" and snapshot.events == (event(H),)


def test_an_empty_feed_is_still_fresh(tmp_path: Path) -> None:
    snapshot = _service(tmp_path, FakeCalendarSource([])).snapshot(NOW)

    assert snapshot.status == "fresh" and snapshot.events == ()


def test_concurrent_cold_callers_cause_one_fetch(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    source = FakeCalendarSource([event(H)])
    service = _service(tmp_path, source)

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: service.snapshot(NOW), range(8)))

    assert source.calls == 1 and all(r.status == "fresh" for r in results)
