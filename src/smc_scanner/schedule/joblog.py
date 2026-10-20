"""Job log: one auditable row per completed scheduled run, in the same SQLite file as the schedules.

``SqliteJobLogStore.record_run`` is the recorder injected into ``RunDeps.record``. Rows hold
counts, UTC times, a status and a short error summary only. ``record`` is the single place error
text is sanitised: invisible/control characters are removed first (so a secret cannot be split to
dodge the patterns), then common key, token, URL and file-path shapes are redacted (best effort),
then the text is cut to ``MAX_ERROR_CHARS``. The runner's own ``_short`` cut (200 chars) happens
before this, so a secret straddling that cut can leave a harmless fragment.

Error text is internal. Any future endpoint must stay behind the internal key and must
output-encode ``error`` (it is data, not markup).

Retention: the newest ``retention`` rows per schedule for real runs, and a smaller
``skipped_retention`` for ``skipped`` rows (busy / already_running / stopped), so postponed ticks
cannot crowd out real history. Both are applied on every insert and at start-up. ``prune()`` also
drops rows of deleted schedules; ``prune_schedule`` removes one schedule's rows (for the delete
endpoint). Every statement is parameterised and each call opens a short-lived connection.
``list_entries`` is bounded, newest first, with keyset paging on ``id``.
"""

import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, get_args

from smc_scanner.ai.store import (
    BUSY_TIMEOUT_SECONDS,
    FILE_MODE,
    SCHEMA_VERSION,
    StoreError,
    checked_path,
)
from smc_scanner.schedule.runner import RunReport

DEFAULT_RETENTION: Final = 500
DEFAULT_SKIPPED_RETENTION: Final = 50
MAX_ERROR_CHARS: Final = 500
DEFAULT_LIST_LIMIT: Final = 50
MAX_LIST_LIMIT: Final = 200

JobStatus = Literal["success", "skipped", "failed"]

_INVISIBLE: Final = re.compile("[\x00-\x08\x0b-\x1f\x7f​-‏  ‪-‮⁠-⁩﻿]")
_WHITESPACE: Final = re.compile(r"\s+")
_SECRET_SHAPES: Final = re.compile(
    r"(?:bot)?\d{5,}:[A-Za-z0-9_-]{3,}"  # Telegram bot token
    r"|sk-[A-Za-z0-9_-]{16,}"  # OpenAI/Anthropic style keys
    r"|AIza[0-9A-Za-z_-]{20,}"  # Google API key
    r"|(?i:bearer)\s+\S+"
    r"|(?i:key|token|secret|password)=[^&\s]+"
    r"|https?://\S+"
    r"|[A-Za-z]:\\\S+"  # Windows path
    r"|/[^\s/()]+/\S+"  # POSIX path
    r"|[A-Za-z0-9_-]{24,}"  # any long opaque run
)
_STATUSES: Final = ", ".join(f"'{s}'" for s in get_args(JobStatus))
_SCHEMA: Final = (
    f"""
    CREATE TABLE IF NOT EXISTS job_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
        status TEXT NOT NULL CHECK (status IN ({_STATUSES})),
        hits INTEGER NOT NULL CHECK (hits >= 0),
        delivered INTEGER NOT NULL CHECK (delivered >= 0),
        skipped INTEGER NOT NULL CHECK (skipped >= 0),
        skip_reason TEXT,
        error TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS job_logs_schedule ON job_logs (schedule_id, id)",
)
_COLUMNS: Final = (
    "id, schedule_id, started_at, finished_at, status, hits, delivered, skipped, skip_reason, error"
)
_INSERT: Final = """
INSERT INTO job_logs (
    schedule_id, started_at, finished_at, duration_ms, status, hits, delivered, skipped,
    skip_reason, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
# Real runs and skipped runs are trimmed separately: (status = 'skipped') is 0 or 1.
_PRUNE_ONE: Final = """
DELETE FROM job_logs WHERE schedule_id = ? AND (status = 'skipped') = ? AND id NOT IN (
    SELECT id FROM job_logs WHERE schedule_id = ? AND (status = 'skipped') = ?
    ORDER BY id DESC LIMIT ?
)
"""
_PRUNE_ORPHANS: Final = "DELETE FROM job_logs WHERE schedule_id NOT IN (SELECT id FROM schedules)"
_PRUNE_ALL: Final = """
DELETE FROM job_logs WHERE id IN (
    SELECT id FROM (
        SELECT id, is_skip, ROW_NUMBER() OVER (
            PARTITION BY schedule_id, is_skip ORDER BY id DESC
        ) AS rank
        FROM (SELECT id, schedule_id, (status = 'skipped') AS is_skip FROM job_logs)
    ) WHERE rank > CASE WHEN is_skip THEN ? ELSE ? END
)
"""


@dataclass(frozen=True)
class JobLogEntry:
    """One run. Times are aware UTC; ``id`` is None until stored."""

    schedule_id: int
    started_at: datetime
    finished_at: datetime
    status: JobStatus
    hits: int = 0
    delivered: int = 0
    skipped: int = 0
    skip_reason: str | None = None
    error: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        for moment in (self.started_at, self.finished_at):
            if moment.tzinfo is None:
                raise ValueError("job log times must carry a timezone")
        if min(self.hits, self.delivered, self.skipped) < 0:
            raise ValueError("job log counts must not be negative")

    @property
    def duration_ms(self) -> int:
        return max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))


def sanitise_error(text: str) -> str:
    """Strip invisible characters, redact secret/path shapes, collapse whitespace, then bound."""
    visible = _INVISIBLE.sub("", text)
    redacted = _SECRET_SHAPES.sub("[redacted]", visible)
    return _WHITESPACE.sub(" ", redacted).strip()[:MAX_ERROR_CHARS]


def entry_from_report(report: RunReport, started: datetime, finished: datetime) -> JobLogEntry:
    """Map a ``RunReport`` to a log row (error text stays raw until ``record``)."""
    status: JobStatus
    if report.status == "ok":
        status = "success"
    elif report.status == "failed":
        status = "failed"
    else:
        status = "skipped"
    return JobLogEntry(
        schedule_id=report.schedule_id,
        started_at=started,
        finished_at=finished,
        status=status,
        hits=report.rows,
        delivered=report.delivered,
        skipped=len(report.skipped),
        skip_reason=report.status if status == "skipped" else None,
        error="; ".join(report.errors) or None,
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(text: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise StoreError("job log database holds a corrupt timestamp") from None
    if parsed.tzinfo is None:
        raise StoreError("job log database holds a corrupt timestamp")
    return parsed


def _to_entry(row: tuple[Any, ...]) -> JobLogEntry:
    row_id, schedule_id, started, finished, status, hits, delivered, skipped, reason, error = row
    return JobLogEntry(
        schedule_id=schedule_id,
        started_at=_parse(started),
        finished_at=_parse(finished),
        status=status,
        hits=hits,
        delivered=delivered,
        skipped=skipped,
        skip_reason=reason,
        error=error,
        id=row_id,
    )


class SqliteJobLogStore:
    def __init__(
        self,
        path: Path | str,
        *,
        retention: int = DEFAULT_RETENTION,
        skipped_retention: int = DEFAULT_SKIPPED_RETENTION,
    ) -> None:
        if retention < 1 or skipped_retention < 1:
            raise ValueError("retention must be at least 1")
        self._retention = retention
        self._skipped_retention = min(skipped_retention, retention)
        self._path = checked_path(path)
        parent = self._path.parent
        if not parent.is_dir():
            raise StoreError(f"database directory does not exist: {parent}")
        self._create_private_file()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise StoreError(f"database {self._path} was written by a newer version")
            for statement in _SCHEMA:
                conn.execute(statement)
        self.prune()

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
        except sqlite3.Error as exc:
            raise StoreError(f"job log database {self._path}: {exc}") from exc

    def record(self, entry: JobLogEntry) -> None:
        """Insert one row (error text sanitised here), then trim that schedule's history."""
        params = (
            entry.schedule_id,
            _iso(entry.started_at),
            _iso(entry.finished_at),
            entry.duration_ms,
            entry.status,
            entry.hits,
            entry.delivered,
            entry.skipped,
            entry.skip_reason,
            None if entry.error is None else sanitise_error(entry.error) or None,
        )
        is_skip = int(entry.status == "skipped")
        keep = self._skipped_retention if is_skip else self._retention
        with self._connect() as conn:
            conn.execute(_INSERT, params)
            conn.execute(_PRUNE_ONE, (entry.schedule_id, is_skip, entry.schedule_id, is_skip, keep))

    def record_run(self, report: RunReport, started: datetime, finished: datetime) -> None:
        """The ``RunDeps.record`` hook: store one row for a completed run."""
        self.record(entry_from_report(report, started, finished))

    def prune(self) -> int:
        """Trim every schedule to the retention and drop rows of deleted schedules.

        Returns the rows removed. The orphan sweep only runs once the ``schedules`` table exists.
        """
        with self._connect() as conn:
            removed = conn.execute(_PRUNE_ALL, (self._skipped_retention, self._retention)).rowcount
            has_schedules = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schedules'"
            ).fetchone()
            if has_schedules:
                removed += conn.execute(_PRUNE_ORPHANS).rowcount
            return removed

    def prune_schedule(self, schedule_id: int) -> int:
        """Delete every row of one schedule (call when the schedule is deleted)."""
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM job_logs WHERE schedule_id = ?", (schedule_id,)
            ).rowcount

    def list_entries(
        self,
        *,
        schedule_id: int | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        before_id: int | None = None,
    ) -> list[JobLogEntry]:
        """Newest first. Page with ``before_id`` = the last ``id`` of the previous page."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        clauses: list[str] = []
        params: list[Any] = []
        if schedule_id is not None:
            clauses.append("schedule_id = ?")
            params.append(schedule_id)
        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        params.append(min(limit, MAX_LIST_LIMIT))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM job_logs {where}ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        return [_to_entry(row) for row in rows]
