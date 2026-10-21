"""SQLite cache of the calendar feed, in the same database file as the analyses.

Every statement is parameterised and each call opens a short-lived connection. Like the journal
store this module only *checks* ``PRAGMA user_version`` (a file from a newer version is refused)
and never writes it: only ``ai.store`` owns the shared counter. Tables are created with
``CREATE TABLE IF NOT EXISTS``; a later schema change needs its own migration marker.
"""

import logging
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from smc_scanner.ai.store import (
    BUSY_TIMEOUT_SECONDS,
    FILE_MODE,
    SCHEMA_VERSION,
    StoreError,
    checked_path,
)
from smc_scanner.econ_calendar.models import CalendarEvent

log = logging.getLogger(__name__)

_FETCHED_AT_KEY: Final = "fetched_at"
_SCHEMA: Final = (
    """
    CREATE TABLE IF NOT EXISTS calendar_events (
        currency TEXT NOT NULL,
        impact TEXT NOT NULL,
        time TEXT NOT NULL,
        title TEXT NOT NULL,
        actual REAL,
        forecast REAL,
        previous REAL,
        PRIMARY KEY (currency, time, title)
    )
    """,
    "CREATE TABLE IF NOT EXISTS calendar_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


def _iso(moment: datetime) -> str:
    """Fixed-width UTC text, so string order is time order."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


@dataclass(frozen=True)
class StoredCalendar:
    events: tuple[CalendarEvent, ...]
    fetched_at: datetime | None


def _to_event(row: tuple[Any, ...]) -> CalendarEvent | None:
    currency, impact, time, title, actual, forecast, previous = row
    try:
        return CalendarEvent(
            currency=currency,
            impact=impact,
            time=datetime.fromisoformat(time),
            title=title,
            actual=actual,
            forecast=forecast,
            previous=previous,
        )
    except (ValidationError, ValueError, TypeError):
        return None


class SqliteCalendarStore:
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
                yield connection
        except (sqlite3.Error, OverflowError) as exc:
            raise StoreError(f"calendar database {self._path}: {exc}") from exc

    def replace(self, events: Sequence[CalendarEvent], fetched_at: datetime) -> None:
        """Swap the cached week for ``events`` in one transaction."""
        rows = [
            (e.currency, e.impact, _iso(e.time), e.title, e.actual, e.forecast, e.previous)
            for e in events
        ]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM calendar_events")
            conn.executemany(
                "INSERT OR REPLACE INTO calendar_events "
                "(currency, impact, time, title, actual, forecast, previous) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute(
                "INSERT OR REPLACE INTO calendar_meta (key, value) VALUES (?, ?)",
                (_FETCHED_AT_KEY, _iso(fetched_at)),
            )

    def load(self) -> StoredCalendar:
        """The cached events (unreadable rows are skipped) and when they were fetched."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT currency, impact, time, title, actual, forecast, previous "
                "FROM calendar_events ORDER BY time, currency, title"
            ).fetchall()
            meta = conn.execute(
                "SELECT value FROM calendar_meta WHERE key = ?", (_FETCHED_AT_KEY,)
            ).fetchone()
        parsed = [_to_event(row) for row in rows]
        events = tuple(item for item in parsed if item is not None)
        if len(events) != len(rows):
            log.warning("calendar cache: %d unreadable rows skipped", len(rows) - len(events))
        return StoredCalendar(events, self._fetched_at(meta))

    @staticmethod
    def _fetched_at(meta: tuple[Any, ...] | None) -> datetime | None:
        if meta is None:
            return None
        try:
            moment = datetime.fromisoformat(meta[0])
        except (ValueError, TypeError):
            return None
        return moment if moment.tzinfo is not None else None
