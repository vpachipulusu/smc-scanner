"""Schedule store: round trip, validation, alert dedupe, shared-file safety, history lookup."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, SqliteAnalysisStore, StoreError
from smc_scanner.schedule.store import (
    MAX_SCHEDULES,
    AlertKey,
    Schedule,
    ScheduleLimitError,
    ScheduleNotFoundError,
    SqliteScheduleRepository,
    previous_action,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def make(**changes: object) -> Schedule:
    base = Schedule(
        name="hourly majors",
        source="demo",
        tf="1h",
        symbols=("EURUSD", "XAUUSD"),
        frequency="1h",
    )
    return Schedule(**{**base.__dict__, **changes})


def repo(tmp_path: Path) -> SqliteScheduleRepository:
    return SqliteScheduleRepository(tmp_path / "smc.db")


def test_round_trip_keeps_every_field(tmp_path: Path) -> None:
    store = repo(tmp_path)
    original = make(
        min_score=3,
        min_confidence=65.5,
        only_on_change=True,
        send_hold=True,
        telegram_chat_id="-100123",
        enabled=False,
        last_run_at=T0,
        next_run_at=T0 + timedelta(hours=1),
    )

    saved = store.add(original)
    loaded = store.get(saved.id or 0)

    assert saved.id is not None
    assert loaded == saved
    assert loaded is not None
    assert loaded.symbols == ("EURUSD", "XAUUSD")
    assert loaded.telegram_chat_id == "-100123"
    assert loaded.next_run_at == T0 + timedelta(hours=1)


def test_list_returns_all_or_only_enabled(tmp_path: Path) -> None:
    store = repo(tmp_path)
    store.add(make(name="on"))
    store.add(make(name="off", enabled=False))

    assert [s.name for s in store.list_schedules()] == ["on", "off"]
    assert [s.name for s in store.list_schedules(enabled_only=True)] == ["on"]


def test_get_missing_returns_none(tmp_path: Path) -> None:
    assert repo(tmp_path).get(99) is None


def test_update_changes_fields_and_keeps_last_run(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make(last_run_at=T0, next_run_at=T0))

    updated = store.update(Schedule(**{**saved.__dict__, "name": "renamed", "min_score": 4}))

    assert updated.name == "renamed"
    assert updated.min_score == 4
    assert updated.last_run_at == T0
    assert updated.next_run_at == T0


def test_update_resets_next_run_when_frequency_or_enabled_changes(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make(next_run_at=T0))

    faster = store.update(Schedule(**{**saved.__dict__, "frequency": "15m"}))
    assert faster.next_run_at is None

    store.mark_run(faster.id or 0, T0, T0 + timedelta(minutes=15))
    paused = store.update(Schedule(**{**faster.__dict__, "enabled": False}))
    assert paused.next_run_at is None


def test_update_unknown_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ScheduleNotFoundError):
        repo(tmp_path).update(make(id=5))


def test_update_needs_an_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="id"):
        repo(tmp_path).update(make())


def test_delete_removes_schedule_and_its_alerts(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make())
    alert = AlertKey(saved.id or 0, "EURUSD", "1h", "OB:1.1:1.2", "2026-03-01T11:00:00+00:00")
    assert store.claim_alert(alert, T0)

    assert store.delete(saved.id or 0)
    assert store.get(saved.id or 0) is None
    assert not store.delete(saved.id or 0)
    other = store.add(make(name="again"))
    assert store.claim_alert(AlertKey(other.id or 0, *alert[1:]), T0)  # table holds nothing stale


def test_mark_run_stores_both_times(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make())

    store.mark_run(saved.id or 0, T0, T0 + timedelta(hours=1))

    loaded = store.get(saved.id or 0)
    assert loaded is not None
    assert (loaded.last_run_at, loaded.next_run_at) == (T0, T0 + timedelta(hours=1))


def test_claim_alert_is_once_per_bar(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make())
    key = AlertKey(saved.id or 0, "EURUSD", "1h", "OB:1.1:1.2", "2026-03-01T11:00:00+00:00")

    assert store.claim_alert(key, T0)
    assert not store.claim_alert(key, T0 + timedelta(hours=1))


def test_claim_alert_distinguishes_bar_zone_symbol_and_schedule(tmp_path: Path) -> None:
    store = repo(tmp_path)
    first = store.add(make(name="a")).id or 0
    second = store.add(make(name="b")).id or 0
    base = AlertKey(first, "EURUSD", "1h", "OB:1.1:1.2", "2026-03-01T11:00:00+00:00")
    variants = [
        base,
        AlertKey(second, *base[1:]),
        AlertKey(first, "XAUUSD", *base[2:]),
        AlertKey(first, base.symbol, base.tf, "FVG:1.1:1.2", base.bar_time),
        AlertKey(first, base.symbol, base.tf, base.zone_key, "2026-03-01T12:00:00+00:00"),
    ]

    assert [store.claim_alert(v, T0) for v in variants] == [True] * len(variants)


def test_release_alert_lets_it_be_claimed_again(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make())
    key = AlertKey(saved.id or 0, "EURUSD", "1h", "OB:1.1:1.2", "2026-03-01T11:00:00+00:00")
    store.claim_alert(key, T0)

    store.release_alert(key)

    assert store.claim_alert(key, T0)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "  "}, "name"),
        ({"frequency": "5m"}, "frequency"),
        ({"tf": "2h"}, "timeframe"),
        ({"source": "csv"}, "source"),
        ({"symbols": ()}, "symbols"),
        ({"symbols": ("EUR USD",)}, "symbol"),
        ({"min_score": -1}, "min_score"),
        ({"min_confidence": 101.0}, "min_confidence"),
        ({"min_confidence": float("nan")}, "min_confidence"),
        ({"last_run_at": datetime(2026, 1, 1)}, "timezone"),
    ],
)
def test_schedule_validates_its_fields(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make(**changes)


def test_sql_metacharacters_are_data(tmp_path: Path) -> None:
    store = repo(tmp_path)
    nasty = "x'); DROP TABLE schedules;--"

    saved = store.add(make(name=nasty))

    assert store.get(saved.id or 0) == saved
    assert len(store.list_schedules()) == 1


def test_database_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteAnalysisStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")

    with pytest.raises(StoreError, match="newer"):
        SqliteScheduleRepository(path)


def test_shares_the_file_with_the_analysis_store_without_disturbing_it(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteAnalysisStore(path)
    SqliteScheduleRepository(path)

    SqliteAnalysisStore(path)  # reopening must not see a "newer" version
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"analyses", "schedules", "sent_alerts"} <= tables


def test_reopening_keeps_data(tmp_path: Path) -> None:
    saved = repo(tmp_path).add(make())

    assert repo(tmp_path).get(saved.id or 0) == saved


def test_unc_and_directory_paths_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        SqliteScheduleRepository("\\\\server\\share\\smc.db")
    with pytest.raises(StoreError):
        SqliteScheduleRepository(tmp_path)


def test_missing_parent_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="directory"):
        SqliteScheduleRepository(tmp_path / "nope" / "smc.db")


def test_corrupt_symbols_json_is_a_store_error_on_get(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    store = SqliteScheduleRepository(path)
    saved = store.add(make())
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schedules SET symbols = 'not json'")

    with pytest.raises(StoreError, match="corrupt"):
        store.get(saved.id or 0)


# --- previous_action: read-only history lookup -------------------------------------


def _analysis(
    path: Path, symbol: str, tf: str, bar_time: str, action: str | None, created: str
) -> None:
    key = AnalysisKey(symbol, tf, "OB", 1.1, 1.2, bar_time)
    verdict = None if action is None else {"action": action, "confidence": 50.0}
    SqliteAnalysisStore(path).save(
        AnalysisRecord(
            key=key,
            created_at=created,
            zone={},
            context=None,
            verdict=verdict,
            provider="fake",
            model="fake",
            prompt_version="1",
            tokens_in=None,
            tokens_out=None,
            cost_estimate=None,
            error=None if verdict else "boom",
        )
    )


def test_previous_action_is_the_latest_verdict_on_an_earlier_bar(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    _analysis(
        path, "EURUSD", "1h", "2026-03-01T09:00:00+00:00", "SELL", "2026-03-01T09:01:00+00:00"
    )
    _analysis(path, "EURUSD", "1h", "2026-03-01T10:00:00+00:00", "BUY", "2026-03-01T10:01:00+00:00")
    _analysis(
        path, "EURUSD", "1h", "2026-03-01T11:00:00+00:00", "HOLD", "2026-03-01T11:01:00+00:00"
    )

    assert previous_action(path, "EURUSD", "1h", "2026-03-01T11:00:00+00:00") == "BUY"


def test_previous_action_ignores_other_symbols_timeframes_and_failures(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    _analysis(
        path, "XAUUSD", "1h", "2026-03-01T09:00:00+00:00", "SELL", "2026-03-01T09:01:00+00:00"
    )
    _analysis(
        path, "EURUSD", "4h", "2026-03-01T09:00:00+00:00", "SELL", "2026-03-01T09:01:00+00:00"
    )
    _analysis(path, "EURUSD", "1h", "2026-03-01T10:00:00+00:00", None, "2026-03-01T10:01:00+00:00")

    assert previous_action(path, "EURUSD", "1h", "2026-03-01T11:00:00+00:00") is None


def test_previous_action_is_none_for_missing_database_or_table(tmp_path: Path) -> None:
    assert (
        previous_action(tmp_path / "absent.db", "EURUSD", "1h", "2026-03-01T11:00:00+00:00") is None
    )
    bare = tmp_path / "bare.db"
    sqlite3.connect(bare).close()

    assert previous_action(bare, "EURUSD", "1h", "2026-03-01T11:00:00+00:00") is None


def test_previous_action_never_writes(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    _analysis(path, "EURUSD", "1h", "2026-03-01T09:00:00+00:00", "BUY", "2026-03-01T09:01:00+00:00")
    before = path.read_bytes()

    previous_action(path, "EURUSD", "1h", "2026-03-01T11:00:00+00:00")

    assert path.read_bytes() == before


def test_set_next_run_leaves_last_run_alone(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make(last_run_at=T0))

    store.set_next_run(saved.id or 0, T0 + timedelta(hours=1))

    loaded = store.get(saved.id or 0)
    assert loaded is not None
    assert (loaded.last_run_at, loaded.next_run_at) == (T0, T0 + timedelta(hours=1))


@pytest.mark.parametrize("chat", ["42", "-1001234567890", "@my_channel"])
def test_valid_chat_ids_are_accepted(chat: str) -> None:
    assert make(telegram_chat_id=chat).telegram_chat_id == chat


@pytest.mark.parametrize(
    "chat",
    [
        "",
        "abc",
        "12 3",
        "-",
        "1" * 21,
        "@ab",
        "@bad name",
        "../x",
        "42\n",
        "https://t.me/x",
        "@" + "a" * 40,
    ],
)
def test_bad_chat_ids_are_rejected(chat: str) -> None:
    with pytest.raises(ValueError, match="telegram_chat_id"):
        make(telegram_chat_id=chat)


def test_symbol_with_trailing_newline_is_rejected() -> None:
    with pytest.raises(ValueError, match="symbol"):
        make(symbols=("EURUSD\n",))


def test_schedule_count_is_capped(tmp_path: Path) -> None:
    store = repo(tmp_path)
    for i in range(MAX_SCHEDULES):
        store.add(make(name=f"s{i}"))

    with pytest.raises(ScheduleLimitError):
        store.add(make(name="one too many"))
    assert len(store.list_schedules()) == MAX_SCHEDULES


def test_unreadable_rows_are_skipped_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    store = SqliteScheduleRepository(path)
    store.add(make(name="good"))
    bad = store.add(make(name="bad"))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schedules SET symbols = 'not json' WHERE id = ?", (bad.id,))

    assert [s.name for s in store.list_schedules()] == ["good"]


def test_mark_run_with_frequency_clears_next_run_if_the_frequency_changed(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make())
    store.update(Schedule(**{**saved.__dict__, "frequency": "4h"}))

    store.mark_run(saved.id or 0, T0, T0 + timedelta(hours=1), frequency="1h")  # stale frequency

    loaded = store.get(saved.id or 0)
    assert loaded is not None
    assert loaded.last_run_at == T0
    assert loaded.next_run_at is None


def test_mark_run_with_matching_frequency_stores_next_run(tmp_path: Path) -> None:
    store = repo(tmp_path)
    saved = store.add(make())

    store.mark_run(saved.id or 0, T0, T0 + timedelta(hours=1), frequency="1h")

    loaded = store.get(saved.id or 0)
    assert loaded is not None and loaded.next_run_at == T0 + timedelta(hours=1)


def test_delete_alerts_older_than_keeps_recent_rows(tmp_path: Path) -> None:
    store = repo(tmp_path)
    sid = store.add(make()).id or 0
    old = AlertKey(sid, "EURUSD", "1h", "OB:1.1:1.2", "2026-03-01T08:00:00+00:00")
    new = AlertKey(sid, "EURUSD", "1h", "OB:1.1:1.2", "2026-03-01T11:00:00+00:00")
    store.claim_alert(old, T0 - timedelta(days=10))
    store.claim_alert(new, T0)

    removed = store.delete_alerts_older_than(T0 - timedelta(days=1))

    assert removed == 1
    assert not store.claim_alert(new, T0)  # still remembered
    assert store.claim_alert(old, T0)  # forgotten, so claimable again
