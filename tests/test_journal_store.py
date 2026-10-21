"""Journal store: CRUD, keyset paging, shared-file safety, injection, corrupt rows."""

import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smc_scanner.ai.store import SCHEMA_VERSION, SqliteAnalysisStore, StoreError
from smc_scanner.journal.models import JournalEntryIn, JournalEntryUpdate
from smc_scanner.journal.store import (
    MAX_ENTRIES,
    JournalCursor,
    JournalLimitError,
    JournalNotFoundError,
    SqliteJournalStore,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def make(**changes: Any) -> JournalEntryIn:
    base: dict[str, Any] = {
        "symbol": "EURUSD",
        "timeframe": "1h",
        "side": "long",
        "entry": 1.1,
        "stop": 1.095,
        "opened_at": T0,
    }
    return JournalEntryIn(**{**base, **changes})


@pytest.fixture
def store(tmp_path: Path) -> SqliteJournalStore:
    return SqliteJournalStore(tmp_path / "smc.db")


def test_add_and_get_round_trip(store: SqliteJournalStore) -> None:
    saved = store.add(make(notes="clean sweep", size=0.5, analysis_id=7))
    assert saved.id >= 1 and saved.created_at.tzinfo is not None
    assert store.get(saved.id) == saved
    assert saved.notes == "clean sweep" and saved.analysis_id == 7 and saved.opened_at == T0


def test_get_missing_returns_none(store: SqliteJournalStore) -> None:
    assert store.get(99) is None


def test_non_utc_times_are_stored_as_the_same_instant(store: SqliteJournalStore) -> None:
    local = T0.astimezone(timezone(timedelta(hours=5, minutes=30)))
    saved = store.add(make(opened_at=local))
    assert saved.opened_at == T0


def test_update_merges_and_revalidates(store: SqliteJournalStore) -> None:
    saved = store.add(make())
    closed = store.update(
        saved.id,
        JournalEntryUpdate(exit=1.11, closed_at=T0 + timedelta(hours=3), pnl_currency=12.5),
    )
    assert closed.exit == 1.11 and closed.pnl_currency == 12.5 and closed.entry == 1.1
    assert closed.created_at == saved.created_at
    assert closed.updated_at >= saved.updated_at
    reopened = store.update(
        saved.id, JournalEntryUpdate(exit=None, closed_at=None, pnl_currency=None)
    )
    assert reopened.exit is None and reopened.closed_at is None


def test_update_that_breaks_an_invariant_is_rejected_and_changes_nothing(
    store: SqliteJournalStore,
) -> None:
    saved = store.add(make())
    with pytest.raises(ValidationError):
        store.update(saved.id, JournalEntryUpdate(stop=1.2))
    assert store.get(saved.id) == saved


def test_update_missing_raises(store: SqliteJournalStore) -> None:
    with pytest.raises(JournalNotFoundError):
        store.update(5, JournalEntryUpdate(notes="x"))


def test_delete(store: SqliteJournalStore) -> None:
    saved = store.add(make())
    assert store.delete(saved.id) is True
    assert store.delete(saved.id) is False
    assert store.get(saved.id) is None


def test_list_is_newest_first_and_pages_without_gaps(store: SqliteJournalStore) -> None:
    ids = [store.add(make(opened_at=T0 + timedelta(hours=h))).id for h in (0, 5, 2, 9, 9)]
    # opened_at desc, id desc as the tiebreak
    expected = [ids[4], ids[3], ids[1], ids[2], ids[0]]
    first = store.list_entries(limit=2)
    assert [e.id for e in first.items] == expected[:2] and first.next_cursor is not None
    second = store.list_entries(limit=2, cursor=first.next_cursor)
    assert [e.id for e in second.items] == expected[2:4] and second.next_cursor is not None
    last = store.list_entries(limit=2, cursor=second.next_cursor)
    assert [e.id for e in last.items] == expected[4:] and last.next_cursor is None


def test_list_filters_by_symbol_and_bounds_limit(store: SqliteJournalStore) -> None:
    store.add(make(symbol="EURUSD"))
    store.add(make(symbol="XAUUSD"))
    assert [e.symbol for e in store.list_entries(symbol="XAUUSD").items] == ["XAUUSD"]
    with pytest.raises(ValueError, match="limit"):
        store.list_entries(limit=0)
    assert len(store.list_entries(limit=10_000).items) == 2


def test_closed_entries_are_all_closed_rows_oldest_close_first(store: SqliteJournalStore) -> None:
    store.add(make())  # open
    late = store.add(make(exit=1.12, closed_at=T0 + timedelta(hours=9)))
    early = store.add(make(exit=1.09, closed_at=T0 + timedelta(hours=2)))
    assert [e.id for e in store.closed_entries()] == [early.id, late.id]


def test_sql_text_in_fields_is_data_not_code(store: SqliteJournalStore) -> None:
    saved = store.add(make(notes="x'); DROP TABLE journal_entries; --"))
    assert store.get(saved.id) is not None
    assert store.list_entries(symbol="x' OR '1'='1").items == []


def test_shares_the_analysis_file_without_touching_user_version(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteAnalysisStore(path)
    SqliteJournalStore(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"analyses", "journal_entries"} <= tables
    SqliteJournalStore(path)  # reopening is idempotent


def test_a_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(StoreError, match="newer"):
        SqliteJournalStore(path)


def test_bad_paths_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="does not exist"):
        SqliteJournalStore(tmp_path / "missing" / "smc.db")
    with pytest.raises(StoreError, match="directory"):
        SqliteJournalStore(tmp_path)
    with pytest.raises(StoreError, match="UNC"):
        SqliteJournalStore("\\\\host\\share\\smc.db")


def test_unreadable_rows_are_skipped_in_lists_and_raise_on_get(
    store: SqliteJournalStore, tmp_path: Path
) -> None:
    good = store.add(make())
    bad = store.add(make(exit=1.2, closed_at=T0 + timedelta(hours=1)))
    with closing(sqlite3.connect(tmp_path / "smc.db")) as conn, conn:
        conn.execute("UPDATE journal_entries SET stop = 5.0 WHERE id = ?", (bad.id,))
    assert [e.id for e in store.list_entries().items] == [good.id]
    assert store.closed_entries() == []
    with pytest.raises(StoreError, match="invalid"):
        store.get(bad.id)


def test_corrupt_timestamp_raises_store_error(store: SqliteJournalStore, tmp_path: Path) -> None:
    saved = store.add(make())
    with closing(sqlite3.connect(tmp_path / "smc.db")) as conn, conn:
        conn.execute("UPDATE journal_entries SET opened_at = 'garbage' WHERE id = ?", (saved.id,))
    with pytest.raises(StoreError):
        store.get(saved.id)


def test_add_refuses_past_the_entry_cap(
    store: SqliteJournalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smc_scanner.journal.store.MAX_ENTRIES", 2)
    store.add(make())
    store.add(make())
    with pytest.raises(JournalLimitError):
        store.add(make())
    assert MAX_ENTRIES == 10_000


def test_out_of_range_ids_are_not_found_not_crashes(store: SqliteJournalStore) -> None:
    huge = 2**70
    assert store.get(huge) is None
    assert store.get(0) is None
    assert store.delete(huge) is False
    with pytest.raises(JournalNotFoundError):
        store.update(huge, JournalEntryUpdate(notes="x"))
    with pytest.raises(ValueError, match="cursor"):
        store.list_entries(cursor=JournalCursor(T0, huge))


def test_naive_cursor_is_refused(store: SqliteJournalStore) -> None:
    with pytest.raises(ValueError, match="cursor"):
        store.list_entries(cursor=JournalCursor(datetime(2026, 1, 1), 1))


def test_paging_mixes_whole_second_and_fractional_times(store: SqliteJournalStore) -> None:
    times = [
        T0,
        T0 + timedelta(microseconds=5),
        T0 + timedelta(seconds=1),
        T0 - timedelta(microseconds=1),
    ]
    ids = [store.add(make(opened_at=t)).id for t in times]
    expected = [ids[2], ids[1], ids[0], ids[3]]
    seen: list[int] = []
    cursor = None
    while True:
        page = store.list_entries(limit=1, cursor=cursor)
        seen += [e.id for e in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == expected


def test_symbol_filter_pages_with_a_cursor(store: SqliteJournalStore) -> None:
    for h in range(3):
        store.add(make(symbol="XAUUSD", opened_at=T0 + timedelta(hours=h)))
    store.add(make(symbol="EURUSD", opened_at=T0 + timedelta(hours=1)))
    first = store.list_entries(limit=2, symbol="XAUUSD")
    rest = store.list_entries(limit=2, symbol="XAUUSD", cursor=first.next_cursor)
    assert [e.symbol for e in first.items + rest.items] == ["XAUUSD"] * 3
    assert rest.next_cursor is None


def test_corrupt_timestamp_on_the_page_boundary_ends_paging_without_failing(
    store: SqliteJournalStore, tmp_path: Path
) -> None:
    top = store.add(make(opened_at=T0 + timedelta(hours=2)))
    bad = store.add(make(opened_at=T0 + timedelta(hours=1)))
    store.add(make(opened_at=T0))
    with closing(sqlite3.connect(tmp_path / "smc.db")) as conn, conn:
        conn.execute(
            "UPDATE journal_entries SET opened_at = '2026-03-01T13:00:00.000000+00:00x' "
            "WHERE id = ?",
            (bad.id,),
        )
    page = store.list_entries(limit=2)
    assert [e.id for e in page.items] == [top.id] and page.next_cursor is None


def test_concurrent_patches_to_different_fields_both_survive(store: SqliteJournalStore) -> None:
    saved = store.add(make())
    close = T0 + timedelta(hours=1)
    patches = [JournalEntryUpdate(notes="n"), JournalEntryUpdate(exit=1.2, closed_at=close)]
    threads = [threading.Thread(target=store.update, args=(saved.id, p)) for p in patches]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = store.get(saved.id)
    assert final is not None and final.notes == "n" and final.exit == 1.2


def test_database_rejects_rows_that_skip_validation(
    store: SqliteJournalStore, tmp_path: Path
) -> None:
    sql = (
        "INSERT INTO journal_entries (symbol, timeframe, side, entry, stop, exit, opened_at, "
        "notes, created_at, updated_at) VALUES ('A', '1h', 'long', 1, 0.5, 2, 'x', '', 'x', 'x')"
    )
    # exit set without closed_at
    with (
        closing(sqlite3.connect(tmp_path / "smc.db")) as conn,
        pytest.raises(sqlite3.IntegrityError),
        conn,
    ):
        conn.execute(sql)


def test_open_count_counts_only_entries_without_an_exit(store: SqliteJournalStore) -> None:
    assert store.open_count() == 0
    store.add(make())
    store.add(make())
    store.add(make(exit=1.12, closed_at=T0 + timedelta(hours=1)))
    assert store.open_count() == 2
