"""Request and response models of the schedule, job log and Telegram routes."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field

from smc_scanner.api.constants import (
    _OMITTED,
    CHAT_ID_REGEX,
    DEFAULT_SCHEDULE_MIN_SCORE,
    MAX_AI_MIN_SCORE,
    MAX_CURSOR_CHARS,
    MAX_LABEL_CHARS,
    MAX_ROW_ID,
    MAX_SYMBOLS,
    SYMBOL_PATTERN,
)
from smc_scanner.config import (
    ApiSource,
    Timeframe,
)
from smc_scanner.schedule.joblog import (
    MAX_ERROR_CHARS as MAX_JOB_ERROR_CHARS,
)
from smc_scanner.schedule.joblog import (
    JobLogEntry,
    JobStatus,
)
from smc_scanner.schedule.store import (
    MAX_CONFIDENCE,
    MAX_NAME_CHARS,
    Schedule,
)

ScheduleId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]
Frequency = Literal["15m", "1h", "4h", "1d"]  # kept equal to timing.FREQUENCIES by a test
SymbolName = Annotated[str, Field(pattern=SYMBOL_PATTERN.pattern)]
ChatId = Annotated[str, Field(pattern=CHAT_ID_REGEX)]
Symbols = Annotated[list[SymbolName], Field(min_length=1, max_length=MAX_SYMBOLS)]


class ScheduleCreate(BaseModel):
    """A new schedule. Every field but the first five has a default."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    source: ApiSource
    tf: Timeframe
    symbols: Symbols
    frequency: Frequency
    min_score: int = Field(default=DEFAULT_SCHEDULE_MIN_SCORE, ge=0, le=MAX_AI_MIN_SCORE)
    min_confidence: float = Field(default=0.0, ge=0, le=MAX_CONFIDENCE)
    only_on_change: bool = False
    send_hold: bool = False
    enabled: bool = True
    telegram_chat_id: ChatId | None = None


class ScheduleUpdate(BaseModel):
    """Any subset of the editable fields. Only ``telegram_chat_id`` may be null (it clears it)."""

    model_config = ConfigDict(extra="forbid")

    # Omittable but not nullable (the schema says so); an absent field is simply not in
    # ``model_fields_set``, so the ``_OMITTED`` default is never read.
    name: str = Field(default=_OMITTED, min_length=1, max_length=MAX_NAME_CHARS)
    source: ApiSource = _OMITTED
    tf: Timeframe = _OMITTED
    symbols: Symbols = _OMITTED
    frequency: Frequency = _OMITTED
    min_score: int = Field(default=_OMITTED, ge=0, le=MAX_AI_MIN_SCORE)
    min_confidence: float = Field(default=_OMITTED, ge=0, le=MAX_CONFIDENCE)
    only_on_change: bool = _OMITTED
    send_hold: bool = _OMITTED
    enabled: bool = _OMITTED
    telegram_chat_id: ChatId | None = None


class ScheduleOut(BaseModel):
    id: int
    name: str
    source: ApiSource
    tf: Timeframe
    symbols: list[str]
    frequency: Frequency
    min_score: int
    min_confidence: float
    only_on_change: bool
    send_hold: bool
    enabled: bool
    telegram_chat_id: str | None
    last_run_at: str | None = Field(max_length=MAX_LABEL_CHARS)
    next_run_at: str | None = Field(max_length=MAX_LABEL_CHARS)

    @classmethod
    def from_schedule(cls, schedule: Schedule) -> "ScheduleOut":
        return cls.model_validate(
            {
                **schedule.__dict__,
                "id": schedule.id or 0,
                "symbols": list(schedule.symbols),
                "last_run_at": _iso_or_none(schedule.last_run_at),
                "next_run_at": _iso_or_none(schedule.next_run_at),
            }
        )


class ScheduleList(BaseModel):
    items: list[ScheduleOut]


class DeleteResponse(BaseModel):
    deleted: Literal[True] = True


class RunOut(BaseModel):
    """What a run-now did. Error text is never returned here; see the job log."""

    status: Literal["ok", "failed"]
    rows: int
    delivered: int
    skipped: int
    error_count: int


class JobLogOut(BaseModel):
    """One job-log row. ``error`` is raw text (already redacted and bounded): render it as
    text, never as markup."""

    id: int
    schedule_id: int
    started_at: str = Field(max_length=MAX_LABEL_CHARS)
    finished_at: str = Field(max_length=MAX_LABEL_CHARS)
    duration_ms: int
    status: JobStatus
    hits: int
    delivered: int
    skipped: int
    skip_reason: str | None = Field(max_length=MAX_LABEL_CHARS)
    error: str | None = Field(max_length=MAX_JOB_ERROR_CHARS)

    @classmethod
    def from_entry(cls, entry: JobLogEntry) -> "JobLogOut":
        return cls(
            id=entry.id or 0,
            schedule_id=entry.schedule_id,
            started_at=entry.started_at.isoformat(),
            finished_at=entry.finished_at.isoformat(),
            duration_ms=entry.duration_ms,
            status=entry.status,
            hits=entry.hits,
            delivered=entry.delivered,
            skipped=entry.skipped,
            skip_reason=None if entry.skip_reason is None else _clip(entry.skip_reason),
            error=None if entry.error is None else _clip(entry.error, MAX_JOB_ERROR_CHARS),
        )


class JobLogPage(BaseModel):
    items: list[JobLogOut]
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)


class TelegramTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: ChatId | None = Field(default=None, description="default: TELEGRAM_CHAT_ID")


class TelegramTestResponse(BaseModel):
    sent: Literal[True] = True


def _iso_or_none(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()
