"""Economic calendar: events, rule-based risk, a cached feed and the AI prompt block."""

from smc_scanner.econ_calendar.models import (
    CalendarEvent,
    CalendarSnapshot,
    CalendarSource,
    CalendarSourceError,
)
from smc_scanner.econ_calendar.risk import immediate_risk
from smc_scanner.econ_calendar.service import CalendarService
from smc_scanner.econ_calendar.symbols import currencies_for

__all__ = [
    "CalendarEvent",
    "CalendarService",
    "CalendarSnapshot",
    "CalendarSource",
    "CalendarSourceError",
    "currencies_for",
    "immediate_risk",
]
