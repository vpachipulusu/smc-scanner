"""Persistence for schedules and sent alerts, in the same SQLite file as the analyses.

``ScheduleRepository`` is the Protocol callers depend on; ``SqliteScheduleRepository`` is the
stdlib implementation. Every statement is parameterised. Each call opens a short-lived
connection, so the repository holds no lock between calls and is safe to share across threads.

The file is shared with ``ai.store`` and both read ``PRAGMA user_version``. This module only
*checks* it (a file from a newer version is refused) and never writes it: bumping the shared
counter would make the older analysis store refuse the file. Tables are created with
``CREATE TABLE IF NOT EXISTS``; a later schema change here needs its own migration marker.
"""

import json
import logging
import math
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple, Protocol

from smc_scanner.ai.store import (
    BUSY_TIMEOUT_SECONDS,
    FILE_MODE,
    SCHEMA_VERSION,
    StoreError,
    canonical_bar_time,
    checked_path,
)
from smc_scanner.config import TIMEFRAMES
from smc_scanner.schedule.timing import FREQUENCIES
from smc_scanner.strategy.models import DEFAULT_STRATEGY_SLUG, SLUG_PATTERN

log = logging.getLogger(__name__)

SCHEDULE_SOURCES: Final = ("mt5", "demo")  # no csv: it needs a file path
SYMBOL_PATTERN: Final = re.compile(r"^[A-Za-z0-9._#@\-]{1,32}$")
CHAT_ID_PATTERN: Final = re.compile(r"-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31}")
MAX_NAME_CHARS: Final = 64
MAX_SYMBOLS: Final = 50
MAX_SCHEDULES: Final = 50
MAX_CONFIDENCE: Final = 100.0

_SCHEMA: Final = (
    f"""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        source TEXT NOT NULL,
        tf TEXT NOT NULL,
        symbols TEXT NOT NULL,
        frequency TEXT NOT NULL,
        min_score INTEGER NOT NULL,
        min_confidence REAL NOT NULL,
        only_on_change INTEGER NOT NULL,
        send_hold INTEGER NOT NULL,
        telegram_chat_id TEXT,
        last_run_at TEXT,
        next_run_at TEXT,
        mtf INTEGER NOT NULL DEFAULT 0,
        require_htf_aligned INTEGER NOT NULL DEFAULT 0,
        strategy TEXT NOT NULL DEFAULT '{DEFAULT_STRATEGY_SLUG}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sent_alerts (
        schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
        symbol TEXT NOT NULL,
        tf TEXT NOT NULL,
        zone_key TEXT NOT NULL,
        bar_time TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        UNIQUE (schedule_id, symbol, tf, zone_key, bar_time)
    )
    """,
)
_COLUMNS: Final = (
    "id, name, enabled, source, tf, symbols, frequency, min_score, min_confidence, "
    "only_on_change, send_hold, telegram_chat_id, last_run_at, next_run_at, "
    "mtf, require_htf_aligned, strategy"
)
# Columns added after the first release, with their definitions (constants, never input); each
# is added to an existing table when missing. The defaults match ``_SCHEMA``.
_ADDED_COLUMNS: Final = (
    ("mtf", "INTEGER NOT NULL DEFAULT 0"),
    ("require_htf_aligned", "INTEGER NOT NULL DEFAULT 0"),
    ("strategy", f"TEXT NOT NULL DEFAULT '{DEFAULT_STRATEGY_SLUG}'"),
)
_INSERT: Final = """
INSERT INTO schedules (
    name, enabled, source, tf, symbols, frequency, min_score, min_confidence, only_on_change,
    send_hold, telegram_chat_id, last_run_at, next_run_at, mtf, require_htf_aligned, strategy
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
# SET expressions read the row's old values, so the CASE sees the frequency/enabled being replaced.
_UPDATE: Final = """
UPDATE schedules SET
    name = ?, source = ?, tf = ?, symbols = ?, min_score = ?, min_confidence = ?,
    only_on_change = ?, send_hold = ?, telegram_chat_id = ?, mtf = ?, require_htf_aligned = ?,
    strategy = ?,
    next_run_at = CASE WHEN frequency = ? AND enabled = ? THEN next_run_at ELSE NULL END,
    frequency = ?, enabled = ?
WHERE id = ?
"""
_SELECT_PREVIOUS: Final = """
SELECT verdict FROM analyses
WHERE symbol = ? AND tf = ? AND verdict IS NOT NULL AND bar_time < ?
ORDER BY bar_time DESC, created_at DESC, id DESC LIMIT 1
"""


class ScheduleNotFoundError(StoreError):
    """No schedule has the given id."""


class ScheduleLimitError(StoreError):
    """The repository already holds ``MAX_SCHEDULES`` schedules."""


@dataclass(frozen=True)
class Schedule:
    """One alert rule set. ``id`` is None until stored; the run times are aware UTC."""

    name: str
    source: str
    tf: str
    symbols: tuple[str, ...]
    frequency: str
    min_score: int = 2
    min_confidence: float = 0.0
    only_on_change: bool = False
    send_hold: bool = False
    enabled: bool = True
    telegram_chat_id: str | None = None
    id: int | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    # Multi-timeframe analysis: show the HTF bias to the AI; optionally drop hits it opposes.
    mtf: bool = False
    require_htf_aligned: bool = False
    # Slug of the strategy to scan with; one that no longer exists falls back to the default.
    strategy: str = DEFAULT_STRATEGY_SLUG

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > MAX_NAME_CHARS:
            raise ValueError(f"name must be 1 to {MAX_NAME_CHARS} characters")
        if self.frequency not in FREQUENCIES:
            raise ValueError(f"frequency must be one of {', '.join(FREQUENCIES)}")
        if self.tf not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
        if self.source not in SCHEDULE_SOURCES:
            raise ValueError(f"source must be one of {', '.join(SCHEDULE_SOURCES)}")
        if not self.symbols or len(self.symbols) > MAX_SYMBOLS:
            raise ValueError(f"symbols must hold 1 to {MAX_SYMBOLS} names")
        for symbol in self.symbols:
            if not SYMBOL_PATTERN.fullmatch(symbol):
                raise ValueError(f"invalid symbol name: {symbol!r}")
        chat = self.telegram_chat_id
        if chat is not None and not CHAT_ID_PATTERN.fullmatch(chat):
            raise ValueError("telegram_chat_id must be a numeric chat id or an @channel name")
        if self.require_htf_aligned and not self.mtf:
            raise ValueError("require_htf_aligned needs mtf")
        if not isinstance(self.strategy, str) or not SLUG_PATTERN.fullmatch(self.strategy):
            raise ValueError("strategy must be a strategy slug")
        if self.min_score < 0:
            raise ValueError("min_score must not be negative")
        if not math.isfinite(self.min_confidence) or not 0 <= self.min_confidence <= MAX_CONFIDENCE:
            raise ValueError(f"min_confidence must be between 0 and {MAX_CONFIDENCE:.0f}")
        for moment in (self.last_run_at, self.next_run_at):
            if moment is not None and moment.tzinfo is None:
                raise ValueError("run times must carry a timezone")


class AlertKey(NamedTuple):
    """One alert per schedule, symbol, timeframe, zone and bar: the dedupe key."""

    schedule_id: int
    symbol: str
    tf: str
    zone_key: str
    bar_time: str


class ScheduleRepository(Protocol):
    def add(self, schedule: Schedule) -> Schedule: ...

    def get(self, schedule_id: int) -> Schedule | None: ...

    def list_schedules(self, *, enabled_only: bool = False) -> list[Schedule]:
        """All schedules by id; rows that cannot be read are skipped and logged."""
        ...

    def update(self, schedule: Schedule) -> Schedule:
        """Replace the editable fields. Run times are kept, except that next_run_at is cleared
        when the frequency or enabled flag changes so the service picks a fresh slot."""
        ...

    def delete(self, schedule_id: int) -> bool: ...

    def mark_run(
        self,
        schedule_id: int,
        last_run_at: datetime,
        next_run_at: datetime,
        *,
        frequency: str | None = None,
    ) -> None:
        """Record a run. With ``frequency`` given, ``next_run_at`` is stored only if the stored
        frequency still equals it; otherwise it is cleared so the service picks a fresh slot."""
        ...

    def set_next_run(self, schedule_id: int, next_run_at: datetime) -> None: ...

    def claim_alert(self, key: AlertKey, sent_at: datetime) -> bool:
        """Record the alert; False when it was already recorded (do not send it again)."""
        ...

    def release_alert(self, key: AlertKey) -> None:
        """Forget a claim, e.g. after the send failed, so a later run can retry it."""
        ...

    def delete_alerts_older_than(self, cutoff: datetime) -> int:
        """Drop dedupe rows sent before ``cutoff`` (they only matter for the bar they guard);
        returns how many were removed. Call it from housekeeping to keep the table small."""
        ...


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _parse_time(text: str | None) -> datetime | None:
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise StoreError("schedule database holds a corrupt timestamp") from None


def _symbols_from(text: str) -> tuple[str, ...]:
    try:
        value = json.loads(text)
    except ValueError:
        raise StoreError("schedule database holds corrupt JSON") from None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StoreError("schedule database holds corrupt JSON")
    return tuple(value)


def _to_schedule(row: tuple[Any, ...]) -> Schedule:
    (row_id, name, enabled, source, tf, symbols, frequency, min_score, min_confidence) = row[:9]
    (only_on_change, send_hold, chat_id, last_run, next_run, mtf, require_aligned) = row[9:16]
    strategy = row[16]
    try:
        return Schedule(
            name=name,
            source=source,
            tf=tf,
            symbols=_symbols_from(symbols),
            frequency=frequency,
            min_score=min_score,
            min_confidence=min_confidence,
            only_on_change=bool(only_on_change),
            send_hold=bool(send_hold),
            enabled=bool(enabled),
            telegram_chat_id=chat_id,
            id=row_id,
            last_run_at=_parse_time(last_run),
            next_run_at=_parse_time(next_run),
            mtf=bool(mtf),
            require_htf_aligned=bool(require_aligned),
            strategy=strategy,
        )
    except ValueError as exc:
        raise StoreError(f"schedule database holds an invalid schedule: {exc}") from exc


def _fields(schedule: Schedule) -> tuple[Any, ...]:
    """The editable columns, in the order ``_UPDATE`` binds them (before frequency/enabled)."""
    return (
        schedule.name,
        schedule.source,
        schedule.tf,
        json.dumps(list(schedule.symbols)),
        schedule.min_score,
        schedule.min_confidence,
        int(schedule.only_on_change),
        int(schedule.send_hold),
        schedule.telegram_chat_id,
        int(schedule.mtf),
        int(schedule.require_htf_aligned),
        schedule.strategy,
    )


class SqliteScheduleRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = checked_path(path)
        parent = self._path.parent
        if not parent.is_dir():
            raise StoreError(f"database directory does not exist: {parent}")
        self._create_private_file()
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise StoreError(f"database {self._path} was written by a newer version")
            for statement in _SCHEMA:
                conn.execute(statement)
            self._add_missing_columns(conn)

    @staticmethod
    def _add_missing_columns(conn: sqlite3.Connection) -> None:
        """Idempotent; the shared ``user_version`` is deliberately left alone."""
        columns = {row[1] for row in conn.execute("PRAGMA table_info(schedules)")}
        for name, definition in _ADDED_COLUMNS:
            if name in columns:
                continue
            try:
                conn.execute(f"ALTER TABLE schedules ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc):  # another process added it first
                    raise

    def _create_private_file(self) -> None:
        """Create the file owner-only before SQLite does (best effort; Windows ignores modes)."""
        if self._path.exists():
            return
        try:
            os.close(os.open(self._path, os.O_CREAT | os.O_WRONLY, FILE_MODE))
        except OSError as exc:
            raise StoreError(f"cannot create database {self._path}: {exc}") from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_SECONDS)
            with closing(connection), connection:  # connection: commit or roll back
                connection.execute("PRAGMA foreign_keys = ON")
                yield connection
        except sqlite3.Error as exc:
            raise StoreError(f"schedule database {self._path}: {exc}") from exc

    def add(self, schedule: Schedule) -> Schedule:
        params = (
            schedule.name,
            int(schedule.enabled),
            schedule.source,
            schedule.tf,
            json.dumps(list(schedule.symbols)),
            schedule.frequency,
            schedule.min_score,
            schedule.min_confidence,
            int(schedule.only_on_change),
            int(schedule.send_hold),
            schedule.telegram_chat_id,
            _iso(schedule.last_run_at),
            _iso(schedule.next_run_at),
            int(schedule.mtf),
            int(schedule.require_htf_aligned),
            schedule.strategy,
        )
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
            if count >= MAX_SCHEDULES:
                raise ScheduleLimitError(f"at most {MAX_SCHEDULES} schedules are allowed")
            new_id = conn.execute(_INSERT, params).lastrowid
        stored = self.get(new_id or 0)
        if stored is None:  # pragma: no cover - insert just succeeded
            raise StoreError("schedule was not saved")
        return stored

    def get(self, schedule_id: int) -> Schedule | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM schedules WHERE id = ?", (schedule_id,)
            ).fetchone()
        return None if row is None else _to_schedule(row)

    def list_schedules(self, *, enabled_only: bool = False) -> list[Schedule]:
        where = "WHERE enabled = 1 " if enabled_only else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM schedules {where}ORDER BY id").fetchall()
        found: list[Schedule] = []
        for row in rows:
            try:
                found.append(_to_schedule(row))
            except StoreError as exc:  # one bad row must not stall every other schedule
                log.error("skipping unreadable schedule row id=%s: %s", row[0], exc)
        return found

    def update(self, schedule: Schedule) -> Schedule:
        if schedule.id is None:
            raise ValueError("update needs a schedule with an id")
        params = (
            *_fields(schedule),
            schedule.frequency,
            int(schedule.enabled),
            schedule.frequency,
            int(schedule.enabled),
            schedule.id,
        )
        with self._connect() as conn:
            changed = conn.execute(_UPDATE, params).rowcount
        if changed == 0:
            raise ScheduleNotFoundError(f"no schedule with id {schedule.id}")
        stored = self.get(schedule.id)
        if stored is None:  # pragma: no cover - deleted between the two calls
            raise ScheduleNotFoundError(f"no schedule with id {schedule.id}")
        return stored

    def delete(self, schedule_id: int) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,)).rowcount > 0

    def mark_run(
        self,
        schedule_id: int,
        last_run_at: datetime,
        next_run_at: datetime,
        *,
        frequency: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE schedules SET last_run_at = ?, "
                "next_run_at = CASE WHEN ? IS NULL OR frequency = ? THEN ? ELSE NULL END "
                "WHERE id = ?",
                (_iso(last_run_at), frequency, frequency, _iso(next_run_at), schedule_id),
            )

    def set_next_run(self, schedule_id: int, next_run_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE schedules SET next_run_at = ? WHERE id = ?",
                (_iso(next_run_at), schedule_id),
            )

    def claim_alert(self, key: AlertKey, sent_at: datetime) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO sent_alerts "
                "(schedule_id, symbol, tf, zone_key, bar_time, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (*key, _iso(sent_at)),
            )
            return cursor.rowcount == 1

    def delete_alerts_older_than(self, cutoff: datetime) -> int:
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM sent_alerts WHERE sent_at < ?", (_iso(cutoff),)
            ).rowcount

    def release_alert(self, key: AlertKey) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sent_alerts WHERE schedule_id = ? AND symbol = ? AND tf = ? "
                "AND zone_key = ? AND bar_time = ?",
                tuple(key),
            )


def previous_action(db_path: Path | str, symbol: str, tf: str, bar_time: str) -> str | None:
    """The action of the latest stored verdict for ``symbol``/``tf`` on a bar before ``bar_time``.

    Reads the ``analyses`` table through a read-only connection, so it can never write. Returns
    None when there is no earlier verdict, or the database or table is missing or unreadable
    (the rules then treat the signal as new, and the per-bar alert dedupe still applies).
    """
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            row = conn.execute(
                _SELECT_PREVIOUS, (symbol, tf, canonical_bar_time(bar_time))
            ).fetchone()
        if row is None:
            return None
        verdict = json.loads(row[0])
        action = verdict.get("action") if isinstance(verdict, dict) else None
    except (sqlite3.Error, ValueError):
        log.warning("could not read the previous action for %s %s", symbol, tf)
        return None
    return action if isinstance(action, str) else None
