"""GET /calendar: window, risk, status, validation, key, rate limit and failure containment."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from calendar_support import event
from fastapi.testclient import TestClient

from smc_scanner.api import RATE_LIMITERS, app
from smc_scanner.api.deps import get_calendar_service
from smc_scanner.econ_calendar.fake import FakeCalendarSource
from smc_scanner.econ_calendar.models import CalendarSourceError
from smc_scanner.econ_calendar.service import CalendarService
from smc_scanner.econ_calendar.store import SqliteCalendarStore
from smc_scanner.ratelimit import RateLimiter

client = TestClient(app, base_url="http://localhost")
H = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(UTC)


def _use(tmp_path: Path, source: FakeCalendarSource) -> CalendarService:
    service = CalendarService(source, SqliteCalendarStore(tmp_path / "smc.db"))
    app.dependency_overrides[get_calendar_service] = lambda: service
    return service


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    yield
    app.dependency_overrides.clear()


def _get(**params: Any) -> Any:
    return client.get("/calendar", params={"symbol": "EURUSD", **params})


def test_returns_events_for_the_symbols_currencies_with_risk(tmp_path: Path) -> None:
    now = _now()
    _use(
        tmp_path,
        FakeCalendarSource(
            [
                event(H, now=now),
                event(3 * H, currency="EUR", impact="medium", title="CPI y/y", now=now),
                event(H, currency="JPY", now=now),
                event(48 * H, now=now),
            ]
        ),
    )

    response = _get()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "EURUSD" and body["currencies"] == ["EUR", "USD"]
    assert body["calendar_status"] == "fresh" and body["immediate_risk"] == "high"
    assert body["window_hours"] == 24
    assert [e["currency"] for e in body["events"]] == ["USD", "EUR"]
    assert set(body["events"][0]) == {
        "currency",
        "impact",
        "time",
        "title",
        "actual",
        "forecast",
        "previous",
    }
    assert body["events"][0]["time"].endswith("Z") or "+00:00" in body["events"][0]["time"]
    assert body["fetched_at"] is not None and body["as_of"] is not None


def test_hours_widens_the_window_but_not_the_risk(tmp_path: Path) -> None:
    now = _now()
    _use(tmp_path, FakeCalendarSource([event(48 * H, now=now)]))

    assert _get().json()["events"] == []
    wide = _get(hours=72).json()

    assert len(wide["events"]) == 1 and wide["immediate_risk"] == "none"


def test_unknown_symbol_has_no_currencies_and_no_events(tmp_path: Path) -> None:
    _use(tmp_path, FakeCalendarSource([event(H, now=_now())]))

    body = _get(symbol="ZZZZ").json()

    assert body["currencies"] == [] and body["events"] == []
    assert body["immediate_risk"] == "none"


def test_unavailable_calendar_is_a_200_with_status(tmp_path: Path) -> None:
    _use(tmp_path, FakeCalendarSource(error=CalendarSourceError("down")))

    response = _get()

    assert response.status_code == 200
    body = response.json()
    assert body["calendar_status"] == "unavailable" and body["events"] == []
    assert body["immediate_risk"] == "none" and body["fetched_at"] is None


def test_stale_cache_is_served_with_stale_status(tmp_path: Path) -> None:
    now = _now()
    store = SqliteCalendarStore(tmp_path / "smc.db")
    store.replace([event(H, now=now)], now - 3 * H)
    _use(tmp_path, FakeCalendarSource(error=CalendarSourceError("down")))

    body = _get().json()

    assert body["calendar_status"] == "stale" and len(body["events"]) == 1


def test_a_failing_service_dependency_still_returns_200(tmp_path: Path) -> None:
    class Exploding:
        def snapshot(self, now: datetime) -> None:
            raise RuntimeError("boom")

    app.dependency_overrides[get_calendar_service] = lambda: Exploding()

    response = _get()

    assert response.status_code == 200
    assert response.json()["calendar_status"] == "unavailable"


@pytest.mark.parametrize(
    "params",
    [
        {"symbol": ""},
        {"symbol": "A" * 33},
        {"symbol": "bad symbol!"},
        {"symbol": "EURUSD", "hours": 0},
        {"symbol": "EURUSD", "hours": 169},
        {"symbol": "EURUSD", "hours": "x"},
    ],
)
def test_invalid_parameters_are_422(params: dict[str, Any], tmp_path: Path) -> None:
    _use(tmp_path, FakeCalendarSource([]))

    response = client.get("/calendar", params=params)

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}


def test_symbol_is_required(tmp_path: Path) -> None:
    _use(tmp_path, FakeCalendarSource([]))

    assert client.get("/calendar").status_code == 422


def test_internal_key_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(tmp_path, FakeCalendarSource([]))
    monkeypatch.setenv("SMC_INTERNAL_KEY", "sekret")

    assert _get().status_code == 401
    assert (
        client.get("/calendar?symbol=EURUSD", headers={"X-Internal-Key": "sekret"}).status_code
        == 200
    )


def test_rate_limit_applies_after_the_key_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(tmp_path, FakeCalendarSource([]))
    monkeypatch.setitem(RATE_LIMITERS, "calendar", RateLimiter(1, 60.0))

    assert _get().status_code == 200
    limited = _get()

    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_lowercase_symbol_maps_to_currencies(tmp_path: Path) -> None:
    _use(tmp_path, FakeCalendarSource([]))

    assert _get(symbol="eurusd").json()["currencies"] == ["EUR", "USD"]


def test_unauthorised_requests_do_not_use_the_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(tmp_path, FakeCalendarSource([]))
    monkeypatch.setenv("SMC_INTERNAL_KEY", "sekret")
    monkeypatch.setitem(RATE_LIMITERS, "calendar", RateLimiter(1, 60.0))

    assert _get().status_code == 401 and _get().status_code == 401
    assert (
        client.get("/calendar?symbol=EURUSD", headers={"X-Internal-Key": "sekret"}).status_code
        == 200
    )


def test_services_are_shared_per_database_path(tmp_path: Path) -> None:
    from smc_scanner.api import deps

    first = deps._calendar_service_for(tmp_path / "a.db")  # noqa: SLF001
    assert deps._calendar_service_for(tmp_path / "a.db") is first  # noqa: SLF001
    assert deps._calendar_service_for(None) is deps._calendar_service_for(None)  # noqa: SLF001
    assert deps._calendar_service_for(None) is not first  # noqa: SLF001


def test_bad_database_path_still_gives_one_shared_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", "//server/share/smc.db")

    assert get_calendar_service() is get_calendar_service()
