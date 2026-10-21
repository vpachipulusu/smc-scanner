"""Journal routes: CRUD, cursor paging, stats, key check, rate limit and error mapping."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smc_scanner import api
from smc_scanner.ai.store import StoreError
from smc_scanner.api import app
from smc_scanner.api.deps import get_journal_store
from smc_scanner.api.routes.journal import encode_cursor
from smc_scanner.journal.models import JournalEntryIn, JournalEntryUpdate
from smc_scanner.journal.store import (
    JournalCursor,
    JournalLimitError,
    JournalNotFoundError,
    SqliteJournalStore,
)
from smc_scanner.ratelimit import RateLimiter

client = TestClient(app, base_url="http://localhost")

OPEN = {
    "symbol": "EURUSD",
    "timeframe": "1h",
    "side": "long",
    "entry": 100.0,
    "stop": 99.0,
    "opened_at": "2026-03-01T12:00:00Z",
}


def closed(exit_price: float, hours: int = 1, **changes: Any) -> dict[str, Any]:
    return {
        **OPEN,
        "exit": exit_price,
        "closed_at": f"2026-03-01T{12 + hours:02d}:00:00Z",
        **changes,
    }


@pytest.fixture(autouse=True)
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SqliteJournalStore]:
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    journal = SqliteJournalStore(tmp_path / "smc.db")
    app.dependency_overrides[get_journal_store] = lambda: journal
    yield journal
    app.dependency_overrides.clear()


def _create(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post("/journal", json=payload or OPEN)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- CRUD ----------------------------------------------------------------------------------


def test_create_get_patch_delete_round_trip() -> None:
    created = _create({**OPEN, "notes": "sweep", "analysis_id": 3})
    assert created["id"] >= 1 and created["notes"] == "sweep" and created["exit"] is None

    fetched = client.get(f"/journal/{created['id']}")
    assert fetched.status_code == 200 and fetched.json() == created

    patched = client.patch(
        f"/journal/{created['id']}", json={"exit": 102.0, "closed_at": "2026-03-01T14:00:00Z"}
    )
    assert patched.status_code == 200 and patched.json()["exit"] == 102.0

    assert client.delete(f"/journal/{created['id']}").json() == {"deleted": True}
    assert client.get(f"/journal/{created['id']}").status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"stop": 101.0},
        {"timeframe": "2h"},
        {"extra": 1},
        {"notes": "x" * 2001},
        {"exit": 101.0},
        {"entry": 1e13},
    ],
)
def test_invalid_create_is_a_422_with_the_common_error_shape(changes: dict[str, Any]) -> None:
    response = client.post("/journal", json={**OPEN, **changes})
    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}


def test_nan_in_the_body_is_a_422() -> None:
    body = '{"symbol":"EURUSD","timeframe":"1h","side":"long","entry":NaN,"stop":99,'
    body += '"opened_at":"2026-03-01T12:00:00Z"}'
    response = client.post("/journal", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_patch_that_breaks_a_rule_is_422_and_changes_nothing() -> None:
    created = _create()
    response = client.patch(f"/journal/{created['id']}", json={"stop": 105.0})
    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}
    assert client.get(f"/journal/{created['id']}").json() == created


def test_patch_cannot_clear_a_required_field() -> None:
    created = _create()
    assert client.patch(f"/journal/{created['id']}", json={"stop": None}).status_code == 422


def test_missing_entries_are_404() -> None:
    assert client.get("/journal/999").status_code == 404
    assert client.patch("/journal/999", json={"notes": "x"}).status_code == 404
    response = client.delete("/journal/999")
    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "Journal entry not found"}


@pytest.mark.parametrize("entry_id", ["0", "-1", "abc", str(2**63)])
def test_bad_ids_are_422(entry_id: str) -> None:
    assert client.get(f"/journal/{entry_id}").status_code == 422


# --- listing -------------------------------------------------------------------------------


def test_list_is_newest_first_and_pages_with_an_opaque_cursor() -> None:
    ids = [_create({**OPEN, "opened_at": f"2026-03-01T{h:02d}:00:00Z"})["id"] for h in (10, 14, 12)]
    first = client.get("/journal", params={"limit": 2}).json()
    assert [e["id"] for e in first["items"]] == [ids[1], ids[2]]
    assert isinstance(first["next_cursor"], str)
    second = client.get("/journal", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [e["id"] for e in second["items"]] == [ids[0]]
    assert second["next_cursor"] is None


def test_list_filters_by_symbol() -> None:
    _create()
    _create({**OPEN, "symbol": "XAUUSD"})
    body = client.get("/journal", params={"symbol": "XAUUSD"}).json()
    assert [e["symbol"] for e in body["items"]] == ["XAUUSD"]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"cursor": "garbage"},
        {"cursor": "x" * 200},
        {"symbol": "EUR USD"},
        {"symbol": "x" * 33},
    ],
)
def test_bad_list_parameters_are_422(params: dict[str, Any]) -> None:
    assert client.get("/journal", params=params).status_code == 422


def test_cursor_with_a_naive_time_or_a_huge_id_is_422() -> None:
    naive = encode_cursor(JournalCursor(datetime(2026, 1, 1), 1))
    huge = encode_cursor(JournalCursor(datetime(2026, 1, 1).astimezone(), 2**63))
    for cursor in (naive, huge):
        assert client.get("/journal", params={"cursor": cursor}).status_code == 422


# --- stats ---------------------------------------------------------------------------------


def test_stats_with_no_trades_has_null_ratios_and_an_empty_series() -> None:
    response = client.get("/journal/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["closed_trades"] == 0
    assert body["summary"]["win_rate"] is None and body["summary"]["expectancy"] is None
    assert body["cumulative"] == []


def test_stats_summarise_closed_trades_and_skip_open_ones() -> None:
    _create(closed(102.0, hours=2))  # +2R
    _create(closed(99.0, hours=1))  # -1R
    _create()  # open
    body = client.get("/journal/stats").json()
    summary = body["summary"]
    assert (summary["closed_trades"], summary["open_trades"]) == (2, 1)
    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["average_r"] == pytest.approx(0.5)
    assert summary["expectancy"] == pytest.approx(0.5)
    assert summary["total_r"] == pytest.approx(1.0)
    assert [p["cumulative_r"] for p in body["cumulative"]] == pytest.approx([-1.0, 1.0])


# --- auth, rate limit, errors ----------------------------------------------------------------


def test_internal_key_is_required_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", "s3cret")
    for path in ("/journal", "/journal/stats", "/journal/1"):
        assert client.get(path).status_code == 401
    assert client.post("/journal", json=OPEN).status_code == 401
    assert client.patch("/journal/1", json={}).status_code == 401
    assert client.delete("/journal/1").status_code == 401
    ok = client.get("/journal", headers={api.INTERNAL_KEY_HEADER: "s3cret"})
    assert ok.status_code == 200


def test_requests_are_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(api.RATE_LIMITERS, "journal", RateLimiter(2, 60.0))
    assert client.get("/journal").status_code == 200
    assert client.get("/journal/stats").status_code == 200
    limited = client.get("/journal")
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) >= 1
    assert limited.json()["error"] == api.RATE_LIMIT_MESSAGE


def test_unauthenticated_calls_do_not_use_the_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(api.RATE_LIMITERS, "journal", RateLimiter(1, 60.0))
    monkeypatch.setenv("SMC_INTERNAL_KEY", "s3cret")
    for _ in range(3):
        assert client.get("/journal").status_code == 401
    assert client.get("/journal", headers={api.INTERNAL_KEY_HEADER: "s3cret"}).status_code == 200


class _BrokenStore(SqliteJournalStore):
    """Every operation raises ``error``; no database is opened."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def add(self, entry: JournalEntryIn) -> Any:
        raise self._error

    def get(self, entry_id: int) -> Any:
        raise self._error

    def update(self, entry_id: int, patch: JournalEntryUpdate) -> Any:
        raise self._error

    def delete(self, entry_id: int) -> bool:
        raise self._error

    def list_entries(self, **_: Any) -> Any:
        raise self._error

    def closed_entries(self) -> Any:
        raise self._error

    def open_count(self) -> int:
        raise self._error


def test_store_failures_are_a_fixed_503_without_the_path() -> None:
    broken = _BrokenStore(StoreError("journal database C:\\secret\\smc.db: disk I/O error"))
    app.dependency_overrides[get_journal_store] = lambda: broken
    for response in (
        client.get("/journal"),
        client.get("/journal/stats"),
        client.get("/journal/1"),
        client.post("/journal", json=OPEN),
        client.patch("/journal/1", json={"notes": "x"}),
        client.delete("/journal/1"),
    ):
        assert response.status_code == 503
        assert response.json() == {"success": False, "error": "Journal database unavailable"}


def test_the_entry_cap_is_a_409_and_a_lost_row_a_404() -> None:
    app.dependency_overrides[get_journal_store] = lambda: _BrokenStore(JournalLimitError("full"))
    assert client.post("/journal", json=OPEN).status_code == 409
    app.dependency_overrides[get_journal_store] = lambda: _BrokenStore(JournalNotFoundError("x"))
    assert client.patch("/journal/1", json={"notes": "x"}).status_code == 404


# --- the real dependency -----------------------------------------------------------------------


def test_default_dependency_opens_the_store_from_smc_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides.clear()
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "real.db"))
    assert client.post("/journal", json=OPEN).status_code == 201
    assert len(client.get("/journal").json()["items"]) == 1


def test_default_dependency_maps_a_bad_database_path_to_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides.clear()
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path))  # a directory, not a file
    response = client.get("/journal")
    assert response.status_code == 503
    assert response.json()["error"] == "Journal database unavailable"


def test_stats_have_their_own_tighter_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(api.RATE_LIMITERS, "journal_stats", RateLimiter(1, 60.0))
    assert client.get("/journal/stats").status_code == 200
    assert client.get("/journal/stats").status_code == 429
    assert client.get("/journal").status_code == 200


def test_bad_ids_are_422_for_patch_and_delete_too() -> None:
    assert client.patch("/journal/0", json={"notes": "x"}).status_code == 422
    assert client.delete(f"/journal/{2**63}").status_code == 422


def test_cursors_with_a_wrong_prefix_or_id_are_422() -> None:
    import base64

    for text in ("x1:2026-01-01T00:00:00+00:00|1", "j1:2026-01-01T00:00:00+00:00|1a", "j1:|"):
        token = base64.urlsafe_b64encode(text.encode()).decode()
        assert client.get("/journal", params={"cursor": token}).status_code == 422


def test_openapi_documents_the_journal_routes() -> None:
    spec = client.get("/openapi.json").json()
    assert {"/journal", "/journal/stats", "/journal/{entry_id}"} <= set(spec["paths"])
    assert {"409", "429"} <= set(spec["paths"]["/journal"]["post"]["responses"])
