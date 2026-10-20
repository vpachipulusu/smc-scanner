"""Persistence for LLM verdicts: a small repository Protocol and a stdlib SQLite implementation.

Callers depend on ``AnalysisStore`` only, so SQLite can later be swapped for Postgres. Every
statement is parameterised: model text and symbols are bound values, never part of the SQL.
Each operation opens its own short-lived connection, so the store holds no lock between calls
and is safe to share across threads.
"""

import json
import logging
import math
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

log = logging.getLogger(__name__)

DB_PATH_ENV: Final = "SMC_DB_PATH"
DEFAULT_DB_PATH: Final = "./smc.db"
BUSY_TIMEOUT_SECONDS: Final = 10.0
SCHEMA_VERSION: Final = 1
MAX_LIST_LIMIT: Final = 500
FILE_MODE: Final = 0o600
KEY_SIGNIFICANT_DIGITS: Final = 8  # zone bounds in the dedupe key; absorbs float noise

JsonObject = dict[str, Any]

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    zone_kind TEXT NOT NULL,
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    bar_time TEXT NOT NULL,
    zone TEXT NOT NULL,
    context TEXT,
    verdict TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_estimate REAL,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    UNIQUE (symbol, tf, zone_kind, zone_low, zone_high, bar_time)
)
"""
_COLUMNS: Final = (
    "id, created_at, symbol, tf, zone_kind, zone_low, zone_high, bar_time, zone, context, "
    "verdict, provider, model, prompt_version, tokens_in, tokens_out, cost_estimate, error, "
    "attempts"
)
_UPSERT: Final = """
INSERT INTO analyses (
    created_at, symbol, tf, zone_kind, zone_low, zone_high, bar_time, zone, context, verdict,
    provider, model, prompt_version, tokens_in, tokens_out, cost_estimate, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, tf, zone_kind, zone_low, zone_high, bar_time) DO UPDATE SET
    created_at = excluded.created_at, zone = excluded.zone, context = excluded.context,
    verdict = excluded.verdict, provider = excluded.provider, model = excluded.model,
    prompt_version = excluded.prompt_version, tokens_in = excluded.tokens_in,
    tokens_out = excluded.tokens_out, cost_estimate = excluded.cost_estimate,
    error = excluded.error, attempts = analyses.attempts + 1
WHERE ? OR analyses.error IS NOT NULL
"""
_SELECT_ONE: Final = f"""
SELECT {_COLUMNS} FROM analyses
WHERE symbol = ? AND tf = ? AND zone_kind = ? AND zone_low = ? AND zone_high = ? AND bar_time = ?
"""
_SELECT_RECENT: Final = f"SELECT {_COLUMNS} FROM analyses ORDER BY created_at DESC, id DESC LIMIT ?"
_SELECT_BY_ID: Final = f"SELECT {_COLUMNS} FROM analyses WHERE id = ?"
# Optional filters are bound as NULL when unused, so the statement text never changes. The
# verdict JSON is read with json_extract; a failed attempt (verdict NULL) never matches a
# verdict filter. Keyset paging on the primary key: newest first, ``id < before_id``.
_SELECT_FILTERED: Final = f"""
SELECT {_COLUMNS} FROM analyses
WHERE (? IS NULL OR symbol = ?)
  AND (? IS NULL OR json_extract(verdict, '$.action') = ?)
  AND (? IS NULL OR json_extract(verdict, '$.confidence') >= ?)
  AND (? IS NULL OR id < ?)
ORDER BY id DESC
LIMIT ?
"""


class StoreError(Exception):
    """The analysis store is misconfigured or unusable."""


def canonical_bar_time(text: str) -> str:
    """A bar time as a UTC ISO string; naive times are taken to be UTC."""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("bar_time is not an ISO timestamp") from None
    parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return parsed.isoformat()


def _normalise_bound(name: str, value: float) -> float:
    """Round a zone bound to the key precision; reject non-finite values."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(f"{value:.{KEY_SIGNIFICANT_DIGITS}g}")


@dataclass(frozen=True)
class AnalysisKey:
    """One analysis per zone per bar: the dedupe key.

    Normalised on construction (bounds to 8 significant digits, bar time to UTC ISO) so that
    float noise and timestamp spelling cannot create duplicates. Non-finite bounds raise
    ValueError. The prompt version, provider and model are deliberately not part of the key.
    """

    symbol: str
    tf: str
    zone_kind: str
    zone_low: float
    zone_high: float
    bar_time: str

    def __post_init__(self) -> None:
        low = _normalise_bound("zone_low", self.zone_low)
        high = _normalise_bound("zone_high", self.zone_high)
        object.__setattr__(self, "zone_low", low)
        object.__setattr__(self, "zone_high", high)
        object.__setattr__(self, "bar_time", canonical_bar_time(self.bar_time))


@dataclass(frozen=True)
class AnalysisRecord:
    """A saved attempt: a verdict, or an error when the attempt failed (verdict is None)."""

    key: AnalysisKey
    created_at: str
    zone: JsonObject
    context: JsonObject | None
    verdict: JsonObject | None
    provider: str
    model: str
    prompt_version: str
    tokens_in: int | None
    tokens_out: int | None
    cost_estimate: float | None
    error: str | None
    id: int | None = None
    attempts: int = 1


class AnalysisStore(Protocol):
    def get(self, key: AnalysisKey) -> AnalysisRecord | None: ...

    def save(self, record: AnalysisRecord, *, overwrite: bool = False) -> None:
        """Insert, or replace a stored failure. A stored success is kept unless ``overwrite``."""
        ...

    def list_recent(self, limit: int) -> list[AnalysisRecord]: ...


class AnalysisReader(Protocol):
    """Read side used by the API: one record by id, and a filtered, keyset-paged list."""

    def get_by_id(self, record_id: int) -> AnalysisRecord | None: ...

    def list_filtered(
        self,
        *,
        symbol: str | None = None,
        action: str | None = None,
        min_confidence: float | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[AnalysisRecord]:
        """Newest first (by id). ``before_id`` is exclusive; ``limit`` is capped at 500."""
        ...


def _checked_path(raw: str | Path) -> Path:
    """Absolute path; UNC (network) paths and directories are refused."""
    text = str(raw)
    if text.startswith(("\\\\", "//")):
        raise StoreError("network (UNC) database paths are not allowed")
    path = Path(text).resolve()
    if path.is_dir():
        raise StoreError(f"database path is a directory: {path}")
    return path


def db_path_from_env() -> Path:
    """SMC_DB_PATH (made absolute), or ./smc.db when unset or blank."""
    raw = os.environ.get(DB_PATH_ENV, "").strip()
    if chr(0) in raw:
        raise StoreError(f"{DB_PATH_ENV} must not contain NUL characters")
    path = _checked_path(raw or DEFAULT_DB_PATH)
    log.info("analysis database: %s", path)
    return path


def _dump(value: JsonObject | None) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _load(text: str | None) -> JsonObject | None:
    return None if text is None else _loads(text)


def _loads(text: str) -> JsonObject:
    try:
        value = json.loads(text)
    except ValueError:
        raise StoreError("analysis database holds corrupt JSON") from None
    if not isinstance(value, dict):
        raise StoreError("analysis database holds corrupt JSON")
    return value


def _to_record(row: tuple[Any, ...]) -> AnalysisRecord:
    (
        row_id,
        created_at,
        symbol,
        tf,
        zone_kind,
        zone_low,
        zone_high,
        bar_time,
        zone,
        context,
        verdict,
        provider,
        model,
        prompt_version,
        tokens_in,
        tokens_out,
        cost_estimate,
        error,
        attempts,
    ) = row
    return AnalysisRecord(
        key=AnalysisKey(symbol, tf, zone_kind, zone_low, zone_high, bar_time),
        created_at=created_at,
        zone=_loads(zone),
        context=_load(context),
        verdict=_load(verdict),
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_estimate=cost_estimate,
        error=error,
        id=row_id,
        attempts=attempts,
    )


class SqliteAnalysisStore:
    _read_only = False

    def __init__(self, path: Path | str) -> None:
        self._path = _checked_path(path)
        parent = self._path.parent
        if not parent.is_dir():
            raise StoreError(f"database directory does not exist: {parent}")
        self._create_private_file()
        with self._connect() as conn:
            self._init_schema(conn)

    @classmethod
    def open_read_only(cls, path: Path | str) -> "SqliteAnalysisStore":
        """A reader that never creates, migrates or writes the database.

        A missing or uninitialised file fails on first use with ``StoreError``, so a wrong
        path is an error rather than an empty result.
        """
        store = cls.__new__(cls)
        store._path = _checked_path(path)
        store._read_only = True
        return store

    def _create_private_file(self) -> None:
        """Create the file owner-only before SQLite does (best effort; Windows ignores modes)."""
        if self._path.exists():
            return
        try:
            os.close(os.open(self._path, os.O_CREAT | os.O_WRONLY, FILE_MODE))
        except OSError as exc:
            raise StoreError(f"cannot create analysis database {self._path}: {exc}") from exc

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise StoreError(f"analysis database {self._path} was written by a newer version")
        conn.execute(_SCHEMA)
        if version < SCHEMA_VERSION:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(analyses)")}
            if "attempts" not in columns:
                conn.execute("ALTER TABLE analyses ADD COLUMN attempts INTEGER NOT NULL DEFAULT 1")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            if self._read_only:
                uri = f"{self._path.as_uri()}?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS)
                connection.execute("PRAGMA query_only = ON")
            else:
                connection = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_SECONDS)
            with closing(connection), connection:  # connection: commit or roll back
                yield connection
        except sqlite3.Error as exc:
            raise StoreError(f"analysis database {self._path}: {exc}") from exc

    def get(self, key: AnalysisKey) -> AnalysisRecord | None:
        params = (key.symbol, key.tf, key.zone_kind, key.zone_low, key.zone_high, key.bar_time)
        with self._connect() as conn:
            row = conn.execute(_SELECT_ONE, params).fetchone()
        return None if row is None else _to_record(row)

    def save(self, record: AnalysisRecord, *, overwrite: bool = False) -> None:
        key = record.key
        params = (
            record.created_at,
            key.symbol,
            key.tf,
            key.zone_kind,
            key.zone_low,
            key.zone_high,
            key.bar_time,
            json.dumps(record.zone, sort_keys=True),
            _dump(record.context),
            _dump(record.verdict),
            record.provider,
            record.model,
            record.prompt_version,
            record.tokens_in,
            record.tokens_out,
            record.cost_estimate,
            record.error,
            int(overwrite),
        )
        with self._connect() as conn:
            conn.execute(_UPSERT, params)

    def list_recent(self, limit: int) -> list[AnalysisRecord]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        limit = min(limit, MAX_LIST_LIMIT)
        with self._connect() as conn:
            rows = conn.execute(_SELECT_RECENT, (limit,)).fetchall()
        return [_to_record(row) for row in rows]

    def get_by_id(self, record_id: int) -> AnalysisRecord | None:
        with self._connect() as conn:
            row = conn.execute(_SELECT_BY_ID, (record_id,)).fetchone()
        return None if row is None else _to_record(row)

    def list_filtered(
        self,
        *,
        symbol: str | None = None,
        action: str | None = None,
        min_confidence: float | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[AnalysisRecord]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        params = (
            symbol,
            symbol,
            action,
            action,
            min_confidence,
            min_confidence,
            before_id,
            before_id,
            min(limit, MAX_LIST_LIMIT),
        )
        with self._connect() as conn:
            rows = conn.execute(_SELECT_FILTERED, params).fetchall()
        return [_to_record(row) for row in rows]
