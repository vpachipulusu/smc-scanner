"""Rule-based immediate risk around scheduled releases. No model is involved.

``high``: a high-impact event for one of the symbol's currencies is at most ``HIGH_BEFORE``
away in the future or happened at most ``HIGH_AFTER`` ago. ``elevated``: a high-impact event
is further ahead, up to ``ELEVATED_AHEAD``, or a medium-impact event sits in the ``high``
window. Low-impact events and holidays are ignored.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Final

from smc_scanner.econ_calendar.models import CalendarEvent, ImmediateRisk

HIGH_BEFORE: Final = timedelta(hours=2)
HIGH_AFTER: Final = timedelta(minutes=30)
ELEVATED_AHEAD: Final = timedelta(hours=8)


def immediate_risk(
    events: Iterable[CalendarEvent], currencies: Iterable[str], now: datetime
) -> ImmediateRisk:
    """The worst risk any of ``events`` poses to an instrument exposed to ``currencies``."""
    wanted = frozenset(currencies)
    risk: ImmediateRisk = "none"
    for item in events:
        if item.currency not in wanted or item.impact not in ("high", "medium"):
            continue
        offset = item.time - now
        if -HIGH_AFTER <= offset <= HIGH_BEFORE:
            if item.impact == "high":
                return "high"
            risk = "elevated"
        elif item.impact == "high" and HIGH_BEFORE < offset <= ELEVATED_AHEAD:
            risk = "elevated"
    return risk
