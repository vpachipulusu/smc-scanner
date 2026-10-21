"""``GET /calendar``: upcoming economic events and the immediate risk for one symbol."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query

from smc_scanner.api.calendar_schemas import CalendarEventOut, CalendarResponse
from smc_scanner.api.constants import (
    CALENDAR_PAST_HOURS,
    DEFAULT_CALENDAR_HOURS,
    MAX_CALENDAR_EVENTS,
    MAX_CALENDAR_HOURS,
    SYMBOL_PATTERN,
)
from smc_scanner.api.deps import CalendarRateDep, CalendarServiceDep, InternalKeyDep
from smc_scanner.api.schemas import RETRY_AFTER_HEADER, ErrorResponse
from smc_scanner.econ_calendar.models import CalendarSnapshot
from smc_scanner.econ_calendar.risk import immediate_risk
from smc_scanner.econ_calendar.service import CalendarService
from smc_scanner.econ_calendar.symbols import currencies_for

log = logging.getLogger(__name__)
router = APIRouter(tags=["calendar"])

CALENDAR_ERRORS: dict[int | str, dict[str, Any]] = {
    429: {
        "model": ErrorResponse,
        "description": "Too many requests; see the Retry-After header",
        "headers": RETRY_AFTER_HEADER,
    },
}


def _snapshot(service: CalendarService, now: datetime) -> CalendarSnapshot:
    """The calendar as of ``now``; a failure is ``unavailable``, never an error response."""
    try:
        return service.snapshot(now)
    except Exception as exc:  # noqa: BLE001 - the calendar must never take the API down
        log.warning("calendar unavailable: %s", type(exc).__name__, exc_info=True)
        return CalendarSnapshot((), "unavailable", None)


@router.get("/calendar", response_model=CalendarResponse, responses=CALENDAR_ERRORS)
def get_calendar(
    _: InternalKeyDep,
    __: CalendarRateDep,
    service: CalendarServiceDep,
    symbol: Annotated[
        str,
        Query(
            min_length=1,
            max_length=32,
            pattern=SYMBOL_PATTERN.pattern,
            description="FX pair, index or metal, e.g. EURUSD, USTEC, XAUUSD",
        ),
    ],
    hours: Annotated[
        int, Query(ge=1, le=MAX_CALENDAR_HOURS, description="how many hours ahead to list events")
    ] = DEFAULT_CALENDAR_HOURS,
) -> CalendarResponse:
    """Economic events for the currencies that move ``symbol`` (an FX pair such as ``EURUSD``,
    or an index or metal such as ``USTEC`` or ``XAUUSD``), plus a rule-based ``immediate_risk``.

    The feed is cached and refreshed at most hourly. If it cannot be reached the cached week is
    returned as ``stale``, or an empty ``unavailable`` answer; the status is 200 either way.
    """
    now = datetime.now(UTC)
    currencies = currencies_for(symbol)
    snapshot = _snapshot(service, now)
    start = now - timedelta(hours=CALENDAR_PAST_HOURS)
    end = now + timedelta(hours=hours)
    shown = [
        item
        for item in snapshot.events
        if item.currency in currencies and start <= item.time <= end
    ]
    shown.sort(key=lambda item: (item.time, item.currency, item.title))
    return CalendarResponse(
        symbol=symbol,
        currencies=list(currencies),
        calendar_status=snapshot.status,
        immediate_risk=immediate_risk(snapshot.events, currencies, now),
        as_of=now,
        fetched_at=snapshot.fetched_at,
        window_hours=hours,
        events=[CalendarEventOut(**item.model_dump()) for item in shown[:MAX_CALENDAR_EVENTS]],
    )
