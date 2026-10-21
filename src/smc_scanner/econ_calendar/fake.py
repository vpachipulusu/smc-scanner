"""A canned calendar source for tests and offline demos: never touches the network."""

from collections.abc import Sequence

from smc_scanner.econ_calendar.models import CalendarEvent


class FakeCalendarSource:
    """Returns the given events, or raises ``error`` when one is given. Counts its calls."""

    def __init__(
        self, events: Sequence[CalendarEvent] = (), *, error: Exception | None = None
    ) -> None:
        self._events = list(events)
        self._error = error
        self.calls = 0

    def fetch(self) -> Sequence[CalendarEvent]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._events)
