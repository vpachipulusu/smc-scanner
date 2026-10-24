"""Strategy store: round trip, ordering, the cap, conflicts, bad rows and shared-file safety."""

import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from smc_scanner.ai.store import SCHEMA_VERSION, SqliteAnalysisStore, StoreError
from smc_scanner.schedule.store import SqliteScheduleRepository
from smc_scanner.strategy.models import ConditionRef, Strategy
from smc_scanner.strategy.store import (
    MAX_STRATEGIES,
    SqliteStrategyRepository,
    StrategyConflictError,
    StrategyLimitError,
    StrategyNotFoundError,
    StrategyRepository,
    non_builtin,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def make(slug: str = "ob-pullback", **changes: Any) -> Strategy:
    fields: dict[str, Any] = {
        "slug": slug,
        "name": "OB pullback",
        "description": "Order blocks, aligned with bias.",
        "zone_kinds": ("OB",),
        "swing_length": 10,
        "near_atr": 0.5,
        "require": (ConditionRef(key="fresh"),),
        "score": (ConditionRef(key="ote", params={"level": 0.62, "side": "auto"}),),
        "min_score": 1,
        "statuses": ("TOUCHING", "NEAR"),
    }
    return Strategy(**{**fields, **changes})


class Clock:
    """A settable clock so timestamps are deterministic."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "smc.db"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(db_path: Path, clock: Clock) -> SqliteStrategyRepository:
    return SqliteStrategyRepository(db_path, clock=clock)


@contextmanager
def raw(path: Path) -> Iterator[sqlite3.Connection]:
    """A direct connection that commits and is closed (``with connect()`` alone never closes)."""
    with closing(sqlite3.connect(path)) as conn, conn:
        yield conn


def raw_rows(path: Path) -> list[tuple[Any, ...]]:
    with raw(path) as conn:
        return conn.execute(
            "SELECT slug, definition, created_at, updated_at FROM strategies ORDER BY slug"
        ).fetchall()


def insert_raw(path: Path, slug: str, definition: str) -> None:
    with raw(path) as conn:
        conn.execute(
            "INSERT INTO strategies (slug, definition, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (slug, definition, T0.isoformat(), T0.isoformat()),
        )


def user_version(path: Path) -> int:
    with raw(path) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def test_sqlite_repository_satisfies_the_protocol(store: SqliteStrategyRepository) -> None:
    repository: StrategyRepository = store

    assert repository.list() == ()


def test_round_trip_keeps_every_field(store: SqliteStrategyRepository) -> None:
    original = make(mtf=True, require_htf_aligned=True, zone_kinds=("OB", "FVG"))

    created = store.create(original)

    assert created == original
    assert store.get("ob-pullback") == original
    assert store.list() == (original,)


def test_definition_column_holds_the_model_json(
    store: SqliteStrategyRepository, db_path: Path
) -> None:
    store.create(make())

    (slug, definition, created_at, updated_at) = raw_rows(db_path)[0]

    assert slug == "ob-pullback"
    assert definition == make().model_dump_json()
    assert created_at == updated_at == T0.isoformat()


def test_create_and_update_store_builtin_false(
    store: SqliteStrategyRepository, db_path: Path
) -> None:
    created = store.create(make(builtin=True))
    updated = store.update(make(builtin=True, name="Renamed"))

    assert created.builtin is False
    assert updated.builtin is False
    assert store.get("ob-pullback").builtin is False
    assert json.loads(raw_rows(db_path)[0][1])["builtin"] is False


def test_non_builtin_returns_a_validated_copy() -> None:
    original = make(builtin=True)

    copy = non_builtin(original)

    assert copy.builtin is False
    assert original.builtin is True
    assert copy == make()


def test_list_is_ordered_by_slug(store: SqliteStrategyRepository) -> None:
    for slug in ("zeta", "alpha", "mid-1", "mid"):
        store.create(make(slug))

    assert [s.slug for s in store.list()] == ["alpha", "mid", "mid-1", "zeta"]


def test_get_unknown_slug_raises(store: SqliteStrategyRepository) -> None:
    with pytest.raises(StrategyNotFoundError):
        store.get("missing")


def test_duplicate_slug_is_a_conflict_and_keeps_the_original(
    store: SqliteStrategyRepository,
) -> None:
    store.create(make(name="First"))

    with pytest.raises(StrategyConflictError):
        store.create(make(name="Second"))
    assert store.get("ob-pullback").name == "First"


def test_strategy_count_is_capped_at_exactly_the_limit(store: SqliteStrategyRepository) -> None:
    for i in range(MAX_STRATEGIES):
        store.create(make(f"s{i:02d}"))

    with pytest.raises(StrategyLimitError):
        store.create(make("one-too-many"))
    assert len(store.list()) == MAX_STRATEGIES == 50

    store.delete("s00")
    store.create(make("fits-again"))
    assert len(store.list()) == MAX_STRATEGIES


def test_conflict_wins_over_the_limit_when_full(store: SqliteStrategyRepository) -> None:
    for i in range(MAX_STRATEGIES):
        store.create(make(f"s{i:02d}"))

    with pytest.raises(StrategyConflictError):
        store.create(make("s00"))


def test_update_replaces_definition_and_bumps_updated_at(
    store: SqliteStrategyRepository, db_path: Path, clock: Clock
) -> None:
    store.create(make())
    clock.now = T0 + timedelta(hours=2)

    updated = store.update(make(name="Renamed", min_score=0))

    assert updated == make(name="Renamed", min_score=0)
    assert store.get("ob-pullback") == updated
    (_, _, created_at, updated_at) = raw_rows(db_path)[0]
    assert created_at == T0.isoformat()
    assert updated_at == (T0 + timedelta(hours=2)).isoformat()


def test_update_unknown_slug_raises(store: SqliteStrategyRepository) -> None:
    with pytest.raises(StrategyNotFoundError):
        store.update(make("missing"))


def test_delete_removes_the_row(store: SqliteStrategyRepository) -> None:
    store.create(make("keep"))
    store.create(make("drop"))

    store.delete("drop")

    assert [s.slug for s in store.list()] == ["keep"]
    with pytest.raises(StrategyNotFoundError):
        store.get("drop")


def test_delete_unknown_slug_raises(store: SqliteStrategyRepository) -> None:
    with pytest.raises(StrategyNotFoundError):
        store.delete("missing")


def test_invalid_rows_are_skipped_and_logged_without_their_input(
    store: SqliteStrategyRepository, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store.create(make("good"))
    bad = make("bad").model_dump(mode="json")
    insert_raw(db_path, "bad", json.dumps({**bad, "zone_kinds": ["SECRET-INPUT"]}))
    insert_raw(db_path, "broken", "not json SECRET-INPUT")

    with caplog.at_level(logging.ERROR, logger="smc_scanner.strategy.store"):
        listed = store.list()

    assert [s.slug for s in listed] == ["good"]
    assert "'bad'" in caplog.text
    assert "'broken'" in caplog.text
    assert "SECRET-INPUT" not in caplog.text


def test_get_on_an_invalid_row_is_not_found_and_logged(
    store: SqliteStrategyRepository, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    insert_raw(db_path, "bad", "{}")

    with (
        caplog.at_level(logging.ERROR, logger="smc_scanner.strategy.store"),
        pytest.raises(StrategyNotFoundError),
    ):
        store.get("bad")
    assert "'bad'" in caplog.text


def test_rows_whose_definition_disagrees_with_the_row_are_skipped(
    store: SqliteStrategyRepository, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    insert_raw(db_path, "renamed", make("other").model_dump_json())
    insert_raw(db_path, "fake-builtin", make("fake-builtin", builtin=True).model_dump_json())

    with caplog.at_level(logging.ERROR, logger="smc_scanner.strategy.store"):
        assert store.list() == ()
    assert "'renamed'" in caplog.text
    assert "'fake-builtin'" in caplog.text


def test_invalid_rows_can_still_be_deleted_or_overwritten(
    store: SqliteStrategyRepository, db_path: Path
) -> None:
    insert_raw(db_path, "bad", "{}")
    insert_raw(db_path, "worse", "{}")

    store.update(make("bad"))
    store.delete("worse")

    assert store.list() == (make("bad"),)


def test_sql_metacharacters_are_data(store: SqliteStrategyRepository) -> None:
    sneaky = make(name="Bob's (OB) -- drop", description="x' OR '1' / '1 -- & ('a')")

    store.create(sneaky)

    assert store.get("ob-pullback") == sneaky


def test_database_from_a_newer_version_is_refused(db_path: Path) -> None:
    SqliteAnalysisStore(db_path)
    with raw(db_path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(StoreError, match="newer"):
        SqliteStrategyRepository(db_path)


def test_user_version_is_never_written(db_path: Path) -> None:
    SqliteStrategyRepository(db_path).create(make())
    assert user_version(db_path) == 0

    SqliteAnalysisStore(db_path)  # sets the shared counter
    SqliteStrategyRepository(db_path).delete("ob-pullback")
    assert user_version(db_path) == SCHEMA_VERSION


def test_reopening_is_idempotent_and_keeps_data(db_path: Path) -> None:
    SqliteStrategyRepository(db_path).create(make())

    reopened = SqliteStrategyRepository(db_path)
    SqliteStrategyRepository(db_path)

    assert reopened.list() == (make(),)


def test_shares_the_file_with_the_other_stores(db_path: Path) -> None:
    SqliteAnalysisStore(db_path)
    SqliteScheduleRepository(db_path)
    SqliteStrategyRepository(db_path).create(make())

    SqliteAnalysisStore(db_path)  # reopening must not see a "newer" version
    SqliteScheduleRepository(db_path)
    with raw(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"analyses", "schedules", "strategies"} <= tables


def run_together(count: int, action: Callable[[int], object]) -> list[str]:
    """Run ``action(i)`` on ``count`` threads at once; each outcome is "ok" or the error name."""
    barrier = threading.Barrier(count)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        barrier.wait()
        try:
            action(i)
            outcome = "ok"
        except Exception as exc:  # recorded, so an unexpected error fails the assertions
            outcome = type(exc).__name__
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_concurrent_creates_never_exceed_the_cap(db_path: Path) -> None:
    store = SqliteStrategyRepository(db_path)
    threads_count = MAX_STRATEGIES + 15

    outcomes = run_together(threads_count, lambda i: store.create(make(f"t{i:02d}")))

    assert sorted(set(outcomes)) == ["StrategyLimitError", "ok"]
    assert outcomes.count("ok") == MAX_STRATEGIES
    assert len(raw_rows(db_path)) == MAX_STRATEGIES


def test_concurrent_creates_of_one_slug_store_it_once(db_path: Path) -> None:
    store = SqliteStrategyRepository(db_path)

    outcomes = run_together(10, lambda i: store.create(make(name=f"Copy {i}")))

    assert outcomes.count("ok") == 1
    assert outcomes.count("StrategyConflictError") == 9
    assert len(raw_rows(db_path)) == 1


def test_a_held_write_lock_is_a_store_error_and_leaves_nothing_behind(
    store: SqliteStrategyRepository, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.create(make("existing"))
    monkeypatch.setattr("smc_scanner.strategy.store.BUSY_TIMEOUT_SECONDS", 0.05)

    with closing(sqlite3.connect(db_path, isolation_level=None)) as other:
        other.execute("BEGIN IMMEDIATE")
        for attempt in (
            lambda: store.create(make("new")),
            lambda: store.update(make("existing", name="Changed")),
            lambda: store.delete("existing"),
        ):
            with pytest.raises(StoreError, match="locked"):
                attempt()
        other.execute("ROLLBACK")

    assert store.list() == (make("existing"),)
    store.create(make("new"))
    assert len(raw_rows(db_path)) == 2


def test_a_null_slug_is_refused_by_the_schema(
    store: SqliteStrategyRepository, db_path: Path
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        insert_raw(db_path, None, make().model_dump_json())  # type: ignore[arg-type]


def test_not_found_echoes_only_well_formed_slugs(store: SqliteStrategyRepository) -> None:
    with pytest.raises(StrategyNotFoundError, match="'missing'"):
        store.get("missing")
    with pytest.raises(StrategyNotFoundError) as caught:
        store.delete("BAD\nSLUG" * 100)
    assert "BAD" not in str(caught.value)


def test_losing_the_file_creation_race_is_not_an_error(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def created_elsewhere(*_args: object) -> int:
        raise FileExistsError("exists")

    monkeypatch.setattr("smc_scanner.strategy.store.os.open", created_elsewhere)

    SqliteStrategyRepository(db_path).create(make())

    assert len(raw_rows(db_path)) == 1


def test_unc_and_directory_paths_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        SqliteStrategyRepository("\\\\server\\share\\smc.db")
    with pytest.raises(StoreError):
        SqliteStrategyRepository(tmp_path)


def test_missing_parent_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="directory"):
        SqliteStrategyRepository(tmp_path / "nope" / "smc.db")


def test_a_file_that_is_not_a_database_is_a_store_error(db_path: Path) -> None:
    db_path.write_bytes(b"definitely not sqlite" * 100)

    with pytest.raises(StoreError, match="strategy database"):
        SqliteStrategyRepository(db_path)


def test_file_creation_failure_is_a_store_error(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr("smc_scanner.strategy.store.os.open", refuse)

    with pytest.raises(StoreError, match="cannot create"):
        SqliteStrategyRepository(db_path)


def test_errors_are_store_errors() -> None:
    for error in (StrategyNotFoundError, StrategyConflictError, StrategyLimitError):
        assert issubclass(error, StoreError)
