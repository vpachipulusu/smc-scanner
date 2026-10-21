"""Persistence for the manual trade journal, in the same SQLite file as the analyses.

``JournalStore`` is the Protocol callers depend on; ``SqliteJournalStore`` is the stdlib
implementation. Every statement is parameterised and each call opens a short-lived connection, so
the store holds no lock between calls and is safe to share across threads.

The file is shared with ``ai.store`` and ``schedule.store``. This module only *checks*
``PRAGMA user_version`` (a file from a newer version is refused) and never writes it: bumping the
shared counter would make the other stores refuse the file. The table is created with
``CREATE TABLE IF NOT EXISTS``; a later schema change needs its own migration marker.
``analysis_id`` is a plain reference with no foreign key, so journal rows survive analysis pruning.
"""

import logging
import os
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
    MAX_LIST_LIMIT,
    SCHEMA_VERSION,
    StoreError,
    checked_path,
)
from smc_scanner.journal.models import JournalEntryIn, JournalEntryOut, JournalEntryUpdate

log = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE: Final = 50
MAX_ENTRIES: Final = 10_000
MAX_ID: Final = 2**63 - 1  # SQLite INTEGER

_SCHEMA: Final = (
    """
    CREATE TABLE IF NOT EXISTS journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('long', 'short')),
        entry REAL NOT NULL CHECK (entry > 0),
        stop REAL NOT NULL CHECK (stop > 0),
        exit REAL,
        size REAL,
        pnl_currency REAL,
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        notes TEXT NOT NULL,
        analysis_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK ((exit IS NULL) = (closed_at IS NULL))
    )
    """,
    "CREATE INDEX IF NOT EXISTS journal_entries_opened "
    "ON journal_entries (opened_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS journal_entries_symbol "
    "ON journal_entries (symbol, opened_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS journal_entries_closed ON journal_entries (closed_at, id)",
)
_COLUMNS: Final = (
    "id, symbol, timeframe, side, entry, stop, exit, size, pnl_currency, opened_at, closed_at, "
    "notes, analysis_id, created_at, updated_at"
)
_INSERT: Final = """
INSERT INTO journal_entries (
    symbol, timeframe, side, entry, stop, exit, size, pnl_currency, opened_at, closed_at, notes,
    analysis_id, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_UPDATE: Final = """
UPDATE journal_entries SET
    symbol = ?, timeframe = ?, side = ?, entry = ?, stop = ?, exit = ?, size = ?,
    pnl_currency = ?, opened_at = ?, closed_at = ?, notes = ?, analysis_id = ?, updated_at = ?
WHERE id = ?
"""
_STORED_FIELDS: Final = set(JournalEntryIn.model_fields)


class JournalNotFoundError(StoreError):
    """No journal entry has the given id."""


class JournalLimitError(StoreError):
    """The journal already holds ``MAX_ENTRIES`` entries."""


class JournalCursor(NamedTuple):
    """Keyset position: the last entry of a page (newest first by opened_at, then id)."""

    opened_at: datetime
    id: int


@dataclass(frozen=True)
class JournalPage:
    items: list[JournalEntryOut]
    next_cursor: JournalCursor | None


class JournalStore(Protocol):
    def add(self, entry: JournalEntryIn) -> JournalEntryOut: ...

    def get(self, entry_id: int) -> JournalEntryOut | None: ...

    def update(self, entry_id: int, patch: JournalEntryUpdate) -> JournalEntryOut:
        """Apply ``patch`` to the stored entry and re-validate the result.

        Raises ``JournalNotFoundError`` for an unknown id and pydantic's ``ValidationError`` when
        the merged entry breaks a rule; nothing is written in either case."""
        ...

    def delete(self, entry_id: int) -> bool: ...

    def list_entries(
        self,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: JournalCursor | None = None,
        symbol: str | None = None,
    ) -> JournalPage:
        """Newest ``opened_at`` first. ``limit`` is 1 to ``MAX_LIST_LIMIT``; unreadable rows are
        skipped and logged. Pass ``next_cursor`` back as ``cursor`` for the following page."""
        ...

    def closed_entries(self) -> list[JournalEntryOut]:
        """Every closed entry, oldest ``closed_at`` first: the input for statistics."""
        ...


def _iso(moment: datetime | None) -> str | None:
    """Fixed-width UTC text, so string order is time order."""
    if moment is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _parse_time(text: str | None) -> datetime | None:
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise StoreError("journal database holds a corrupt timestamp") from None


def _parse_required_time(text: str) -> datetime:
    moment = _parse_time(text)
    if moment is None:  # pragma: no cover - the column is NOT NULL
        raise StoreError("journal database holds a corrupt timestamp")
    return moment


def _to_entry(row: tuple[Any, ...]) -> JournalEntryOut:
    (row_id, symbol, timeframe, side, entry, stop, exit_price, size, pnl) = row[:9]
    (opened, closed, notes, analysis_id, created, updated) = row[9:]
    try:
        return JournalEntryOut(
            id=row_id,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            entry=entry,
            stop=stop,
            exit=exit_price,
            size=size,
            pnl_currency=pnl,
            opened_at=_parse_required_time(opened),
            closed_at=_parse_time(closed),
            notes=notes,
            analysis_id=analysis_id,
            created_at=_parse_required_time(created),
            updated_at=_parse_required_time(updated),
        )
    except ValueError as exc:  # pydantic's ValidationError is a ValueError
        raise StoreError(f"journal database holds an invalid entry: {exc}") from exc


def _fields(entry: JournalEntryIn) -> tuple[Any, ...]:
    """The editable columns, in the order ``_INSERT`` and ``_UPDATE`` bind them."""
    return (
        entry.symbol,
        entry.timeframe,
        entry.side,
        entry.entry,
        entry.stop,
        entry.exit,
        entry.size,
        entry.pnl_currency,
        _iso(entry.opened_at),
        _iso(entry.closed_at),
        entry.notes,
        entry.analysis_id,
    )


class SqliteJournalStore:
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
            raise StoreError(f"journal database {self._path}: {exc}") from exc

    def add(self, entry: JournalEntryIn) -> JournalEntryOut:
        now = _iso(datetime.now(UTC))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
            if count >= MAX_ENTRIES:
                raise JournalLimitError(f"at most {MAX_ENTRIES} journal entries are allowed")
            new_id = conn.execute(_INSERT, (*_fields(entry), now, now)).lastrowid
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries WHERE id = ?", (new_id,)
            ).fetchone()
        return _to_entry(row)

    def get(self, entry_id: int) -> JournalEntryOut | None:
        if not 1 <= entry_id <= MAX_ID:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return None if row is None else _to_entry(row)

    def update(self, entry_id: int, patch: JournalEntryUpdate) -> JournalEntryOut:
        if not 1 <= entry_id <= MAX_ID:
            raise JournalNotFoundError(f"no journal entry with id {entry_id}")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # read, merge and write under one write lock
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                raise JournalNotFoundError(f"no journal entry with id {entry_id}")
            merged = {
                **_to_entry(row).model_dump(include=_STORED_FIELDS),
                **patch.model_dump(exclude_unset=True),
            }
            entry = JournalEntryIn.model_validate(merged)  # ValidationError rolls back
            conn.execute(_UPDATE, (*_fields(entry), _iso(datetime.now(UTC)), entry_id))
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return _to_entry(row)

    def delete(self, entry_id: int) -> bool:
        if not 1 <= entry_id <= MAX_ID:
            return False
        with self._connect() as conn:
            return (
                conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,)).rowcount > 0
            )

    def list_entries(
        self,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: JournalCursor | None = None,
        symbol: str | None = None,
    ) -> JournalPage:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        limit = min(limit, MAX_LIST_LIMIT)
        if cursor is not None and (cursor.opened_at.tzinfo is None or not 0 <= cursor.id <= MAX_ID):
            raise ValueError("cursor needs an aware opened_at and an id in range")
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if cursor is not None:
            clauses.append("(opened_at, id) < (?, ?)")
            params.extend((_iso(cursor.opened_at), cursor.id))
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries {where}"
                "ORDER BY opened_at DESC, id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
        page = rows[:limit]
        items = self._readable(page)
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]  # cursor from the raw row so a skipped bad row cannot stall paging
            try:
                next_cursor = JournalCursor(_parse_required_time(last[9]), last[0])
            except StoreError as exc:
                log.error("journal paging stopped at unreadable row id=%s: %s", last[0], exc)
        return JournalPage(items, next_cursor)

    def closed_entries(self) -> list[JournalEntryOut]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries WHERE closed_at IS NOT NULL "
                "ORDER BY closed_at, id"
            ).fetchall()
        return self._readable(rows)

    @staticmethod
    def _readable(rows: list[tuple[Any, ...]]) -> list[JournalEntryOut]:
        found: list[JournalEntryOut] = []
        for row in rows:
            try:
                found.append(_to_entry(row))
            except StoreError as exc:  # one bad row must not hide every other entry
                log.error("skipping unreadable journal row id=%s: %s", row[0], exc)
        return found
