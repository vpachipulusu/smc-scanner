"""Persistence for user strategies, in the same SQLite file as the analyses and schedules.

``StrategyRepository`` is the Protocol callers depend on; ``SqliteStrategyRepository`` is the
stdlib implementation. Every statement is parameterised. Each call opens a short-lived
connection, so the repository holds no lock between calls and is safe to share across threads.

A row keeps the whole strategy as JSON (``Strategy.model_dump_json``) and is validated again on
every read: a row that no longer validates is logged and skipped, never raised. Stored
strategies are never built-in, so ``builtin`` is forced to False on every write. A skipped row
still holds its slug and counts toward ``MAX_STRATEGIES``; ``update`` or ``delete`` by that slug
(named in the log) repairs or removes it.

Like ``schedule.store``, this module only *checks* the shared ``PRAGMA user_version`` (a file
from a newer version is refused) and never writes it. The table is created with
``CREATE TABLE IF NOT EXISTS``; a later schema change here needs its own migration marker.
"""

import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import ValidationError

from smc_scanner.ai.store import (
    BUSY_TIMEOUT_SECONDS,
    FILE_MODE,
    SCHEMA_VERSION,
    StoreError,
    checked_path,
)
from smc_scanner.strategy.models import SLUG_PATTERN, Strategy

log = logging.getLogger(__name__)

MAX_STRATEGIES: Final = 50
_MAX_LOGGED_ERROR_CHARS: Final = 500

# NOT NULL: unlike other databases, SQLite lets a non-integer PRIMARY KEY hold NULL.
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS strategies (
    slug TEXT NOT NULL PRIMARY KEY,
    definition TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_SELECT_ALL: Final = "SELECT slug, definition FROM strategies ORDER BY slug"
_SELECT_ONE: Final = "SELECT slug, definition FROM strategies WHERE slug = ?"
_EXISTS: Final = "SELECT 1 FROM strategies WHERE slug = ?"
_COUNT: Final = "SELECT COUNT(*) FROM strategies"
_INSERT: Final = (
    "INSERT INTO strategies (slug, definition, created_at, updated_at) VALUES (?, ?, ?, ?)"
)
_UPDATE: Final = "UPDATE strategies SET definition = ?, updated_at = ? WHERE slug = ?"
_DELETE: Final = "DELETE FROM strategies WHERE slug = ?"


class StrategyNotFoundError(StoreError):
    """No readable stored strategy has the given slug."""


class StrategyConflictError(StoreError):
    """A strategy with the given slug already exists."""


class StrategyLimitError(StoreError):
    """The repository already holds ``MAX_STRATEGIES`` strategies."""


class StrategyRepository(Protocol):
    def list(self) -> tuple[Strategy, ...]:
        """All readable strategies by slug; rows that fail validation are skipped and logged."""
        ...

    def get(self, slug: str) -> Strategy: ...

    def create(self, strategy: Strategy) -> Strategy:
        """Store a new strategy (as non-built-in) and return what was stored."""
        ...

    def update(self, strategy: Strategy) -> Strategy:
        """Replace the strategy with the same slug (as non-built-in) and return it."""
        ...

    def delete(self, slug: str) -> None: ...


def non_builtin(strategy: Strategy) -> Strategy:
    """A validated copy with ``builtin=False`` (``model_copy(update=...)`` skips validation)."""
    return Strategy.model_validate({**strategy.model_dump(), "builtin": False})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(slug: str) -> StrategyNotFoundError:
    """Echo the slug only when it is well formed, so arbitrary input never reaches logs."""
    shown = repr(slug) if SLUG_PATTERN.fullmatch(slug) else "(invalid slug)"
    return StrategyNotFoundError(f"no strategy with slug {shown}")


# ``Any``: SQLite columns are dynamically typed, so a tampered row may hold anything.
def _load(slug: Any, definition: Any) -> Strategy | None:
    """The row's strategy, or None (logged) when it fails validation or disagrees with the row."""
    try:
        strategy = Strategy.model_validate_json(definition)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        shown = str(errors)[:_MAX_LOGGED_ERROR_CHARS]  # ``loc`` can hold stored field names
        log.error("skipping invalid strategy row %r: %s", slug, shown)
        return None
    if strategy.slug != slug or strategy.builtin:
        log.error("skipping strategy row %r: its definition does not match the row", slug)
        return None
    return strategy


class SqliteStrategyRepository:
    def __init__(self, path: Path | str, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = checked_path(path)
        self._clock = clock
        parent = self._path.parent
        if not parent.is_dir():
            raise StoreError(f"database directory does not exist: {parent}")
        self._create_private_file()
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise StoreError(f"database {self._path} was written by a newer version")
            conn.execute(_SCHEMA)

    def _create_private_file(self) -> None:
        """Create the file owner-only before SQLite does (best effort; Windows ignores modes)."""
        if self._path.exists():
            return
        try:
            os.close(os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, FILE_MODE))
        except FileExistsError:  # another process created it first
            return
        except OSError as exc:
            raise StoreError(f"cannot create database {self._path}: {exc}") from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_SECONDS)
            with closing(connection), connection:  # connection: commit or roll back
                yield connection
        except sqlite3.Error as exc:
            raise StoreError(f"strategy database {self._path}: {exc}") from exc

    def _timestamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    def list(self) -> tuple[Strategy, ...]:
        with self._connect() as conn:
            rows = conn.execute(_SELECT_ALL).fetchall()
        loaded = (_load(slug, definition) for slug, definition in rows)
        return tuple(strategy for strategy in loaded if strategy is not None)

    def get(self, slug: str) -> Strategy:
        with self._connect() as conn:
            row = conn.execute(_SELECT_ONE, (slug,)).fetchone()
        strategy = None if row is None else _load(*row)
        if strategy is None:
            raise _not_found(slug)
        return strategy

    def create(self, strategy: Strategy) -> Strategy:
        stored = non_builtin(strategy)
        now = self._timestamp()
        with self._connect() as conn:
            # Take the write lock before reading, so the checks and the insert are atomic and
            # concurrent creates (threads or processes) can never exceed the cap.
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(_EXISTS, (stored.slug,)).fetchone() is not None:
                raise StrategyConflictError(f"a strategy with slug {stored.slug!r} exists")
            if conn.execute(_COUNT).fetchone()[0] >= MAX_STRATEGIES:
                raise StrategyLimitError(
                    f"at most {MAX_STRATEGIES} strategies are allowed (unreadable rows count)"
                )
            conn.execute(_INSERT, (stored.slug, stored.model_dump_json(), now, now))
        return stored

    def update(self, strategy: Strategy) -> Strategy:
        stored = non_builtin(strategy)
        params = (stored.model_dump_json(), self._timestamp(), stored.slug)
        with self._connect() as conn:
            changed = conn.execute(_UPDATE, params).rowcount
        if changed == 0:
            raise _not_found(stored.slug)
        return stored

    def delete(self, slug: str) -> None:
        with self._connect() as conn:
            removed = conn.execute(_DELETE, (slug,)).rowcount
        if removed == 0:
            raise _not_found(slug)
