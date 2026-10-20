"""SQLite analysis store: schema, round trip, uniqueness, env path handling, injection safety."""

import logging
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from smc_scanner.ai.store import (
    DB_PATH_ENV,
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    AnalysisKey,
    AnalysisRecord,
    AnalysisStore,
    SqliteAnalysisStore,
    StoreError,
    db_path_from_env,
)

BASE_KEY = AnalysisKey("EURUSD", "1h", "FVG", 1.0812, 1.0825, "2026-01-02 10:00:00")
BASE_RECORD = AnalysisRecord(
    key=BASE_KEY,
    created_at="2026-01-02T10:00:05+00:00",
    zone={"label": "bull FVG"},
    context={"symbol": "EURUSD"},
    verdict={"action": "HOLD", "confidence": 40.0},
    provider="fake",
    model="fake-1",
    prompt_version="smc-verdict-1",
    tokens_in=120,
    tokens_out=30,
    cost_estimate=0.0012,
    error=None,
)
UNC_PATH = chr(92) * 2 + "host" + chr(92) + "share" + chr(92) + "smc.db"
FAILURE = replace(BASE_RECORD, verdict=None, context=None, error="AiError: boom", tokens_in=None)


def _key(**overrides: Any) -> AnalysisKey:
    return replace(BASE_KEY, **overrides)


def _record(key: AnalysisKey | None = None, **overrides: Any) -> AnalysisRecord:
    return replace(BASE_RECORD, key=key or BASE_KEY, **overrides)


@pytest.fixture
def store(tmp_path: Path) -> SqliteAnalysisStore:
    return SqliteAnalysisStore(tmp_path / "smc.db")


def test_round_trip_preserves_every_field(store: SqliteAnalysisStore) -> None:
    store.save(_record())

    got = store.get(_key())

    assert got is not None
    assert got.id is not None
    assert got.key == _key()
    assert got.verdict == {"action": "HOLD", "confidence": 40.0}
    assert got.zone == {"label": "bull FVG"}
    assert got.context == {"symbol": "EURUSD"}
    assert (got.provider, got.model, got.prompt_version) == ("fake", "fake-1", "smc-verdict-1")
    assert (got.tokens_in, got.tokens_out, got.cost_estimate) == (120, 30, 0.0012)
    assert got.error is None
    assert got.attempts == 1
    assert got.created_at == "2026-01-02T10:00:05+00:00"


def test_get_returns_none_for_unknown_key(store: SqliteAnalysisStore) -> None:
    assert store.get(_key(symbol="GBPUSD")) is None


def test_failure_record_round_trips_with_null_verdict(store: SqliteAnalysisStore) -> None:
    store.save(FAILURE)

    got = store.get(_key())

    assert got is not None
    assert got.verdict is None
    assert got.context is None
    assert got.error == "AiError: boom"
    assert got.tokens_in is None


def test_success_replaces_a_stored_failure_and_counts_attempts(
    store: SqliteAnalysisStore,
) -> None:
    store.save(FAILURE)
    store.save(FAILURE)
    store.save(_record())

    got = store.get(_key())

    assert got is not None
    assert got.error is None
    assert got.attempts == 3
    assert len(store.list_recent(10)) == 1


def test_failure_never_overwrites_a_stored_success(store: SqliteAnalysisStore) -> None:
    store.save(_record())

    store.save(FAILURE)

    got = store.get(_key())
    assert got is not None
    assert got.error is None
    assert got.verdict == {"action": "HOLD", "confidence": 40.0}
    assert got.attempts == 1


def test_second_success_is_kept_out_unless_overwrite(store: SqliteAnalysisStore) -> None:
    store.save(_record())
    newer = _record(model="fake-2", verdict={"action": "HOLD", "confidence": 10.0})

    store.save(newer)
    kept = store.get(_key())
    store.save(newer, overwrite=True)
    replaced = store.get(_key())

    assert kept is not None and kept.model == "fake-1"
    assert replaced is not None and replaced.model == "fake-2"


def test_key_distinguishes_every_component(store: SqliteAnalysisStore) -> None:
    variants = [
        _key(),
        _key(symbol="GBPUSD"),
        _key(tf="4h"),
        _key(zone_kind="OB"),
        _key(zone_low=1.08),
        _key(zone_high=1.09),
        _key(bar_time="2026-01-02 11:00:00"),
    ]
    for key in variants:
        store.save(_record(key))

    assert len(store.list_recent(50)) == len(variants)


def test_key_absorbs_float_noise() -> None:
    assert _key(zone_low=0.1 + 0.2) == _key(zone_low=0.3)


def test_key_canonicalises_bar_time_to_utc() -> None:
    naive = _key(bar_time="2026-01-02 10:00:00")
    zulu = _key(bar_time="2026-01-02T10:00:00Z")
    offset = _key(bar_time="2026-01-02T12:00:00+02:00")

    assert naive == zulu == offset
    assert naive.bar_time == "2026-01-02T10:00:00+00:00"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_key_rejects_non_finite_bounds(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _key(zone_high=bad)


def test_key_rejects_unparseable_bar_time() -> None:
    with pytest.raises(ValueError, match="bar_time"):
        _key(bar_time="yesterday-ish")


def test_list_recent_newest_first_and_limited(store: SqliteAnalysisStore) -> None:
    for i in range(5):
        store.save(_record(_key(symbol=f"S{i}"), created_at=f"2026-01-02T10:00:0{i}+00:00"))

    recent = store.list_recent(3)

    assert [r.key.symbol for r in recent] == ["S4", "S3", "S2"]


def test_list_recent_rejects_non_positive_limit(store: SqliteAnalysisStore) -> None:
    with pytest.raises(ValueError, match="limit"):
        store.list_recent(0)


def test_hostile_text_is_stored_verbatim_not_executed(store: SqliteAnalysisStore) -> None:
    evil = "x'); DROP TABLE analyses; --"
    store.save(_record(_key(symbol=evil), error=evil, model=evil))

    got = store.get(_key(symbol=evil))

    assert got is not None
    assert got.error == evil
    assert got.model == evil
    assert len(store.list_recent(10)) == 1


def test_data_persists_across_store_instances(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteAnalysisStore(path).save(_record())

    assert SqliteAnalysisStore(path).get(_key()) is not None


def test_schema_has_expected_columns_unique_index_wal_and_version(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteAnalysisStore(path)
    conn = sqlite3.connect(path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(analyses)")}
        unique = [row for row in conn.execute("PRAGMA index_list(analyses)") if row[2]]
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    assert {"id", "created_at", "symbol", "tf", "zone_kind", "zone_low", "zone_high"} <= columns
    assert {"bar_time", "zone", "context", "verdict", "provider", "model", "attempts"} <= columns
    assert {"prompt_version", "tokens_in", "tokens_out", "cost_estimate", "error"} <= columns
    assert unique
    assert mode == "wal"
    assert version == SCHEMA_VERSION


def test_old_database_without_attempts_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE analyses (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,"
        " symbol TEXT NOT NULL, tf TEXT NOT NULL, zone_kind TEXT NOT NULL,"
        " zone_low REAL NOT NULL, zone_high REAL NOT NULL, bar_time TEXT NOT NULL,"
        " zone TEXT NOT NULL, context TEXT, verdict TEXT, provider TEXT NOT NULL,"
        " model TEXT NOT NULL, prompt_version TEXT NOT NULL, tokens_in INTEGER,"
        " tokens_out INTEGER, cost_estimate REAL, error TEXT,"
        " UNIQUE (symbol, tf, zone_kind, zone_low, zone_high, bar_time))"
    )
    conn.commit()
    conn.close()

    migrated = SqliteAnalysisStore(path)
    migrated.save(_record())

    got = migrated.get(_key())
    assert got is not None and got.attempts == 1


def test_database_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()

    with pytest.raises(StoreError, match="newer"):
        SqliteAnalysisStore(path)


def test_satisfies_the_store_protocol(store: SqliteAnalysisStore) -> None:
    protocol_view: AnalysisStore = store

    assert protocol_view.get(_key()) is None


def test_env_path_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DB_PATH_ENV, raising=False)

    assert db_path_from_env() == Path(DEFAULT_DB_PATH).resolve()


def test_env_path_blank_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DB_PATH_ENV, "   ")

    assert db_path_from_env() == Path(DEFAULT_DB_PATH).resolve()


def test_env_path_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path / "x.db"))

    assert db_path_from_env() == tmp_path / "x.db"


def test_env_path_with_nul_byte_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.environ", {DB_PATH_ENV: "a\x00b"})

    with pytest.raises(StoreError, match=DB_PATH_ENV):
        db_path_from_env()


def test_missing_parent_directory_is_a_store_error(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="directory"):
        SqliteAnalysisStore(tmp_path / "nope" / "smc.db")


def test_path_that_is_a_directory_is_a_store_error(tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        SqliteAnalysisStore(tmp_path)


def test_non_sqlite_file_is_a_store_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)

    with pytest.raises(StoreError):
        SqliteAnalysisStore(bad)


def test_database_file_is_created_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "private.db"

    SqliteAnalysisStore(path)

    assert path.exists()
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_unc_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="UNC"):
        SqliteAnalysisStore(UNC_PATH)
    with pytest.raises(StoreError, match="UNC"):
        SqliteAnalysisStore("//host/share/smc.db")


def test_env_unc_path_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DB_PATH_ENV, UNC_PATH)

    with pytest.raises(StoreError, match="UNC"):
        db_path_from_env()


def test_env_directory_path_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path))

    with pytest.raises(StoreError, match="directory"):
        db_path_from_env()


def test_env_path_is_absolute_and_logged_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(DB_PATH_ENV, "relative.db")

    with caplog.at_level(logging.INFO, logger="smc_scanner.ai.store"):
        path = db_path_from_env()

    assert path.is_absolute()
    assert [r.getMessage() for r in caplog.records].count(f"analysis database: {path}") == 1


@pytest.mark.parametrize("column", ["zone", "context", "verdict"])
@pytest.mark.parametrize("bad", ["{not json", "[1, 2]"])
def test_corrupt_stored_json_is_a_store_error(tmp_path: Path, column: str, bad: str) -> None:
    path = tmp_path / "smc.db"
    store = SqliteAnalysisStore(path)
    store.save(_record())
    conn = sqlite3.connect(path)
    conn.execute(f"UPDATE analyses SET {column} = ?", (bad,))
    conn.commit()
    conn.close()

    with pytest.raises(StoreError, match="corrupt"):
        store.get(_key())
    with pytest.raises(StoreError, match="corrupt"):
        store.list_recent(5)


def test_list_recent_limit_is_capped(store: SqliteAnalysisStore) -> None:
    for i in range(3):
        store.save(_record(_key(symbol=f"S{i}")))

    assert len(store.list_recent(10**9)) == 3


def test_failure_to_create_the_file_is_a_store_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def refuse(*args: object, **kwargs: object) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr("smc_scanner.ai.store.os.open", refuse)

    with pytest.raises(StoreError, match="cannot create"):
        SqliteAnalysisStore(tmp_path / "new.db")
