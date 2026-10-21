"""ForexFactory feed parsing and fetching, over httpx.MockTransport (no network)."""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from smc_scanner.econ_calendar.forexfactory import (
    FEED_URL,
    MAX_BODY_BYTES,
    TIMEOUT_SECONDS,
    ForexFactoryCalendarSource,
    parse_feed,
    parse_number,
)
from smc_scanner.econ_calendar.models import CalendarSourceError

ROW = {
    "title": "Non-Farm Employment Change",
    "country": "USD",
    "date": "2026-03-06T08:30:00-05:00",
    "impact": "High",
    "forecast": "160K",
    "previous": "143K",
}


def _source(handler: Any) -> ForexFactoryCalendarSource:
    return ForexFactoryCalendarSource(httpx.Client(transport=httpx.MockTransport(handler)))


def _json(payload: object) -> Any:
    return lambda request: httpx.Response(200, json=payload)


# --- numbers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.2%", 0.2),
        ("-0.4%", -0.4),
        ("160K", 160_000.0),
        ("1.5M", 1_500_000.0),
        ("2.3B", 2_300_000_000.0),
        ("1.1T", 1_100_000_000_000.0),
        ("52.1", 52.1),
        (" 3 ", 3.0),
        ("", None),
        ("   ", None),
        ("n/a", None),
        ("1.8|2.4", None),
        ("<0.1%", None),
        ("nan", None),
        ("inf", None),
        ("1e999", None),
        (None, None),
        (5, 5.0),
        (True, None),
        ([1], None),
    ],
)
def test_parse_number(text: object, expected: float | None) -> None:
    assert parse_number(text) == expected


# --- feed parsing --------------------------------------------------------------------------


def test_parse_feed_builds_utc_events() -> None:
    [parsed] = parse_feed([ROW])

    assert parsed.currency == "USD" and parsed.impact == "high"
    assert parsed.time == datetime(2026, 3, 6, 13, 30, tzinfo=UTC)
    assert parsed.title == "Non-Farm Employment Change"
    assert parsed.forecast == 160_000.0 and parsed.previous == 143_000.0
    assert parsed.actual is None


@pytest.mark.parametrize("impact", ["High", "Medium", "Low", "Holiday"])
def test_parse_feed_maps_every_impact(impact: str) -> None:
    [parsed] = parse_feed([{**ROW, "impact": impact}])

    assert parsed.impact == impact.lower()


@pytest.mark.parametrize(
    "bad",
    [
        {**ROW, "country": "XXX"},
        {**ROW, "country": "usd"},
        {**ROW, "impact": "Extreme"},
        {**ROW, "date": "not a date"},
        {**ROW, "date": "2026-03-06T08:30:00"},  # naive
        {**ROW, "date": 5},
        {**ROW, "title": ""},
        {**ROW, "title": "t" * 500},
        {**ROW, "title": 5},
        {k: v for k, v in ROW.items() if k != "title"},
        "a string",
        5,
        None,
        [],
    ],
)
def test_parse_feed_drops_invalid_rows_and_keeps_the_rest(bad: object) -> None:
    parsed = parse_feed([bad, ROW])

    assert len(parsed) == 1 and parsed[0].title == ROW["title"]


def test_parse_feed_ignores_unknown_extra_keys() -> None:
    assert len(parse_feed([{**ROW, "url": "https://evil.example", "x": 1}])) == 1


def test_parse_feed_rejects_a_non_list_payload() -> None:
    with pytest.raises(CalendarSourceError):
        parse_feed({"events": [ROW]})


def test_parse_feed_caps_the_row_count() -> None:
    parsed = parse_feed([ROW] * 5000)

    assert len(parsed) <= 1000


# --- fetching ------------------------------------------------------------------------------


def test_fetch_requests_the_fixed_feed_url_with_a_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[ROW])

    events = _source(handler).fetch()

    assert len(events) == 1
    [request] = seen
    assert str(request.url) == FEED_URL == "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    assert request.method == "GET"
    assert TIMEOUT_SECONDS == 3.0


def test_default_client_has_the_timeout_and_no_redirects() -> None:
    source = ForexFactoryCalendarSource()

    assert source._client.timeout.read == TIMEOUT_SECONDS  # noqa: SLF001
    assert source._client.follow_redirects is False  # noqa: SLF001


@pytest.mark.parametrize("status", [301, 302, 403, 429, 500, 503])
def test_fetch_raises_on_a_bad_status(status: int) -> None:
    with pytest.raises(CalendarSourceError):
        _source(lambda request: httpx.Response(status, text="no")).fetch()


def test_fetch_raises_on_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(CalendarSourceError):
        _source(handler).fetch()


@pytest.mark.parametrize("body", [b"not json", b"{}", b'"x"', b"null", b"\xff\xfe"])
def test_fetch_raises_on_a_malformed_body(body: bytes) -> None:
    with pytest.raises(CalendarSourceError):
        _source(lambda request: httpx.Response(200, content=body)).fetch()


def test_fetch_refuses_an_oversized_body() -> None:
    big = b"[" + b" " * (MAX_BODY_BYTES + 1) + b"]"

    with pytest.raises(CalendarSourceError):
        _source(lambda request: httpx.Response(200, content=big)).fetch()


def test_errors_and_logs_never_carry_the_response_body(caplog: pytest.LogCaptureFixture) -> None:
    secret = "SECRET-BODY-TEXT"
    caplog.set_level(logging.DEBUG)

    with pytest.raises(CalendarSourceError) as info:
        _source(lambda request: httpx.Response(200, text=secret)).fetch()

    assert secret not in str(info.value)
    assert secret not in caplog.text
    with pytest.raises(CalendarSourceError) as again:
        _source(lambda request: httpx.Response(500, text=secret)).fetch()
    assert secret not in str(again.value)
    assert secret not in caplog.text


def test_a_feed_where_no_row_is_valid_is_a_failure_not_an_empty_week() -> None:
    with pytest.raises(CalendarSourceError):
        parse_feed([{"nonsense": 1}, "x"])
    assert parse_feed([]) == []


def test_deeply_nested_json_is_a_source_error() -> None:
    body = b"[" * 100_000 + b"]" * 100_000

    with pytest.raises(CalendarSourceError):
        _source(lambda request: httpx.Response(200, content=body)).fetch()


def test_a_slow_drip_hits_the_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from smc_scanner.econ_calendar import forexfactory

    clock = iter([0.0, 100.0, 200.0])
    monkeypatch.setattr(forexfactory, "monotonic", lambda: next(clock))

    with pytest.raises(CalendarSourceError):
        _source(lambda request: httpx.Response(200, content=b"[]")).fetch()
