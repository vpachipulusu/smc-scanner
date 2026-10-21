"""ForexFactory's public weekly JSON feed as a ``CalendarSource``.

The URL is a constant: nothing a caller or the feed supplies ever becomes a request target
(no SSRF), redirects are not followed, the body size is capped and the timeout is short. Every
row is validated against ``CalendarEvent``; rows that fail are dropped. Response bodies are never
logged and never appear in an error message.
"""

import json
import logging
import math
import re
from collections.abc import Sequence
from datetime import datetime
from time import monotonic
from typing import Any, Final

import httpx
from pydantic import ValidationError

from smc_scanner.econ_calendar.models import CalendarEvent, CalendarSourceError

log = logging.getLogger(__name__)

FEED_URL: Final = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TIMEOUT_SECONDS: Final = 3.0
MAX_BODY_BYTES: Final = 2_000_000
MAX_ROWS: Final = 1000
TOTAL_DEADLINE_SECONDS: Final = 6.0  # the timeout is per operation; this bounds a slow drip
_HTTP_OK: Final = 200
_NUMBER: Final = re.compile(r"[-+]?\d+(?:\.\d+)?[KMBT]?%?")
_MULTIPLIERS: Final = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_number(raw: object) -> float | None:
    """A feed figure such as ``0.2%``, ``160K`` or ``1.5M`` as a float; None when it is not one."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        number = float(raw)
        return number if math.isfinite(number) else None
    if not isinstance(raw, str):
        return None
    text = raw.strip().upper()
    if not _NUMBER.fullmatch(text):
        return None
    text = text.removesuffix("%")
    multiplier = _MULTIPLIERS.get(text[-1], 1.0)
    return float(text[:-1] if text[-1] in _MULTIPLIERS else text) * multiplier


def _row_to_event(row: object) -> CalendarEvent | None:
    if not isinstance(row, dict):
        return None
    when = row.get("date")
    impact = row.get("impact")
    if not isinstance(when, str) or not isinstance(impact, str):
        return None
    try:
        return CalendarEvent(
            currency=row.get("country"),  # type: ignore[arg-type]  # validated below
            impact=impact.strip().lower(),  # type: ignore[arg-type]
            time=datetime.fromisoformat(when),
            title=row.get("title"),  # type: ignore[arg-type]
            actual=parse_number(row.get("actual")),
            forecast=parse_number(row.get("forecast")),
            previous=parse_number(row.get("previous")),
        )
    except (ValidationError, ValueError):
        return None


def parse_feed(payload: object) -> list[CalendarEvent]:
    """The valid events of a decoded feed. Raises ``CalendarSourceError`` if it is not a list."""
    if not isinstance(payload, list):
        raise CalendarSourceError("calendar feed is not a list")
    rows: list[Any] = payload[:MAX_ROWS]
    events = [item for item in map(_row_to_event, rows) if item is not None]
    if rows and not events:
        raise CalendarSourceError("calendar feed has no valid rows")
    dropped = len(rows) - len(events)
    if dropped:
        log.info("calendar feed: %d of %d rows dropped as invalid", dropped, len(rows))
    return events


class ForexFactoryCalendarSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,  # no proxy or CA bundle from the environment
            headers={"Accept": "application/json"},
        )

    def fetch(self) -> Sequence[CalendarEvent]:
        try:
            with self._client.stream("GET", FEED_URL) as response:
                if response.status_code != _HTTP_OK:
                    raise CalendarSourceError(f"calendar feed returned HTTP {response.status_code}")
                body = self._read_capped(response)
        except httpx.HTTPError as exc:
            raise CalendarSourceError(f"calendar feed unreachable: {type(exc).__name__}") from None
        try:
            payload = json.loads(body)
        except (
            ValueError,
            RecursionError,
        ):  # includes UnicodeDecodeError; the text may echo the body, so drop it
            raise CalendarSourceError("calendar feed is not valid JSON") from None
        return parse_feed(payload)

    @staticmethod
    def _read_capped(response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        deadline = monotonic() + TOTAL_DEADLINE_SECONDS
        for chunk in response.iter_bytes():
            if monotonic() > deadline:
                raise CalendarSourceError("calendar feed is too slow")
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise CalendarSourceError("calendar feed is too large")
            chunks.append(chunk)
        return b"".join(chunks)
