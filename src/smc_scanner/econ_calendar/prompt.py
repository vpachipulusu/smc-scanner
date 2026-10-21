"""The calendar block that goes into the AI verdict context.

Event titles come from an external feed, so they are untrusted text headed for an LLM prompt.
Only a closed set of typed fields is passed on (currency, impact, UTC time, title), the currency
and impact come from allowlists, and a title that does not match ``TITLE_PATTERN`` drops the whole
event rather than being cleaned up. The block also carries two values computed locally (the
feed status and ``immediate_risk``). The system prompt labels all of it as data, not instructions.
"""

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, TypedDict

from smc_scanner.econ_calendar.models import (
    CURRENCIES,
    CalendarEvent,
    CalendarSnapshot,
    CalendarStatus,
    ImmediateRisk,
)
from smc_scanner.econ_calendar.risk import ELEVATED_AHEAD, immediate_risk

MAX_PROMPT_EVENTS: Final = 5
PROMPT_BEFORE: Final = timedelta(hours=1)  # a release that just happened still matters
PROMPT_AHEAD: Final = ELEVATED_AHEAD
TITLE_PATTERN: Final = re.compile(r"[A-Za-z0-9 .,%()/&'-]{1,80}")
_IMPACT_RANK: Final = {"high": 0, "medium": 1}


class CalendarEventContext(TypedDict):
    currency: str
    impact: Literal["high", "medium"]
    time: str
    title: str


class CalendarContext(TypedDict):
    status: CalendarStatus
    immediate_risk: ImmediateRisk
    events: list[CalendarEventContext]


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(item: CalendarEvent, currencies: frozenset[str], now: datetime) -> bool:
    return (
        item.currency in CURRENCIES
        and item.currency in currencies
        and item.impact in _IMPACT_RANK
        and -PROMPT_BEFORE <= item.time - now <= PROMPT_AHEAD
        and TITLE_PATTERN.fullmatch(item.title) is not None
    )


def _context(item: CalendarEvent) -> CalendarEventContext:
    impact: Literal["high", "medium"] = "high" if item.impact == "high" else "medium"
    return CalendarEventContext(
        currency=item.currency, impact=impact, time=_utc_text(item.time), title=item.title
    )


def calendar_block(
    snapshot: CalendarSnapshot, currencies: Iterable[str], now: datetime
) -> CalendarContext | None:
    """The block for an instrument exposed to ``currencies``, or None when there is nothing
    trustworthy to say: the calendar is unavailable or the symbol maps to no currency."""
    wanted = frozenset(currencies)
    if snapshot.status == "unavailable" or not wanted:
        return None
    chosen = sorted(
        (item for item in snapshot.events if _safe(item, wanted, now)),
        key=lambda item: (_IMPACT_RANK[item.impact], item.time, item.currency, item.title),
    )[:MAX_PROMPT_EVENTS]
    return CalendarContext(
        status=snapshot.status,
        immediate_risk=immediate_risk(snapshot.events, wanted, now),
        events=[_context(item) for item in chosen],
    )
