"""Response models for ``GET /calendar``."""

from datetime import datetime

from pydantic import BaseModel, Field

from smc_scanner.econ_calendar.models import CalendarStatus, ImmediateRisk, Impact


class CalendarEventOut(BaseModel):
    """One scheduled release. Figures are null when the feed has none (yet)."""

    currency: str = Field(description="Three-letter currency code, e.g. USD")
    impact: Impact
    time: datetime = Field(description="When it is released, in UTC")
    title: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None


class CalendarResponse(BaseModel):
    """Upcoming events for one symbol's currencies, with the calendar's health and the
    rule-based ``immediate_risk``. The call succeeds even when the feed is down: see
    ``calendar_status``."""

    symbol: str
    currencies: list[str] = Field(
        description="Currencies that move the symbol; empty when the symbol is not recognised"
    )
    calendar_status: CalendarStatus = Field(
        description="fresh: cache under an hour old or just fetched; stale: the feed failed and "
        "an older cache is shown; unavailable: no data at all"
    )
    immediate_risk: ImmediateRisk = Field(
        description="high: a high-impact event from 30 minutes ago to 2 hours ahead; elevated: a "
        "high-impact event 2-8 hours ahead or a medium-impact one in that same window; none "
        "otherwise. Computed from every cached event, whatever ``hours`` is"
    )
    as_of: datetime = Field(description="The time the response was computed for, in UTC")
    fetched_at: datetime | None = Field(
        description="When the shown data was fetched from the feed; null when unavailable"
    )
    window_hours: int = Field(description="How far ahead of ``as_of`` events are listed")
    events: list[CalendarEventOut] = Field(
        description="Events in the window, oldest first: from two hours before ``as_of`` to "
        "``window_hours`` after, for the symbol's currencies, at most 200"
    )
