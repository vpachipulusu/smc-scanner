import sqlite3
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from schedule_support import T0, TOKEN, build_deps, buy, stored_schedule

from smc_scanner.ai.store import StoreError
from smc_scanner.schedule.joblog import (
    DEFAULT_RETENTION,
    MAX_ERROR_CHARS,
    MAX_LIST_LIMIT,
    JobLogEntry,
    SqliteJobLogStore,
    entry_from_report,
)
from smc_scanner.schedule.runner import RunDeps, RunReport, run_schedule
from smc_scanner.schedule.store import Schedule

START = T0
END = T0 + timedelta(seconds=2, milliseconds=500)


def _store(tmp_path: Path, retention: int = DEFAULT_RETENTION) -> SqliteJobLogStore:
    return SqliteJobLogStore(tmp_path / "smc.db", retention=retention)


def _entry(schedule_id: int = 1, offset: int = 0, **changes: object) -> JobLogEntry:
    base = {
        "schedule_id": schedule_id,
        "started_at": START + timedelta(minutes=offset),
        "finished_at": END + timedelta(minutes=offset),
        "status": "success",
    }
    return JobLogEntry(**{**base, **changes})  # type: ignore[arg-type]


def test_report_maps_to_a_success_entry() -> None:
    report = RunReport(7, "ok", rows=3, delivered=2, skipped=(("GBPUSD", "hold"),))

    entry = entry_from_report(report, START, END)

    assert (entry.schedule_id, entry.status, entry.hits, entry.delivered) == (7, "success", 3, 2)
    assert entry.skipped == 1
    assert entry.skip_reason is None
    assert entry.error is None
    assert entry.duration_ms == 2500


@pytest.mark.parametrize("status", ["busy", "already_running", "stopped"])
def test_postponed_runs_are_skipped_entries_with_a_reason(status: str) -> None:
    entry = entry_from_report(RunReport(1, status), START, END)  # type: ignore[arg-type]

    assert (entry.status, entry.skip_reason) == ("skipped", status)


def _stored_error(tmp_path: Path, *errors: str, status: str = "failed") -> str | None:
    store = _store(tmp_path)
    store.record_run(RunReport(1, status, errors=errors), START, END)  # type: ignore[arg-type]
    return store.list_entries()[0].error


def test_failed_report_keeps_a_bounded_single_line_error(tmp_path: Path) -> None:
    error = _stored_error(tmp_path, "RuntimeError: " + "x y " * 2000, "line1\nline2\x00")

    assert error is not None
    assert len(error) <= MAX_ERROR_CHARS
    assert "\n" not in error and "\x00" not in error


def test_ok_run_with_send_errors_keeps_them(tmp_path: Path) -> None:
    entry = entry_from_report(
        RunReport(1, "ok", errors=("EURUSD: send failed (boom)",)), START, END
    )

    assert entry.status == "success"
    assert _stored_error(tmp_path, "EURUSD: send failed (boom)", status="ok") == (
        "EURUSD: send failed (boom)"
    )


def test_telegram_token_shapes_are_redacted(tmp_path: Path) -> None:
    error = _stored_error(tmp_path, f"HTTPError: bad url bot{TOKEN}/sendMessage")

    assert error is not None
    assert TOKEN not in error
    assert "[redacted]" in error


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnop",
        "AIzaSyA1234567890abcdefghij",
        "Bearer abc.def",
        "https://host/path?x=1",
        "key=hunter2",
        "A" * 30,
        r"C:\Users\bob\smc.db",
        "/home/bob/app/smc.db",
    ],
)
def test_other_secret_and_path_shapes_are_redacted(tmp_path: Path, secret: str) -> None:
    error = _stored_error(tmp_path, f"HTTPError: {secret}\u202e tail")

    assert error is not None
    assert secret not in error and "bob" not in error and "hunter2" not in error
    assert "\u202e" not in error
    assert "tail" in error


@pytest.mark.parametrize("splitter", ["\u200b", "\u202e", "\x00", "\ufeff", "\x01"])
def test_a_control_char_inside_a_token_does_not_evade_redaction(
    tmp_path: Path, splitter: str
) -> None:
    token = f"123456:ABC{splitter}-def_ghi"
    key = f"sk-ant-api03-abcdef{splitter}ghijklmnop"

    error = _stored_error(tmp_path, f"x {token} y {key}")

    assert error == "x [redacted] y [redacted]"


def test_skipped_rows_have_their_own_lower_cap(tmp_path: Path) -> None:
    store = SqliteJobLogStore(tmp_path / "smc.db", retention=10, skipped_retention=2)
    for i in range(3):
        store.record(_entry(1, i, status="success"))
    for i in range(5):
        store.record(_entry(1, 10 + i, status="skipped", skip_reason="busy"))

    rows = store.list_entries(schedule_id=1)

    assert sorted(e.status for e in rows) == ["skipped", "skipped", "success", "success", "success"]
    assert SqliteJobLogStore(tmp_path / "smc.db", retention=10, skipped_retention=1).prune() == 0
    assert len(store.list_entries(schedule_id=1)) == 4


def test_prune_schedule_deletes_one_schedules_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_entry(1))
    store.record(_entry(2))

    assert store.prune_schedule(1) == 1
    assert [e.schedule_id for e in store.list_entries()] == [2]


def test_negative_counts_are_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        _entry(hits=-1)


def test_database_check_rejects_unknown_status(tmp_path: Path) -> None:
    _store(tmp_path)

    with (
        sqlite3.connect(tmp_path / "smc.db") as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            "INSERT INTO job_logs (schedule_id, started_at, finished_at, duration_ms, status,"
            " hits, delivered, skipped) VALUES (1, 'a', 'b', 0, 'weird', 0, 0, 0)"
        )


def test_prune_drops_rows_of_deleted_schedules(tmp_path: Path) -> None:
    _, _, repo = build_deps(tmp_path)
    kept = stored_schedule(repo)
    gone = stored_schedule(repo)
    store = _store(tmp_path)
    store.record(_entry(kept.id or 0))
    store.record(_entry(gone.id or 0))
    repo.delete(gone.id or 0)

    assert store.prune() == 1
    assert [e.schedule_id for e in store.list_entries()] == [kept.id]


def test_naive_stored_timestamp_is_a_store_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_entry())
    with sqlite3.connect(tmp_path / "smc.db") as conn:
        conn.execute("UPDATE job_logs SET started_at = '2026-01-01T00:00:00'")

    with pytest.raises(StoreError, match="corrupt"):
        store.list_entries()


def test_record_and_list_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_entry(hits=4, delivered=1, skipped=2, error="boom"))

    [row] = store.list_entries()

    assert row.id is not None
    assert (row.schedule_id, row.status) == (1, "success")
    assert (row.hits, row.delivered, row.skipped) == (4, 1, 2)
    assert row.started_at == START and row.finished_at == END
    assert row.error == "boom"


def test_list_is_newest_first_filtered_and_keyset_paged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for i in range(5):
        store.record(_entry(1, i))
    store.record(_entry(2, 9))

    first = store.list_entries(schedule_id=1, limit=2)
    second = store.list_entries(schedule_id=1, limit=2, before_id=first[-1].id)
    last = store.list_entries(schedule_id=1, limit=2, before_id=second[-1].id)

    assert [e.started_at for e in first] == [START + timedelta(minutes=m) for m in (4, 3)]
    assert [e.started_at for e in second] == [START + timedelta(minutes=m) for m in (2, 1)]
    assert [e.started_at for e in last] == [START]
    assert len(store.list_entries()) == 6


def test_list_limit_is_bounded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_entry())

    assert len(store.list_entries(limit=MAX_LIST_LIMIT * 10)) == 1
    with pytest.raises(ValueError, match="limit"):
        store.list_entries(limit=0)


def test_record_prunes_each_schedule_to_the_retention(tmp_path: Path) -> None:
    store = _store(tmp_path, retention=3)
    for i in range(6):
        store.record(_entry(1, i))
    store.record(_entry(2, 0))

    kept = store.list_entries(schedule_id=1, limit=50)

    assert [e.started_at for e in kept] == [START + timedelta(minutes=m) for m in (5, 4, 3)]
    assert len(store.list_entries(schedule_id=2)) == 1


def test_startup_prune_trims_an_oversized_table(tmp_path: Path) -> None:
    big = _store(tmp_path, retention=10)
    for i in range(8):
        big.record(_entry(1, i))

    small = _store(tmp_path, retention=2)

    assert len(small.list_entries(schedule_id=1)) == 2
    assert small.prune() == 0


def test_retention_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retention"):
        _store(tmp_path, retention=0)


def test_sql_is_parameterised(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_entry(error="x'); DROP TABLE job_logs;--"))

    [row] = store.list_entries()

    assert row.error == "x'); DROP TABLE job_logs;--"


def test_database_uses_wal_and_a_private_file(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteJobLogStore(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_sqlite_errors_become_store_errors(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(tmp_path / "smc.db") as conn:
        conn.execute("DROP TABLE job_logs")

    with pytest.raises(StoreError):
        store.record(_entry())
    with pytest.raises(StoreError):
        store.list_entries()


def test_missing_directory_and_newer_schema_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="directory"):
        SqliteJobLogStore(tmp_path / "nope" / "smc.db")
    path = tmp_path / "new.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 999")
    with pytest.raises(StoreError, match="newer"):
        SqliteJobLogStore(path)


def test_corrupt_timestamp_is_a_store_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_entry())
    with sqlite3.connect(tmp_path / "smc.db") as conn:
        conn.execute("UPDATE job_logs SET started_at = 'garbage'")

    with pytest.raises(StoreError, match="corrupt"):
        store.list_entries()


def test_entry_needs_aware_times() -> None:
    with pytest.raises(ValueError, match="timezone"):
        JobLogEntry(1, datetime(2026, 1, 1), END, "success")


# --- recording from the runner -------------------------------------------------------------


def _recording(deps: RunDeps, store: SqliteJobLogStore) -> RunDeps:
    return replace(deps, record=store.record_run)


def test_each_run_records_exactly_one_row(tmp_path: Path) -> None:
    deps, _, repo = build_deps(tmp_path, verdicts={"EURUSD": buy()})
    store = _store(tmp_path)
    schedule = stored_schedule(repo)

    report = run_schedule(schedule, _recording(deps, store))

    [row] = store.list_entries()
    assert (row.schedule_id, row.status) == (schedule.id, "success")
    assert (row.hits, row.delivered) == (report.rows, report.delivered)
    assert row.started_at.tzinfo is UTC


def test_failed_and_postponed_runs_are_recorded_too(tmp_path: Path) -> None:
    deps, _, repo = build_deps(tmp_path, scan_error=RuntimeError("no data"))
    store = _store(tmp_path)
    deps = _recording(deps, store)
    schedule = stored_schedule(repo)
    run_schedule(schedule, deps)
    assert deps.guard.try_enter(schedule.id or 0)
    run_schedule(schedule, deps)  # overlapping run

    statuses = [(e.status, e.skip_reason) for e in store.list_entries()]

    assert statuses == [("skipped", "already_running"), ("failed", None)]


def test_a_raising_recorder_never_breaks_the_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    deps, _, repo = build_deps(tmp_path)

    def boom(report: RunReport, started: datetime, finished: datetime) -> None:
        raise RuntimeError(f"secret {TOKEN}")

    caplog.set_level("ERROR")

    report = run_schedule(stored_schedule(repo), replace(deps, record=boom))

    assert report.status == "ok"
    assert "RuntimeError" in caplog.text
    assert TOKEN not in caplog.text


def test_run_deps_repr_hides_the_telegram_token(tmp_path: Path) -> None:
    deps, _, _ = build_deps(tmp_path)

    assert TOKEN not in repr(deps)
    assert TOKEN not in str(deps)


def test_default_recorder_is_a_no_op(tmp_path: Path) -> None:
    deps, _, repo = build_deps(tmp_path)

    assert run_schedule(stored_schedule(repo), deps).status == "ok"


def test_run_without_an_id_records_nothing(tmp_path: Path) -> None:
    deps, _, _ = build_deps(tmp_path)
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        run_schedule(Schedule("s", "demo", "1h", ("EURUSD",), "1h"), _recording(deps, store))

    assert store.list_entries() == []
