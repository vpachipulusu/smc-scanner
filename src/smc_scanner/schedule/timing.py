"""When a schedule next runs: the close of the next candle plus a few seconds' grace.

Candle grid
    15m and 1h candles always close on the UTC grid (:00/:15/:30/:45 and on the hour); whole-hour
    broker offsets do not move them. 4h and 1d candles close on the *broker server's* wall clock:
    4h at 00:00, 04:00, ... and 1d at 00:00 server time. ``SERVER_ZONE`` is that clock as a real
    IANA zone, so daylight-saving changes are followed (a US-DST broker such as New York close
    differs from an EU-DST one, and a fixed UTC offset cannot represent either). The default is
    UTC; set ``SMC_SERVER_TZ`` (see ``server_zone_from_env``) to your broker's zone, e.g.
    ``Europe/Athens``, before relying on 4h/1d schedules. Across a DST change the bar that spans
    it is 1 hour shorter or longer, exactly as on the wall clock. On Windows the ``tzdata``
    package supplies the zone database.

Missed runs: the next slot is always computed from "now", never from the previous slot, so a
service that was down for nine hours runs once on its first tick and then rejoins the grid. It
does not replay nine runs.

Every function takes the moment as an argument, so tests drive time with a fake clock.
"""

import os
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FREQUENCY_SECONDS: Final[dict[str, int]] = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}
FREQUENCIES: Final[tuple[str, ...]] = tuple(FREQUENCY_SECONDS)

GRACE: Final = timedelta(seconds=5)  # let the broker publish the closed bar before scanning
SERVER_ZONE: Final[tzinfo] = UTC  # broker server clock for 4h/1d; see module docstring
SERVER_TZ_ENV: Final = "SMC_SERVER_TZ"
_WALL_CLOCK_FREQUENCIES: Final = {"4h": 4, "1d": 24}  # hours between wall-clock boundaries

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _period(frequency: str) -> timedelta:
    try:
        return timedelta(seconds=FREQUENCY_SECONDS[frequency])
    except KeyError:
        raise ValueError(
            f"unknown frequency {frequency!r}; expected one of {', '.join(FREQUENCIES)}"
        ) from None


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("moment must be a timezone-aware datetime")
    return moment.astimezone(UTC)


def server_zone_from_env() -> tzinfo:
    """The zone named by SMC_SERVER_TZ (blank or unset means UTC); ValueError if unknown."""
    name = os.environ.get(SERVER_TZ_ENV, "").strip()
    if not name:
        return SERVER_ZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"{SERVER_TZ_ENV} {name!r} is not a known time zone") from None


def _wall_clock_close(moment: datetime, step_hours: int, zone: tzinfo) -> datetime:
    """First server-wall-clock boundary (every ``step_hours`` from 00:00) after ``moment``."""
    today = moment.astimezone(zone).date()
    for day in range(2):
        date = today + timedelta(days=day)
        for hour in range(0, 24, step_hours):
            candidate = datetime.combine(date, time(hour), tzinfo=zone).astimezone(UTC)
            if candidate > moment:
                return candidate
    raise AssertionError("unreachable: tomorrow 00:00 is always later")  # pragma: no cover


def candle_close_after(moment: datetime, frequency: str, zone: tzinfo = SERVER_ZONE) -> datetime:
    """The first candle close strictly after ``moment`` as an aware UTC datetime.

    15m/1h follow the UTC grid. 4h/1d follow ``zone``'s wall clock (DST-aware); the default
    ``SERVER_ZONE`` is UTC. A moment exactly on a close returns the following close.
    """
    period = _period(frequency)
    instant = _aware(moment)
    step = _WALL_CLOCK_FREQUENCIES.get(frequency)
    if step is not None:
        return _wall_clock_close(instant, step, zone)
    return _EPOCH + (instant - _EPOCH) // period * period + period


def next_run_after(
    moment: datetime,
    frequency: str,
    *,
    grace: timedelta = GRACE,
    zone: tzinfo = SERVER_ZONE,
) -> datetime:
    """The first run slot (candle close + ``grace``) strictly after ``moment``."""
    return candle_close_after(_aware(moment) - grace, frequency, zone) + grace


def is_due(next_run_at: datetime | None, now: datetime) -> bool:
    """True once a scheduled slot has arrived; an unscheduled (None) slot is never due."""
    return next_run_at is not None and _aware(next_run_at) <= _aware(now)


def missed_slots(next_run_at: datetime, now: datetime, frequency: str) -> int:
    """Whole periods that passed since ``next_run_at`` (for logging; they are not replayed)."""
    late = _aware(now) - _aware(next_run_at)
    return max(0, late // _period(frequency))
