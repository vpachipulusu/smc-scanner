"""The backtest run store: CRUD, status transitions, retention, filters and the guards."""

import json
import math
import os
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from backtest_job_support import stats

from smc_scanner.ai.store import SCHEMA_VERSION, StoreError
from smc_scanner.backtest import store as store_module
from smc_scanner.backtest.store import (
    MAX_ERROR_CHARS,
    BacktestNotFoundError,
    NewBacktest,
    SqliteBacktestRepository,
    without_signals,
)
from smc_scanner.config import MAX_BARS, MIN_BARS

RULES = {"rr": 2.0, "stop_buffer_atr": 0.0, "time_stop_bars": 50, "spread": 0.0}


class Clock:
    """A clock that moves one second per reading, so rows have distinct times."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "smc.db"


@pytest.fixture
def repo(path: Path) -> SqliteBacktestRepository:
    return SqliteBacktestRepository(path, clock=Clock())


def done(**changes: Any) -> NewBacktest:
    return run(status="done", stats=stats(), verdict="pass", duration_seconds=1.0, **changes)


def run(**changes: Any) -> NewBacktest:
    base: dict[str, Any] = {
        "strategy": "smc-default",
        "source": "demo",
        "timeframe": "1h",
        "bars": 500,
        "symbols": ("EURUSD", "XAUUSD"),
        "rules": RULES,
        "split": "time",
        "train_fraction": 0.7,
        "seed": 3,
        "stride": 2,
    }
    return NewBacktest(**{**base, **changes})


def test_insert_returns_the_pending_row_and_get_reads_it(repo: SqliteBacktestRepository) -> None:
    record = repo.insert(run())

    assert record.id >= 1 and record.status == "pending"
    assert record.symbols == ("EURUSD", "XAUUSD") and record.rules == RULES
    assert record.stats is None and record.verdict is None and record.lookback is None
    assert record.created_at == "2026-10-01T00:00:01+00:00"
    assert repo.get(record.id) == record
    assert repo.get(record.id + 1) is None


def test_lookback_and_long_bars_round_trip(repo: SqliteBacktestRepository) -> None:
    record = repo.insert(done(bars=121_940, lookback=500))

    assert record.lookback == 500 and record.bars == 121_940
    assert repo.get(record.id) == record
    assert repo.list()[0].lookback == 500


@pytest.mark.parametrize("lookback", [0, -1, MIN_BARS - 1, MAX_BARS + 1, True, 2.5])
def test_insert_rejects_a_bad_lookback(repo: SqliteBacktestRepository, lookback: object) -> None:
    with pytest.raises(ValueError, match="lookback"):
        repo.insert(run(lookback=lookback))


def test_status_moves_from_pending_to_running_to_done(repo: SqliteBacktestRepository) -> None:
    record = repo.insert(run())

    repo.mark_running(record.id)
    assert (got := repo.get(record.id)) is not None and got.status == "running"
    repo.finish(record.id, {**stats(), "signals": [{"x": 1}]}, "pass", 12.5)

    done = repo.get(record.id)
    assert done is not None and done.status == "done" and done.verdict == "pass"
    assert done.duration_seconds == 12.5 and done.error is None
    assert done.stats == stats()  # per-signal rows are never stored


def test_a_failed_run_keeps_a_clipped_error_and_its_duration(
    repo: SqliteBacktestRepository,
) -> None:
    record = repo.insert(run())

    repo.fail(record.id, "x" * (MAX_ERROR_CHARS + 50), 3.0)

    failed = repo.get(record.id)
    assert failed is not None and failed.status == "failed"
    assert failed.error == "x" * MAX_ERROR_CHARS and failed.duration_seconds == 3.0


def test_a_finished_run_cannot_change_again(repo: SqliteBacktestRepository) -> None:
    record = repo.insert(run())
    repo.finish(record.id, stats(), None, 1.0)

    with pytest.raises(BacktestNotFoundError):
        repo.fail(record.id, "late", 2.0)
    with pytest.raises(BacktestNotFoundError):
        repo.mark_running(record.id)
    with pytest.raises(BacktestNotFoundError):
        repo.finish(record.id + 1, stats(), None, 1.0)


def test_fail_unfinished_marks_only_pending_and_running_rows(
    repo: SqliteBacktestRepository,
) -> None:
    pending = repo.insert(run())
    running = repo.insert(run())
    repo.mark_running(running.id)
    done = repo.insert(run(status="done", stats=stats(), verdict="fail", duration_seconds=1.0))

    assert repo.fail_unfinished("interrupted") == 2

    statuses = {r.id: (r.status, r.error) for r in repo.list()}
    assert statuses[pending.id] == ("failed", "interrupted")
    assert statuses[running.id] == ("failed", "interrupted")
    assert statuses[done.id] == ("done", None)


def test_list_is_newest_first_and_filters_by_strategy(repo: SqliteBacktestRepository) -> None:
    first = repo.insert(run())
    other = repo.insert(run(strategy="fresh-ob-trend"))
    last = repo.insert(run())

    assert [r.id for r in repo.list()] == [last.id, other.id, first.id]
    assert [r.id for r in repo.list(strategy="smc-default")] == [last.id, first.id]
    assert [r.id for r in repo.list(limit=1)] == [last.id]


def test_list_hides_strategies_that_are_not_visible(repo: SqliteBacktestRepository) -> None:
    kept = repo.insert(run())
    repo.insert(run(strategy="deleted-one"))

    assert [r.id for r in repo.list(visible=["smc-default"])] == [kept.id]
    assert repo.list(strategy="deleted-one", visible=["smc-default"]) == []
    assert repo.list(visible=[]) == []


@pytest.mark.parametrize("limit", [0, store_module.MAX_LIST_LIMIT + 1])
def test_list_limit_is_bounded(repo: SqliteBacktestRepository, limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        repo.list(limit=limit)


def test_latest_done_skips_unfinished_and_failed_rows(repo: SqliteBacktestRepository) -> None:
    assert repo.latest_done("smc-default") is None
    done = repo.insert(run(status="done", stats=stats(), verdict="pass", duration_seconds=1.0))
    repo.insert(run())  # newer but pending
    failed = repo.insert(run())
    repo.fail(failed.id, "x", None)

    latest = repo.latest_done("smc-default")
    assert latest is not None and latest.id == done.id
    assert repo.latest_done("fresh-ob-trend") is None


def test_retention_keeps_the_newest_rows_per_strategy(
    repo: SqliteBacktestRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_ROWS_PER_STRATEGY", 3)
    other = repo.insert(done(strategy="fresh-ob-trend"))
    ids = [repo.insert(done()).id for _ in range(5)]

    assert [r.id for r in repo.list(strategy="smc-default")] == ids[:1:-1]
    assert [r.id for r in repo.list(strategy="fresh-ob-trend")] == [other.id]


def test_retention_never_prunes_an_unfinished_row(
    repo: SqliteBacktestRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_ROWS_PER_STRATEGY", 2)
    running = repo.insert(run())
    repo.mark_running(running.id)
    finished = [repo.insert(done()).id for _ in range(3)]

    kept = [r.id for r in repo.list()]
    assert kept == [*finished[:0:-1], running.id]
    repo.finish(running.id, stats(), "pass", 1.0)  # its result is not lost


def test_retention_orders_by_id_whatever_the_clock_says(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_ROWS_PER_STRATEGY", 2)
    times = iter(datetime(2026, 1, day, tzinfo=UTC) for day in (5, 4, 3))
    repo = SqliteBacktestRepository(path, clock=lambda: next(times))
    first, second = repo.insert(done()), repo.insert(done())

    newest = repo.insert(done())  # its clock stepped back, yet the oldest id goes

    assert {r.id for r in repo.list()} == {second.id, newest.id}
    assert repo.get(first.id) is None


def test_the_total_cap_prunes_the_oldest_finished_rows_of_any_strategy(
    repo: SqliteBacktestRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_ROWS", 2)
    repo.insert(done(strategy="deleted-one"))
    kept = [repo.insert(done(strategy=s)).id for s in ("a-one", "b-two")]

    assert sorted(r.id for r in repo.list()) == kept


def test_latest_done_reads_past_an_unreadable_newest_row(
    path: Path, repo: SqliteBacktestRepository
) -> None:
    good = repo.insert(done())
    bad = repo.insert(done())
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE backtests SET stats = '[]' WHERE id = ?", (bad.id,))

    latest = repo.latest_done("smc-default")

    assert latest is not None and latest.id == good.id


def test_the_store_switches_the_file_to_wal(path: Path) -> None:
    SqliteBacktestRepository(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_the_default_retention_is_two_hundred() -> None:
    assert store_module.MAX_ROWS_PER_STRATEGY == 200


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "lost"}, "status"),
        ({"verdict": "maybe"}, "verdict"),
        ({"train_fraction": math.nan}, "train_fraction"),
        ({"stats": {"n": math.inf}}, "Out of range float"),
    ],
)
def test_insert_rejects_bad_values(
    repo: SqliteBacktestRepository, changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        repo.insert(run(**changes))


def test_stats_over_the_size_cap_are_rejected(
    repo: SqliteBacktestRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_STATS_CHARS", 10)
    record = repo.insert(run())

    with pytest.raises(ValueError, match="exceed"):
        repo.finish(record.id, stats(), "pass", 1.0)


def test_finish_rejects_an_unknown_verdict(repo: SqliteBacktestRepository) -> None:
    record = repo.insert(run())

    with pytest.raises(ValueError, match="verdict"):
        repo.finish(record.id, stats(), "maybe", 1.0)  # type: ignore[arg-type]


def test_without_signals_drops_them_at_any_depth() -> None:
    value = {"signals": [1], "a": [{"signals": 2, "b": 3}], "c": (4, {"signals": 5})}

    assert without_signals(value) == {"a": [{"b": 3}], "c": [4, {}]}


def test_schema_creation_is_idempotent(path: Path) -> None:
    SqliteBacktestRepository(path).insert(run())
    again = SqliteBacktestRepository(path)

    assert len(again.list()) == 1
    with sqlite3.connect(path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert {"backtests", "backtests_strategy_created", "backtests_status"} <= names


def test_a_newer_schema_version_is_refused_and_never_written(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(StoreError, match="newer version"):
        SqliteBacktestRepository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION + 1


def test_the_user_version_is_left_alone(path: Path) -> None:
    SqliteBacktestRepository(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_a_missing_directory_is_a_store_error(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="does not exist"):
        SqliteBacktestRepository(tmp_path / "missing" / "smc.db")


def test_a_network_path_is_refused() -> None:
    with pytest.raises(StoreError, match="UNC"):
        SqliteBacktestRepository("\\\\server\\share\\smc.db")


def test_a_file_that_is_not_a_database_is_a_store_error(path: Path) -> None:
    path.write_bytes(b"not a database at all, just some text" * 50)

    with pytest.raises(StoreError, match="backtest database"):
        SqliteBacktestRepository(path)


@pytest.fixture
def read_only(path: Path) -> Iterator[Path]:
    SqliteBacktestRepository(path)
    os.chmod(path, stat.S_IREAD)
    yield path
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_writes_to_a_read_only_file_are_store_errors(read_only: Path) -> None:
    repo = SqliteBacktestRepository(read_only)

    assert repo.list() == []
    with pytest.raises(StoreError, match="backtest database"):
        repo.insert(run())


def test_a_concurrent_creator_is_tolerated(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = os.open

    def raced(name: Any, flags: int, mode: int = 0o777) -> int:
        real_open(name, flags, mode)
        raise FileExistsError(name)

    monkeypatch.setattr(os, "open", raced)

    SqliteBacktestRepository(path)

    assert path.exists()


def test_an_uncreatable_file_is_a_store_error(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_: object) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "open", denied)

    with pytest.raises(StoreError, match="cannot create"):
        SqliteBacktestRepository(path)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("symbols", "not json"),
        ("symbols", '{"a": 1}'),
        ("rules", "[1, 2]"),
        ("stats", "[]"),
        ("status", "lost"),
        ("verdict", "maybe"),
        ("bars", "many"),
    ],
)
def test_tampered_rows_are_skipped_and_logged(
    path: Path,
    repo: SqliteBacktestRepository,
    column: str,
    value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = repo.insert(run())
    bad = repo.insert(run())
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(f"UPDATE backtests SET {column} = ? WHERE id = ?", (value, bad.id))

    assert [r.id for r in repo.list()] == [good.id]
    assert repo.get(bad.id) is None
    assert "skipping unreadable backtest row" in caplog.text


def test_symbols_and_rules_are_stored_as_json(path: Path, repo: SqliteBacktestRepository) -> None:
    record = repo.insert(run())

    with sqlite3.connect(path) as conn:
        symbols, rules = conn.execute(
            "SELECT symbols, rules FROM backtests WHERE id = ?", (record.id,)
        ).fetchone()
    assert json.loads(symbols) == ["EURUSD", "XAUUSD"]
    assert json.loads(rules) == RULES
