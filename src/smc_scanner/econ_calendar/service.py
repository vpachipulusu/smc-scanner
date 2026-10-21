"""Cached, failure-proof access to the calendar: fresh, stale or unavailable, never an exception.

A snapshot is served from the database while it is younger than ``REFRESH_INTERVAL``. After that
the source is asked again; if it fails the cached week is returned as ``stale`` (up to
``MAX_STALE`` old) and the failure is remembered in memory for ``RETRY_BACKOFF`` so a dead feed
costs one short timeout per backoff, not one per request. A calendar problem must never block a
scan or an analysis, so nothing here raises.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Final, Protocol

from smc_scanner.econ_calendar.models import (
    CalendarEvent,
    CalendarSnapshot,
    CalendarSource,
)
from smc_scanner.econ_calendar.store import StoredCalendar

log = logging.getLogger(__name__)

REFRESH_INTERVAL: Final = timedelta(hours=1)
MAX_STALE: Final = timedelta(days=7)
RETRY_BACKOFF: Final = timedelta(seconds=60)


class CalendarCache(Protocol):
    def load(self) -> StoredCalendar: ...

    def replace(self, events: list[CalendarEvent], fetched_at: datetime) -> None: ...


class CalendarService:
    def __init__(self, source: CalendarSource, cache: CalendarCache) -> None:
        self._source = source
        self._cache = cache
        self._lock = threading.Lock()  # one fetch at a time; the rest wait and reuse its result
        self._failed_at: datetime | None = None

    def snapshot(self, now: datetime) -> CalendarSnapshot:
        """The calendar as of ``now`` (an aware datetime)."""
        cached = self._load()
        if self._is_current(cached, now):  # the common case takes no lock
            return CalendarSnapshot(cached.events, "fresh", cached.fetched_at)
        with self._lock:
            cached = self._load()  # another thread may have refreshed while we waited
            if self._is_current(cached, now):
                return CalendarSnapshot(cached.events, "fresh", cached.fetched_at)
            if self._failed_at is None or now - self._failed_at >= RETRY_BACKOFF:
                events = self._fetch()
                if events is not None:
                    self._failed_at = None
                    self._save(events, now)
                    return CalendarSnapshot(tuple(events), "fresh", now)
                self._failed_at = now
            return self._fallback(cached, now)

    def _load(self) -> StoredCalendar:
        try:
            return self._cache.load()
        except Exception as exc:  # noqa: BLE001 - a broken cache must not break the caller
            log.warning("calendar cache unreadable: %s", type(exc).__name__)
            return StoredCalendar((), None)

    def _save(self, events: list[CalendarEvent], fetched_at: datetime) -> None:
        try:
            self._cache.replace(events, fetched_at)
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar cache not saved: %s", type(exc).__name__)

    def _fetch(self) -> list[CalendarEvent] | None:
        try:
            return list(self._source.fetch())
        except Exception as exc:  # noqa: BLE001 - any source failure just means "no new data"
            log.warning("calendar fetch failed: %s", type(exc).__name__)
            return None

    @staticmethod
    def _is_current(cached: StoredCalendar, now: datetime) -> bool:
        fetched = cached.fetched_at
        return fetched is not None and timedelta(0) <= now - fetched < REFRESH_INTERVAL

    @staticmethod
    def _fallback(cached: StoredCalendar, now: datetime) -> CalendarSnapshot:
        fetched = cached.fetched_at
        if fetched is None or now - fetched > MAX_STALE:
            return CalendarSnapshot((), "unavailable", None)
        return CalendarSnapshot(cached.events, "stale", fetched)
