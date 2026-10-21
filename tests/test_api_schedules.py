"""Schedule CRUD, run-now and logs: GET/POST /schedules, GET/PATCH/DELETE/run/logs by id."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from schedule_support import build_deps

from smc_scanner import api
from smc_scanner.ai.store import StoreError
from smc_scanner.api import app
from smc_scanner.api.routes import schedules as schedules_routes
from smc_scanner.schedule.joblog import JobLogEntry, SqliteJobLogStore
from smc_scanner.schedule.runner import RunDeps
from smc_scanner.schedule.store import MAX_SCHEDULES, Schedule, SqliteScheduleRepository

client = TestClient(app, base_url="http://localhost")

PAYLOAD: dict[str, Any] = {
    "name": "Majors hourly",
    "source": "demo",
    "tf": "1h",
    "symbols": ["EURUSD", "USDJPY"],
    "frequency": "1h",
}
T = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "smc.db"
    monkeypatch.setenv("SMC_DB_PATH", str(path))
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    api._run_now_at.clear()
    yield path
    app.dependency_overrides.clear()


def _create(**changes: Any) -> dict[str, Any]:
    response = client.post("/schedules", json={**PAYLOAD, **changes})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _use_deps(deps: RunDeps) -> None:
    app.dependency_overrides[api.get_run_deps_factory] = lambda: lambda: deps


def _fake_deps(db_path: Path, **kwargs: Any) -> RunDeps:
    deps, _, _ = build_deps(db_path.parent, **kwargs)
    return replace(deps, scan_lock=api._scan_lock, record=SqliteJobLogStore(db_path).record_run)


# --- create / list / get -------------------------------------------------------------------


def test_create_returns_the_stored_schedule_with_defaults() -> None:
    body = _create()

    assert body["id"] >= 1
    assert body["name"] == "Majors hourly"
    assert body["symbols"] == ["EURUSD", "USDJPY"]
    assert body["enabled"] is True
    assert body["min_score"] == 2
    assert body["min_confidence"] == 0
    assert body["only_on_change"] is False
    assert body["telegram_chat_id"] is None
    assert body["last_run_at"] is None
    assert body["next_run_at"] is None


def test_list_returns_every_schedule_in_id_order() -> None:
    first = _create(name="a")
    second = _create(name="b", enabled=False)

    response = client.get("/schedules")

    assert response.status_code == 200
    assert [s["id"] for s in response.json()["items"]] == [first["id"], second["id"]]
    assert response.json()["items"][1]["enabled"] is False


def test_list_is_empty_on_a_fresh_database() -> None:
    assert client.get("/schedules").json() == {"items": []}


@pytest.mark.parametrize(
    "changes",
    [
        {"frequency": "2h"},
        {"tf": "H1"},
        {"source": "csv"},
        {"symbols": []},
        {"symbols": ["BAD NAME"]},
        {"symbols": ["../etc"]},
        {"symbols": ["A"] * 51},
        {"name": ""},
        {"name": "x" * 65},
        {"min_score": -1},
        {"min_score": 5},
        {"min_confidence": 101},
        {"min_confidence": -1},
        {"telegram_chat_id": "not a chat"},
        {"telegram_chat_id": "12\n"},
        {"telegram_chat_id": "@ab"},
        {"surprise": 1},
    ],
)
def test_create_rejects_invalid_bodies_with_the_envelope(changes: dict[str, Any]) -> None:
    response = client.post("/schedules", json={**PAYLOAD, **changes})

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}


def test_create_rejects_a_blank_name() -> None:
    response = client.post("/schedules", json={**PAYLOAD, "name": "   "})

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}


def test_create_accepts_chat_id_shapes() -> None:
    assert _create(telegram_chat_id="-100123")["telegram_chat_id"] == "-100123"
    assert _create(telegram_chat_id="@my_channel")["telegram_chat_id"] == "@my_channel"


def test_create_beyond_the_cap_is_a_409(db_path: Path) -> None:
    repo = SqliteScheduleRepository(db_path)
    for _ in range(MAX_SCHEDULES):
        repo.add(Schedule(name="s", source="demo", tf="1h", symbols=("EURUSD",), frequency="1h"))

    response = client.post("/schedules", json=PAYLOAD)

    assert response.status_code == 409
    assert response.json() == {"success": False, "error": "Schedule limit reached"}


def test_get_one_and_missing() -> None:
    created = _create()

    assert client.get(f"/schedules/{created['id']}").json() == created
    missing = client.get("/schedules/999")
    assert missing.status_code == 404
    assert missing.json() == {"success": False, "error": "Schedule not found"}


@pytest.mark.parametrize("bad", ["0", "-1", "abc", str(2**63)])
def test_bad_ids_are_422(bad: str) -> None:
    assert client.get(f"/schedules/{bad}").status_code == 422
    assert client.delete(f"/schedules/{bad}").status_code == 422


# --- update --------------------------------------------------------------------------------


def test_patch_changes_only_the_given_fields() -> None:
    created = _create(telegram_chat_id="42")

    response = client.patch(f"/schedules/{created['id']}", json={"name": "New", "enabled": False})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New"
    assert body["enabled"] is False
    assert body["symbols"] == created["symbols"]
    assert body["telegram_chat_id"] == "42"


def test_patch_null_clears_the_chat_id_and_an_empty_body_changes_nothing() -> None:
    created = _create(telegram_chat_id="42")

    assert client.patch(f"/schedules/{created['id']}", json={}).json() == created
    cleared = client.patch(f"/schedules/{created['id']}", json={"telegram_chat_id": None})
    assert cleared.json()["telegram_chat_id"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"frequency": "weekly"},
        {"symbols": ["bad name"]},
        {"min_score": 99},
        {"name": None},
        {"enabled": None},
        {"name": "  "},
        {"id": 7},
    ],
)
def test_patch_rejects_invalid_bodies(changes: dict[str, Any]) -> None:
    created = _create()

    response = client.patch(f"/schedules/{created['id']}", json=changes)

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}
    assert client.get(f"/schedules/{created['id']}").json() == created


def test_patch_missing_schedule_is_404() -> None:
    assert client.patch("/schedules/5", json={"name": "x"}).status_code == 404


def test_patch_frequency_clears_the_next_slot(db_path: Path) -> None:
    created = _create()
    SqliteScheduleRepository(db_path).set_next_run(created["id"], T + timedelta(hours=1))

    body = client.patch(f"/schedules/{created['id']}", json={"frequency": "4h"}).json()

    assert body["frequency"] == "4h"
    assert body["next_run_at"] is None


# --- delete --------------------------------------------------------------------------------


def test_delete_removes_the_schedule_and_its_job_log(db_path: Path) -> None:
    created = _create()
    keep = _create(name="other")
    logs = SqliteJobLogStore(db_path)
    for sid in (created["id"], keep["id"]):
        logs.record(JobLogEntry(sid, T, T, "success"))

    response = client.delete(f"/schedules/{created['id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert client.get(f"/schedules/{created['id']}").status_code == 404
    assert logs.list_entries(schedule_id=created["id"]) == []
    assert len(logs.list_entries(schedule_id=keep["id"])) == 1


def test_delete_missing_is_404_and_leaves_logs_alone(db_path: Path) -> None:
    logs = SqliteJobLogStore(db_path)
    logs.record(JobLogEntry(77, T, T, "success"))

    assert client.delete("/schedules/77").status_code == 404
    assert len(logs.list_entries(schedule_id=77)) == 1


# --- run now -------------------------------------------------------------------------------


def test_run_now_runs_the_schedule_and_logs_it(db_path: Path) -> None:
    created = _create()
    _use_deps(_fake_deps(db_path))

    response = client.post(f"/schedules/{created['id']}/run")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "rows": 1,
        "delivered": 1,
        "skipped": 0,
        "error_count": 0,
    }
    entries = SqliteJobLogStore(db_path).list_entries(schedule_id=created["id"])
    assert [e.status for e in entries] == ["success"]
    assert client.get(f"/schedules/{created['id']}").json()["last_run_at"] is not None


def test_run_now_failure_reports_a_count_never_the_error_text(db_path: Path) -> None:
    created = _create()
    _use_deps(_fake_deps(db_path, scan_error=RuntimeError("secret detail /home/x")))

    response = client.post(f"/schedules/{created['id']}/run")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_count"] == 1
    assert "secret" not in response.text


def test_run_now_is_409_when_the_schedule_is_already_running(db_path: Path) -> None:
    created = _create()
    deps = _fake_deps(db_path)
    _use_deps(deps)
    assert deps.guard.try_enter(created["id"])

    response = client.post(f"/schedules/{created['id']}/run")

    assert response.status_code == 409
    assert response.json() == {"success": False, "error": "This schedule is already running"}


def test_run_now_is_409_when_a_scan_holds_the_lock(db_path: Path) -> None:
    created = _create()
    _use_deps(_fake_deps(db_path))

    with api._scan_lock:
        response = client.post(f"/schedules/{created['id']}/run")

    assert response.status_code == 409
    assert response.json() == {"success": False, "error": "A scan is already in progress"}


def test_run_now_again_within_the_cooldown_is_429_with_retry_after(db_path: Path) -> None:
    first, other = _create(), _create(name="other")
    _use_deps(_fake_deps(db_path))

    assert client.post(f"/schedules/{first['id']}/run").status_code == 200
    again = client.post(f"/schedules/{first['id']}/run")
    elsewhere = client.post(f"/schedules/{other['id']}/run")

    assert again.status_code == 429
    assert again.json() == {"success": False, "error": api.RUN_COOLDOWN_MESSAGE}
    assert 1 <= int(again.headers["Retry-After"]) <= api.RUN_NOW_COOLDOWN_SECONDS
    assert elsewhere.status_code == 200


def test_run_now_is_allowed_again_after_the_cooldown(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create()
    _use_deps(_fake_deps(db_path))
    monkeypatch.setattr(schedules_routes, "RUN_NOW_COOLDOWN_SECONDS", 0.0)

    assert client.post(f"/schedules/{created['id']}/run").status_code == 200
    assert client.post(f"/schedules/{created['id']}/run").status_code == 200
    assert api._run_now_at == {created["id"]: api._run_now_at[created["id"]]}


def test_a_missing_schedule_does_not_take_a_cooldown_slot() -> None:
    assert client.post("/schedules/9/run").status_code == 404
    assert api._run_now_at == {}


def test_run_now_on_a_stopping_service_is_503(db_path: Path) -> None:
    created = _create()
    deps = _fake_deps(db_path)
    deps.stop_event.set()
    _use_deps(deps)

    assert client.post(f"/schedules/{created['id']}/run").status_code == 503


def test_run_now_unknown_schedule_is_404_before_any_deps_are_built() -> None:
    def boom() -> RunDeps:
        raise AssertionError("deps must not be built for a missing schedule")

    app.dependency_overrides[api.get_run_deps_factory] = lambda: boom

    assert client.post("/schedules/9/run").status_code == 404


def test_the_real_run_deps_share_the_guard_and_record_to_the_job_log() -> None:
    deps = api._request_run_deps()

    assert deps.guard is api._run_guard
    assert deps.scan_lock is api._scan_lock
    assert getattr(deps.record, "__self__", None).__class__ is SqliteJobLogStore
    assert not deps.stop_event.is_set()


def test_a_bad_run_setup_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _create()
    monkeypatch.setenv("SMC_SERVER_TZ", "Not/AZone")

    response = client.post(f"/schedules/{created['id']}/run")

    assert response.status_code == 503
    assert response.json()["success"] is False


def test_concurrent_patches_of_different_fields_both_stick() -> None:
    created = _create()
    url = f"/schedules/{created['id']}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(client.patch, url, json={"name": "renamed"}),
            pool.submit(client.patch, url, json={"enabled": False}),
        ]
        assert [f.result().status_code for f in futures] == [200, 200]

    final = client.get(url).json()
    assert final["name"] == "renamed"
    assert final["enabled"] is False


def test_a_broken_database_is_503_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "missing-dir" / "smc.db"))

    assert client.get("/schedules").status_code == 503
    assert client.post("/schedules", json=PAYLOAD).status_code == 503
    assert client.post("/schedules/1/run").status_code == 503
    assert client.get("/schedules/1/logs").status_code == 503


# --- logs ----------------------------------------------------------------------------------


def _log(db_path: Path, sid: int, n: int, **kwargs: Any) -> None:
    logs = SqliteJobLogStore(db_path)
    for i in range(n):
        moment = T + timedelta(minutes=i)
        logs.record(JobLogEntry(sid, moment, moment, **kwargs))


def test_logs_page_newest_first_with_a_keyset_cursor(db_path: Path) -> None:
    created = _create()
    _log(db_path, created["id"], 5, status="success", hits=2)
    url = f"/schedules/{created['id']}/logs"

    first = client.get(url, params={"limit": 2}).json()
    second = client.get(url, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    last = client.get(url, params={"limit": 2, "cursor": second["next_cursor"]}).json()

    ids = [e["id"] for page in (first, second, last) for e in page["items"]]
    assert ids == sorted(ids, reverse=True)
    assert len(ids) == len(set(ids)) == 5
    assert last["next_cursor"] is None
    assert first["items"][0]["status"] == "success"
    assert first["items"][0]["hits"] == 2
    assert first["items"][0]["duration_ms"] == 0


def test_logs_only_show_the_requested_schedule(db_path: Path) -> None:
    mine, other = _create(), _create(name="o")
    _log(db_path, mine["id"], 1, status="success")
    _log(db_path, other["id"], 2, status="failed", error="boom")

    items = client.get(f"/schedules/{mine['id']}/logs").json()["items"]

    assert [i["schedule_id"] for i in items] == [mine["id"]]


def test_logs_error_text_is_a_plain_json_string(db_path: Path) -> None:
    created = _create()
    _log(db_path, created["id"], 1, status="failed", error="<script>alert(1)</script>")

    response = client.get(f"/schedules/{created['id']}/logs")

    assert response.json()["items"][0]["error"] == "<script>alert(1)</script>"
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"cursor": "!!"}, {"cursor": "x" * 65}]
)
def test_logs_reject_bad_paging(params: dict[str, Any]) -> None:
    created = _create()

    assert client.get(f"/schedules/{created['id']}/logs", params=params).status_code == 422


def test_logs_of_a_missing_schedule_are_404() -> None:
    assert client.get("/schedules/3/logs").status_code == 404


def test_logs_store_failure_is_503_without_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _create()

    def broken(*_: Any, **__: Any) -> list[JobLogEntry]:
        raise StoreError("db gone /secret/path")

    monkeypatch.setattr(SqliteJobLogStore, "list_entries", broken)

    response = client.get(f"/schedules/{created['id']}/logs")

    assert response.status_code == 503
    assert "secret" not in response.text


# --- auth and host -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/schedules"),
        ("POST", "/schedules"),
        ("GET", "/schedules/1"),
        ("PATCH", "/schedules/1"),
        ("DELETE", "/schedules/1"),
        ("POST", "/schedules/1/run"),
        ("GET", "/schedules/1/logs"),
        ("POST", "/telegram/test"),
    ],
)
def test_every_endpoint_needs_the_internal_key_when_set(
    method: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", "k")

    assert client.request(method, path, json={}).status_code == 401
    wrong = client.request(method, path, json={}, headers={"X-Internal-Key": "no"})
    assert wrong.status_code == 401


def test_the_right_key_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", "k")

    assert client.get("/schedules", headers={"X-Internal-Key": "k"}).status_code == 200


def test_a_non_loopback_host_is_rejected() -> None:
    other = TestClient(app, base_url="http://evil.example")

    assert other.get("/schedules").status_code == 400
