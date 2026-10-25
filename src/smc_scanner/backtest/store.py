"""Persistence for backtest runs, in the same SQLite file as the strategies and analyses.

``BacktestRepository`` is the Protocol callers depend on; ``SqliteBacktestRepository`` is the
stdlib implementation. Every statement is parameterised, and the statement text never depends on
input. Each call opens a short-lived connection, so the repository holds no lock between calls
and is safe to share across threads (the background job writes while the API reads).

A row is one run of one strategy: what was asked (source, timeframe, bars, symbols, exit rules,
split, seed, stride), how it went (``status``: pending, running, done or failed) and, once done,
its statistics as strict JSON (``stats``: the dict a walk-forward or pooled ``to_dict()``
returned, without per-signal rows) and ``verdict``. ``error`` only ever holds one of the fixed
messages the caller passes, never exception text. ``lookback`` is the replay window in bars (a
CLI run with ``--lookback``) or NULL for a whole-prefix replay; the API never sets it. Only the
latest ``MAX_ROWS_PER_STRATEGY`` finished rows per strategy, and
``MAX_ROWS`` in all, are kept; a pending or running row is never pruned.

Like ``strategy.store``, this module only *checks* the shared ``PRAGMA user_version`` (a file
from a newer version is refused) and never writes it. The table and its indexes are created with
``IF NOT EXISTS``; a later schema change here needs its own migration marker.
"""

import json
import logging
import math
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol, get_args

from smc_scanner.ai.store import (
    BUSY_TIMEOUT_SECONDS,
    FILE_MODE,
    SCHEMA_VERSION,
    StoreError,
    checked_path,
)
from smc_scanner.backtest._common import check_lookback

log = logging.getLogger(__name__)

BacktestStatus = Literal["pending", "running", "done", "failed"]
Verdict = Literal["pass", "fail", "insufficient"]
STATUSES: Final[tuple[str, ...]] = get_args(BacktestStatus)
VERDICTS: Final[tuple[str, ...]] = get_args(Verdict)
MAX_ROWS_PER_STRATEGY: Final = 200
MAX_ROWS: Final = 5000  # all strategies, so rows of deleted strategies cannot pile up
MAX_LIST_LIMIT: Final = 200
MAX_STATS_CHARS: Final = 100_000  # summaries only (a 50-symbol run is ~15k); never signal rows
LATEST_DONE_SCAN: Final = 5  # rows ``latest_done`` reads past unreadable ones
MAX_ERROR_CHARS: Final = 200
SIGNALS_KEY: Final = "signals"

JsonObject = dict[str, Any]

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    source TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bars INTEGER NOT NULL CHECK (bars > 0),
    symbols TEXT NOT NULL,
    rules TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('time', 'symbols')),
    train_fraction REAL,
    seed INTEGER NOT NULL,
    stride INTEGER NOT NULL CHECK (stride > 0),
    stats TEXT,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('pass', 'fail', 'insufficient')),
    duration_seconds REAL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
    error TEXT,
    lookback INTEGER
)
"""
# The status index is partial: ``fail_unfinished`` only ever looks for unfinished rows.
_INDEXES: Final = (
    "CREATE INDEX IF NOT EXISTS backtests_strategy_created ON backtests (strategy, created_at)",
    "CREATE INDEX IF NOT EXISTS backtests_created ON backtests (created_at)",
    "CREATE INDEX IF NOT EXISTS backtests_status ON backtests (status) "
    "WHERE status IN ('pending', 'running')",
)
_COLUMNS: Final = (
    "id, created_at, strategy, source, timeframe, bars, symbols, rules, split, train_fraction, "
    "seed, stride, stats, verdict, duration_seconds, status, error, lookback"
)
_INSERT: Final = """
INSERT INTO backtests (
    created_at, strategy, source, timeframe, bars, symbols, rules, split, train_fraction, seed,
    stride, stats, verdict, duration_seconds, status, error, lookback
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
# Retention keeps the newest finished rows by id (ids only grow, unlike a wall clock that can
# step back): MAX_ROWS_PER_STRATEGY of one strategy, then MAX_ROWS in all. Unfinished rows stay.
_PRUNE_STRATEGY: Final = """
DELETE FROM backtests WHERE strategy = ? AND status IN ('done', 'failed') AND id NOT IN (
    SELECT id FROM backtests WHERE strategy = ? ORDER BY id DESC LIMIT ?
)
"""
_PRUNE_ALL: Final = """
DELETE FROM backtests WHERE status IN ('done', 'failed') AND id NOT IN (
    SELECT id FROM backtests ORDER BY id DESC LIMIT ?
)
"""
_SELECT_BY_ID: Final = f"SELECT {_COLUMNS} FROM backtests WHERE id = ?"
# ``visible`` is one JSON array of slugs, bound as a single value so the statement text never
# changes; NULL means every strategy. Two statements, so the strategy filter can use its index.
_VISIBLE: Final = "(? IS NULL OR strategy IN (SELECT value FROM json_each(?)))"
_SELECT_LIST: Final = f"""
SELECT {_COLUMNS} FROM backtests WHERE {_VISIBLE}
ORDER BY created_at DESC, id DESC LIMIT ?
"""
_SELECT_LIST_STRATEGY: Final = f"""
SELECT {_COLUMNS} FROM backtests WHERE strategy = ? AND {_VISIBLE}
ORDER BY created_at DESC, id DESC LIMIT ?
"""
_SELECT_LATEST_DONE: Final = f"""
SELECT {_COLUMNS} FROM backtests
WHERE strategy = ? AND status = 'done'
ORDER BY created_at DESC, id DESC
LIMIT ?
"""
_MARK_RUNNING: Final = "UPDATE backtests SET status = 'running' WHERE id = ? AND status = 'pending'"
_FINISH: Final = """
UPDATE backtests SET status = 'done', stats = ?, verdict = ?, duration_seconds = ?, error = NULL
WHERE id = ? AND status IN ('pending', 'running')
"""
_FAIL: Final = """
UPDATE backtests SET status = 'failed', error = ?, duration_seconds = ?
WHERE id = ? AND status IN ('pending', 'running')
"""
_FAIL_UNFINISHED: Final = (
    "UPDATE backtests SET status = 'failed', error = ? WHERE status IN ('pending', 'running')"
)


class BacktestNotFoundError(StoreError):
    """No backtest row has the given id, or it is no longer pending or running."""


@dataclass(frozen=True)
class NewBacktest:
    """A run to record. The API inserts it pending and fills in the outcome later; the CLI
    inserts a finished one (``status="done"`` with ``stats``)."""

    strategy: str
    source: str
    timeframe: str
    bars: int
    symbols: tuple[str, ...]
    rules: Mapping[str, float | int]
    split: str
    train_fraction: float | None
    seed: int
    stride: int
    status: BacktestStatus = "pending"
    stats: JsonObject | None = None
    verdict: Verdict | None = None
    duration_seconds: float | None = None
    error: str | None = None
    lookback: int | None = None  # the replay window in bars; None: the whole prefix


@dataclass(frozen=True)
class BacktestRecord:
    id: int
    created_at: str
    strategy: str
    source: str
    timeframe: str
    bars: int
    symbols: tuple[str, ...]
    rules: JsonObject
    split: str
    train_fraction: float | None
    seed: int
    stride: int
    status: BacktestStatus
    stats: JsonObject | None = None
    verdict: Verdict | None = None
    duration_seconds: float | None = None
    error: str | None = None
    lookback: int | None = None  # the replay window in bars; None: the whole prefix


class BacktestRepository(Protocol):
    def insert(self, run: NewBacktest) -> BacktestRecord:
        """Store a run (pruning that strategy's oldest rows past the cap) and return it."""
        ...

    def get(self, backtest_id: int) -> BacktestRecord | None: ...

    def list(
        self,
        *,
        strategy: str | None = None,
        visible: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[BacktestRecord]:
        """Newest first; ``visible`` (when given) hides the rows of every other strategy."""
        ...

    def latest_done(self, strategy: str) -> BacktestRecord | None: ...

    def mark_running(self, backtest_id: int) -> None: ...

    def finish(
        self, backtest_id: int, stats: JsonObject, verdict: Verdict | None, duration: float
    ) -> None: ...

    def fail(self, backtest_id: int, error: str, duration: float | None) -> None: ...

    def fail_unfinished(self, error: str) -> int:
        """Mark every pending or running row failed (their process is gone); the count."""
        ...


def without_signals(value: Any) -> Any:
    """``value`` with every ``signals`` key dropped at any depth: summaries stay small."""
    if isinstance(value, dict):
        return {k: without_signals(v) for k, v in value.items() if k != SIGNALS_KEY}
    if isinstance(value, list | tuple):
        return [without_signals(item) for item in value]
    return value


def _dump_stats(stats: JsonObject | None) -> str | None:
    """Strict JSON (no NaN or infinity) under ``MAX_STATS_CHARS``; else ValueError."""
    if stats is None:
        return None
    text = json.dumps(without_signals(stats), sort_keys=True, allow_nan=False)
    if len(text) > MAX_STATS_CHARS:
        raise ValueError(f"backtest stats exceed {MAX_STATS_CHARS} characters")
    return text


def _checked_error(error: str | None) -> str | None:
    return None if error is None else error[:MAX_ERROR_CHARS]


def parse_verdict(raw: object) -> Verdict | None:
    """``raw`` as a verdict, or None when it is not one."""
    if raw == "pass" or raw == "fail" or raw == "insufficient":
        return raw
    return None


def _checked_verdict(verdict: object) -> Verdict | None:
    parsed = parse_verdict(verdict)
    if verdict is not None and parsed is None:
        raise ValueError("verdict must be pass, fail or insufficient")
    return parsed


def _checked_status(status: object) -> BacktestStatus:
    if status == "pending" or status == "running" or status == "done" or status == "failed":
        return status
    raise ValueError("status must be pending, running, done or failed")


def _checked_run(run: NewBacktest) -> None:
    _checked_status(run.status)
    _checked_verdict(run.verdict)
    if run.train_fraction is not None and not math.isfinite(run.train_fraction):
        raise ValueError("train_fraction must be finite")
    check_lookback(run.lookback)  # the replay's own limits: a stored row was a real run


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_object(text: Any) -> JsonObject:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("not a JSON object")
    return parsed


# ``Any``: SQLite columns are dynamically typed, so a tampered row may hold anything.
def _to_record(row: Sequence[Any]) -> BacktestRecord | None:
    """The row as a record, or None (logged) when its JSON or enums do not parse."""
    rid, created, strategy, source, tf, bars, symbols, rules, split, fraction = row[:10]
    seed, stride, stats, verdict, duration, status, error, lookback = row[10:]
    try:
        parsed_symbols = json.loads(symbols)
        if not isinstance(parsed_symbols, list):
            raise ValueError("symbols is not a JSON array")
        return BacktestRecord(
            id=int(rid),
            created_at=str(created),
            strategy=str(strategy),
            source=str(source),
            timeframe=str(tf),
            bars=int(bars),
            symbols=tuple(str(symbol) for symbol in parsed_symbols),
            rules=_json_object(rules),
            split=str(split),
            train_fraction=None if fraction is None else float(fraction),
            seed=int(seed),
            stride=int(stride),
            status=_checked_status(status),
            stats=None if stats is None else _json_object(stats),
            verdict=_checked_verdict(verdict),
            duration_seconds=None if duration is None else float(duration),
            error=None if error is None else str(error),
            lookback=None if lookback is None else int(lookback),
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:  # incl. JSONDecodeError
        log.error("skipping unreadable backtest row %r: %s", rid, type(exc).__name__)
        return None


class SqliteBacktestRepository:
    def __init__(self, path: Path | str, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = checked_path(path)
        self._clock = clock
        parent = self._path.parent
        if not parent.is_dir():
            raise StoreError(f"database directory does not exist: {parent}")
        self._create_private_file()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # the job writes while the API polls
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise StoreError(f"database {self._path} was written by a newer version")
            conn.execute(_SCHEMA)
            for statement in _INDEXES:
                conn.execute(statement)

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
            raise StoreError(f"backtest database {self._path}: {exc}") from exc

    def _timestamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    def insert(self, run: NewBacktest) -> BacktestRecord:
        _checked_run(run)
        params = (
            self._timestamp(),
            run.strategy,
            run.source,
            run.timeframe,
            run.bars,
            json.dumps(list(run.symbols)),
            json.dumps(dict(run.rules), sort_keys=True, allow_nan=False),
            run.split,
            run.train_fraction,
            run.seed,
            run.stride,
            _dump_stats(run.stats),
            run.verdict,
            run.duration_seconds,
            run.status,
            _checked_error(run.error),
            run.lookback,
        )
        with self._connect() as conn:
            row_id = conn.execute(_INSERT, params).lastrowid
            conn.execute(_PRUNE_STRATEGY, (run.strategy, run.strategy, MAX_ROWS_PER_STRATEGY))
            conn.execute(_PRUNE_ALL, (MAX_ROWS,))
            row = conn.execute(_SELECT_BY_ID, (row_id,)).fetchone()
        record = None if row is None else _to_record(row)
        if record is None:  # pragma: no cover - this module wrote the row just now
            raise StoreError("a stored backtest could not be read back")
        return record

    def get(self, backtest_id: int) -> BacktestRecord | None:
        with self._connect() as conn:
            row = conn.execute(_SELECT_BY_ID, (backtest_id,)).fetchone()
        return None if row is None else _to_record(row)

    # Shadows the builtin in this class body from here on: later annotations must not use list.
    def list(
        self,
        *,
        strategy: str | None = None,
        visible: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[BacktestRecord]:
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
        shown = None if visible is None else json.dumps(list(visible))
        params: tuple[str | int | None, ...] = (shown, shown, limit)
        statement = _SELECT_LIST
        if strategy is not None:
            statement, params = _SELECT_LIST_STRATEGY, (strategy, *params)
        with self._connect() as conn:
            rows = conn.execute(statement, params).fetchall()
        records = (_to_record(row) for row in rows)
        return [record for record in records if record is not None]

    def latest_done(self, strategy: str) -> BacktestRecord | None:
        """The newest readable finished row; an unreadable newest row does not hide older ones."""
        with self._connect() as conn:
            rows = conn.execute(_SELECT_LATEST_DONE, (strategy, LATEST_DONE_SCAN)).fetchall()
        records = (_to_record(row) for row in rows)
        return next((record for record in records if record is not None), None)

    def _update(self, statement: str, params: tuple[Any, ...], backtest_id: int) -> None:
        with self._connect() as conn:
            changed = conn.execute(statement, params).rowcount
        if changed == 0:
            raise BacktestNotFoundError(f"no unfinished backtest with id {backtest_id}")

    def mark_running(self, backtest_id: int) -> None:
        self._update(_MARK_RUNNING, (backtest_id,), backtest_id)

    def finish(
        self, backtest_id: int, stats: JsonObject, verdict: Verdict | None, duration: float
    ) -> None:
        params = (_dump_stats(stats), _checked_verdict(verdict), duration, backtest_id)
        self._update(_FINISH, params, backtest_id)

    def fail(self, backtest_id: int, error: str, duration: float | None) -> None:
        self._update(_FAIL, (_checked_error(error), duration, backtest_id), backtest_id)

    def fail_unfinished(self, error: str) -> int:
        with self._connect() as conn:
            changed: int = conn.execute(_FAIL_UNFINISHED, (_checked_error(error),)).rowcount
        return changed
