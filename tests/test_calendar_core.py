"""Calendar models, symbol-to-currency mapping and the rule-based immediate risk."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from calendar_support import NOW, event
from pydantic import ValidationError

from smc_scanner.econ_calendar.fake import FakeCalendarSource
from smc_scanner.econ_calendar.models import CalendarEvent, CalendarSourceError
from smc_scanner.econ_calendar.risk import (
    ELEVATED_AHEAD,
    HIGH_AFTER,
    HIGH_BEFORE,
    immediate_risk,
)
from smc_scanner.econ_calendar.symbols import currencies_for

H = timedelta(hours=1)
MIN = timedelta(minutes=1)


# --- models --------------------------------------------------------------------------------


def test_event_time_is_normalised_to_utc() -> None:
    zone = timezone(timedelta(hours=-5))
    made = CalendarEvent(
        currency="USD", impact="high", time=datetime(2026, 3, 4, 7, 0, tzinfo=zone), title="CPI"
    )

    assert made.time == datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    assert made.time.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "usd"},
        {"currency": "XXX"},
        {"impact": "critical"},
        {"time": datetime(2026, 3, 4, 7, 0)},  # naive
        {"title": ""},
        {"title": "x" * 201},
        {"forecast": float("nan")},
        {"actual": float("inf")},
        {"surprise": 1},  # unknown field
    ],
)
def test_event_rejects_bad_fields(changes: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "currency": "USD",
        "impact": "high",
        "time": NOW,
        "title": "CPI",
        **changes,
    }

    with pytest.raises(ValidationError):
        CalendarEvent.model_validate(fields)


def test_fake_source_returns_events_and_counts_calls() -> None:
    events = [event(H)]
    source = FakeCalendarSource(events)

    assert list(source.fetch()) == events
    assert source.calls == 1


def test_fake_source_can_fail() -> None:
    source = FakeCalendarSource(error=CalendarSourceError("down"))

    with pytest.raises(CalendarSourceError):
        source.fetch()
    assert source.calls == 1


# --- symbols -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("EURUSD", ("EUR", "USD")),
        ("gbpjpy", ("GBP", "JPY")),
        ("EURUSD.r", ("EUR", "USD")),
        ("EURUSDm", ("EUR", "USD")),
        ("AUDNZD#", ("AUD", "NZD")),
        ("USTEC", ("USD",)),
        ("US500", ("USD",)),
        ("XAUUSD", ("USD",)),
        ("XAGUSD", ("USD",)),
        ("GER40", ("EUR",)),
        ("UK100", ("GBP",)),
        ("JP225", ("JPY",)),
        ("USOIL", ("USD",)),
        ("BTCUSD", ("USD",)),
        ("ABCDEF", ()),
        ("", ()),
        ("EUR", ()),
    ],
)
def test_currencies_for(symbol: str, expected: tuple[str, ...]) -> None:
    assert currencies_for(symbol) == expected


def test_same_currency_pair_is_not_duplicated() -> None:
    assert currencies_for("USDUSD") == ("USD",)


# --- immediate risk ------------------------------------------------------------------------


def risk(*events: CalendarEvent, currencies: tuple[str, ...] = ("USD",)) -> str:
    return immediate_risk(events, currencies, NOW)


def test_constants_are_the_agreed_windows() -> None:
    assert HIGH_BEFORE == 2 * H
    assert HIGH_AFTER == 30 * MIN
    assert ELEVATED_AHEAD == 8 * H


def test_no_events_is_none() -> None:
    assert risk() == "none"


@pytest.mark.parametrize("offset", [-30 * MIN, -MIN, timedelta(0), 30 * MIN, 2 * H])
def test_high_impact_inside_the_window_is_high(offset: timedelta) -> None:
    assert risk(event(offset)) == "high"


@pytest.mark.parametrize("offset", [2 * H + MIN, 5 * H, 8 * H])
def test_high_impact_two_to_eight_hours_ahead_is_elevated(offset: timedelta) -> None:
    assert risk(event(offset)) == "elevated"


@pytest.mark.parametrize("offset", [8 * H + MIN, -31 * MIN, -5 * H, 3 * 24 * H])
def test_high_impact_outside_every_window_is_none(offset: timedelta) -> None:
    assert risk(event(offset)) == "none"


@pytest.mark.parametrize("offset", [-30 * MIN, timedelta(0), 90 * MIN, 2 * H])
def test_medium_impact_within_two_hours_is_elevated(offset: timedelta) -> None:
    assert risk(event(offset, impact="medium")) == "elevated"


@pytest.mark.parametrize("offset", [2 * H + MIN, 5 * H, -31 * MIN])
def test_medium_impact_further_away_is_none(offset: timedelta) -> None:
    assert risk(event(offset, impact="medium")) == "none"


@pytest.mark.parametrize("impact", ["low", "holiday"])
def test_low_and_holiday_are_ignored(impact: str) -> None:
    assert risk(event(timedelta(0), impact=impact)) == "none"  # type: ignore[arg-type]


def test_only_the_symbols_currencies_count() -> None:
    assert risk(event(timedelta(0), currency="JPY")) == "none"
    assert risk(event(timedelta(0), currency="JPY"), currencies=("EUR", "JPY")) == "high"


def test_the_worst_event_wins() -> None:
    soon = event(H, impact="medium")
    later = event(5 * H)
    imminent = event(10 * MIN)

    assert risk(soon, later) == "elevated"
    assert risk(soon, later, imminent) == "high"


def test_no_currencies_means_none() -> None:
    assert risk(event(timedelta(0)), currencies=()) == "none"
