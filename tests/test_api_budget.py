"""TRAD-22b at the API: budget 429s, per-endpoint rate limits, startup warnings, scheduled runs."""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import FLAT, FVG_SETUP, TOUCH_LAST, frame
from fastapi.testclient import TestClient

from smc_scanner import api
from smc_scanner.ai.providers import AiReply, FakeProvider
from smc_scanner.ai.store import SqliteAnalysisStore
from smc_scanner.ai_cli import DemoProvider
from smc_scanner.api import app
from smc_scanner.ratelimit import RateLimiter
from smc_scanner.scanner import ScanOptions, scan_instrument
from smc_scanner.schedule.joblog import SqliteJobLogStore
from smc_scanner.schedule.runner import RunDeps, ScanData, run_schedule
from smc_scanner.schedule.store import Schedule, SqliteScheduleRepository

SECRET = "sk-ant-test-secret-value"
INTERNAL = "internal-key-value-123"
BODY = {"source": "demo", "symbols": ["USDJPY", "EURUSD"], "bars": 300, "min_score": 0}
client = TestClient(app, base_url="http://localhost")


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "smc.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    for name in (
        "SMC_INTERNAL_KEY",
        "AI_MAX_CALLS_PER_DAY",
        "AI_MAX_COST_PER_DAY",
        "SMC_API_HOST",
        "UVICORN_HOST",
        "SMC_API_ALLOWED_HOSTS",
        "SMC_SCHEDULER",
    ):
        monkeypatch.delenv(name, raising=False)
    app.dependency_overrides[api.get_provider_factory] = lambda: lambda: DemoProvider()


@pytest.fixture(autouse=True)
def _clear_overrides() -> object:
    yield
    app.dependency_overrides.clear()


# --- POST /analyse budget ------------------------------------------------------------


def test_calls_cap_gives_429_with_retry_after_and_the_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "0")

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    body = response.json()
    assert body["success"] is False
    assert "budget" in body["error"].lower()
    assert SECRET not in response.text


def test_fully_cached_run_is_served_even_when_the_cap_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post("/analyse", json=BODY).status_code == 200  # fills the store
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "0")

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 200
    assert {r["ai"]["status"] for r in response.json()["rows"]} == {"skipped_duplicate"}


def test_cap_reached_mid_run_gives_429_and_keeps_the_saved_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "1")

    response = client.post("/analyse", json={**BODY, "symbols": ["USDJPY", "EURUSD", "AUDUSD"]})

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert len(SqliteAnalysisStore(tmp_path / "smc.db").list_recent(10)) == 1


def test_cost_cap_gives_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAX_COST_PER_DAY", "0")
    assert client.post("/analyse", json=BODY).status_code == 429


def test_generous_caps_do_not_interfere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "1000")
    monkeypatch.setenv("AI_MAX_COST_PER_DAY", "1000")
    assert client.post("/analyse", json=BODY).status_code == 200


def test_invalid_cap_setting_is_a_503_that_names_no_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "lots-secret-9")

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 503
    assert response.json()["success"] is False
    assert "lots-secret-9" not in response.text


def test_openapi_documents_the_429s() -> None:
    paths = app.openapi()["paths"]
    for route, method in (("/analyse", "post"), ("/scan", "get")):
        responses = paths[route][method]["responses"]
        assert "429" in responses
        assert "Retry-After" in responses["429"]["headers"]


# --- rate limits ---------------------------------------------------------------------


def test_analyse_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(api.RATE_LIMITERS, "analyse", RateLimiter(limit=2, window_seconds=60.0))

    codes = [client.post("/analyse", json=BODY).status_code for _ in range(3)]

    assert codes[:2] == [200, 200]
    assert codes[2] == 429


def test_rate_limit_response_has_retry_after_and_the_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(api.RATE_LIMITERS, "scan", RateLimiter(limit=1, window_seconds=60.0))
    params = {"source": "demo", "symbols": "USDJPY"}
    assert client.get("/scan", params=params).status_code == 200

    response = client.get("/scan", params=params)

    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert response.json() == {"success": False, "error": api.RATE_LIMIT_MESSAGE}


def test_limits_are_per_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(api.RATE_LIMITERS, "scan", RateLimiter(limit=1, window_seconds=60.0))
    params = {"source": "demo", "symbols": "USDJPY"}
    client.get("/scan", params=params)
    assert client.get("/scan", params=params).status_code == 429
    assert client.post("/analyse", json=BODY).status_code == 200


def test_unauthenticated_calls_do_not_use_up_the_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", INTERNAL)
    monkeypatch.setitem(api.RATE_LIMITERS, "scan", RateLimiter(limit=1, window_seconds=60.0))
    params = {"source": "demo", "symbols": "USDJPY"}

    assert client.get("/scan", params=params).status_code == 401
    assert client.get("/scan", params=params).status_code == 401
    ok = client.get("/scan", params=params, headers={"X-Internal-Key": INTERNAL})

    assert ok.status_code == 200


def test_default_limiters_exist_for_scan_and_analyse() -> None:
    assert set(api.RATE_LIMITERS) >= {"scan", "analyse"}


# --- startup warnings ----------------------------------------------------------------


def test_warns_when_exposed_without_an_internal_key() -> None:
    warnings = api.startup_warnings({"SMC_API_HOST": "0.0.0.0"})  # noqa: S104
    assert any("SMC_INTERNAL_KEY" in w for w in warnings)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", ""])
def test_no_key_warning_on_loopback(host: str) -> None:
    warnings = api.startup_warnings({"SMC_API_HOST": host})
    assert not any("SMC_INTERNAL_KEY" in w for w in warnings)


def test_non_loopback_allowed_host_counts_as_exposed() -> None:
    warnings = api.startup_warnings({"SMC_API_ALLOWED_HOSTS": "127.0.0.1,scanner.example.com"})
    assert any("SMC_INTERNAL_KEY" in w for w in warnings)


def test_a_non_loopback_host_flag_on_the_command_line_counts_as_exposed() -> None:
    for argv in (["uvicorn", "--host", "0.0.0.0"], ["uvicorn", "--host=0.0.0.0"]):  # noqa: S104
        warnings = api.startup_warnings({}, argv)
        assert any("SMC_INTERNAL_KEY" in w for w in warnings)
    assert not any(
        "SMC_INTERNAL_KEY" in w
        for w in api.startup_warnings({}, ["uvicorn", "--host", "127.0.0.1"])
    )


def test_no_key_warning_when_the_key_is_set() -> None:
    env = {"SMC_API_HOST": "0.0.0.0", "SMC_INTERNAL_KEY": INTERNAL}  # noqa: S104
    assert not any("SMC_INTERNAL_KEY" in w for w in api.startup_warnings(env))


def test_warns_when_budget_limits_are_unset() -> None:
    warnings = api.startup_warnings({})
    assert any("AI_MAX_CALLS_PER_DAY" in w and "AI_MAX_COST_PER_DAY" in w for w in warnings)


def test_no_budget_warning_when_a_limit_is_set() -> None:
    assert not any("AI_MAX" in w for w in api.startup_warnings({"AI_MAX_CALLS_PER_DAY": "50"}))


def test_warnings_never_contain_secret_values() -> None:
    env = {"SMC_INTERNAL_KEY": INTERNAL, "ANTHROPIC_API_KEY": SECRET, "SMC_API_HOST": "0.0.0.0"}  # noqa: S104
    assert INTERNAL not in " ".join(api.startup_warnings(env))
    assert SECRET not in " ".join(api.startup_warnings(env))


def test_lifespan_logs_the_warnings(caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level(logging.WARNING, logger="smc_scanner.api"),
        TestClient(app, base_url="http://localhost"),
    ):
        pass
    assert any("AI_MAX_CALLS_PER_DAY" in r.getMessage() for r in caplog.records)


# --- scheduled runs ------------------------------------------------------------------

OHLC = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST])
OPTIONS = ScanOptions(swing_length=2)
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _scheduled(tmp_path: Path, provider: FakeProvider) -> tuple[Schedule, RunDeps]:
    db = tmp_path / "smc.db"
    deps = api._build_run_deps(db)
    rows = tuple(scan_instrument("EURUSD", OHLC, OPTIONS))
    assert rows

    def scan(_: Schedule) -> ScanData:
        return ScanData(rows=rows, frames={"EURUSD": OHLC}, options=OPTIONS)

    deps = replace(deps, scan=scan, provider_factory=lambda: provider, clock=lambda: NOW)
    schedule = SqliteScheduleRepository(db).add(
        Schedule(
            name="s",
            source="demo",
            tf="1h",
            symbols=("EURUSD",),
            frequency="1h",
            min_score=0,
        )
    )
    return schedule, deps


def test_scheduled_run_over_the_cap_is_a_failed_job_log_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "0")
    provider = FakeProvider([AiReply("{}", 0, 0, "fake")])
    schedule, deps = _scheduled(tmp_path, provider)

    report = run_schedule(schedule, deps)

    assert report.status == "failed"
    assert provider.calls == []
    assert any("budget" in e.lower() for e in report.errors)
    entries = SqliteJobLogStore(tmp_path / "smc.db").list_entries(schedule_id=schedule.id or 0)
    assert [e.status for e in entries] == ["failed"]
    assert "budget" in (entries[0].error or "").lower()


def test_scheduled_run_under_the_cap_calls_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "100")
    hold = '{"action": "HOLD", "confidence": 40, "reasons": ["weak"], "summary": "No edge."}'
    provider = FakeProvider([hold])
    schedule, deps = _scheduled(tmp_path, provider)

    report = run_schedule(schedule, deps)

    assert report.status == "ok"
    assert len(provider.calls) == 1


def test_run_deps_with_an_invalid_cap_fail_to_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_MAX_COST_PER_DAY", "-1")
    with pytest.raises(ValueError):
        api._build_run_deps(tmp_path / "smc.db")
