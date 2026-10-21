"""Calendar event model, the source Protocol and the snapshot the service returns.

The package is called ``econ_calendar`` so it never shadows the standard library's ``calendar``.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

Impact = Literal["high", "medium", "low", "holiday"]
CalendarStatus = Literal["fresh", "stale", "unavailable"]
ImmediateRisk = Literal["none", "elevated", "high"]

# The currencies the feed may name; an event for any other code is dropped.
CURRENCIES: Final[frozenset[str]] = frozenset(
    {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNY"}
)
MAX_TITLE_CHARS: Final = 200


class CalendarSourceError(Exception):
    """A calendar source could not deliver usable data. The text never carries a response body."""


class CalendarEvent(BaseModel):
    """One scheduled release. ``time`` is always UTC; the numbers are None when unknown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    impact: Impact
    time: AwareDatetime
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None

    @field_validator("currency")
    @classmethod
    def _known_currency(cls, value: str) -> str:
        if value not in CURRENCIES:
            raise ValueError("unknown currency")
        return value

    @field_validator("time")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("actual", "forecast", "previous")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("number must be finite")
        return value


@dataclass(frozen=True)
class CalendarSnapshot:
    """What a read of the calendar produced. ``unavailable`` means no usable data at all."""

    events: tuple[CalendarEvent, ...]
    status: CalendarStatus
    fetched_at: datetime | None


class CalendarSource(Protocol):
    def fetch(self) -> Sequence[CalendarEvent]:
        """The current week's events. Raises ``CalendarSourceError`` on any failure."""
        ...
