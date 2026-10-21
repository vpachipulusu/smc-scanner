"""Shared builders for the economic calendar tests (no network anywhere)."""

from datetime import UTC, datetime, timedelta

from smc_scanner.econ_calendar.models import CalendarEvent, Impact

NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)


def event(
    offset: timedelta,
    *,
    currency: str = "USD",
    impact: Impact = "high",
    title: str = "Non-Farm Payrolls",
    now: datetime = NOW,
) -> CalendarEvent:
    """An event ``offset`` away from ``now`` (negative: already happened)."""
    return CalendarEvent(currency=currency, impact=impact, time=now + offset, title=title)
