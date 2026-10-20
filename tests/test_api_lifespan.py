"""The opt-in scheduler lifespan of the scanner API."""

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_scanner import api
from smc_scanner.ai.store import StoreError
from smc_scanner.api import SCHEDULER_ENV, app
from smc_scanner.schedule.runner import SchedulerService, run_schedule
from smc_scanner.schedule.store import Schedule


class FakeService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SMC_SERVER_TZ", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEB_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[FakeService]:
    built: list[FakeService] = []

    def build() -> FakeService:
        service = FakeService()
        built.append(service)
        return service

    monkeypatch.setattr(api, "_build_scheduler", build)
    return built


def test_disabled_by_default_builds_nothing(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService]
) -> None:
    monkeypatch.delenv(SCHEDULER_ENV, raising=False)

    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200

    assert fake == []


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_falsy_values_keep_it_off(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService], value: str
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, value)

    with TestClient(app, base_url="http://localhost"):
        pass

    assert fake == []


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_enabled_starts_on_startup_and_stops_on_shutdown(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService], value: str
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, value)

    with TestClient(app, base_url="http://localhost"):
        assert [s.calls for s in fake] == [["start"]]

    assert [s.calls for s in fake] == [["start", "stop"]]


def test_start_stop_start_builds_a_fresh_service_each_time(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService]
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "1")

    for _ in range(2):
        with TestClient(app, base_url="http://localhost"):
            pass

    assert [s.calls for s in fake] == [["start", "stop"], ["start", "stop"]]


def test_stop_runs_even_if_the_app_body_raises(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService]
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "1")

    with pytest.raises(RuntimeError), TestClient(app, base_url="http://localhost"):
        raise RuntimeError("boom")

    assert fake[0].calls == ["start", "stop"]


def test_failed_start_still_stops_the_service(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService]
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "1")

    def boom(self: FakeService) -> None:
        self.calls.append("start")
        raise RuntimeError("start failed")

    monkeypatch.setattr(FakeService, "start", boom)

    with pytest.raises(RuntimeError), TestClient(app, base_url="http://localhost"):
        pass

    assert fake[0].calls == ["start", "stop"]


def test_bad_db_path_fails_startup_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "1")
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "missing-dir" / "smc.db"))

    with pytest.raises(StoreError), TestClient(app, base_url="http://localhost"):
        pass


def test_scheduled_analysis_waits_on_the_analyse_lock_until_stopped(tmp_path: Path) -> None:
    deps = api._build_run_deps(tmp_path / "smc.db")
    monkey_poll = 0.01
    api.ANALYSE_LOCK_POLL_SECONDS, saved = monkey_poll, api.ANALYSE_LOCK_POLL_SECONDS

    try:
        with api._analyse_lock:
            deps.stop_event.set()
            with pytest.raises(RuntimeError, match="analysis lock"):
                deps.analyse(None, None, None, None, None)  # type: ignore[arg-type]
    finally:
        api.ANALYSE_LOCK_POLL_SECONDS = saved


def test_unrecognised_value_warns_and_stays_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "maybe")

    assert api._scheduler_enabled() is False
    assert "unrecognised" in caplog.text


def test_several_workers_log_a_warning(
    monkeypatch: pytest.MonkeyPatch, fake: list[FakeService], caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "1")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    with TestClient(app, base_url="http://localhost"):
        pass

    assert "several workers" in caplog.text


def test_held_scan_lock_postpones_a_scheduled_run(tmp_path: Path) -> None:
    base = api._build_run_deps(tmp_path / "smc.db")
    deps = replace(base, lock_timeout=0.05)
    schedule = Schedule(id=1, name="s", symbols=("EURUSD",), source="demo", tf="1h", frequency="1h")

    with api._scan_lock:
        report = run_schedule(schedule, deps)

    assert report.status == "busy"


def test_run_deps_share_the_scan_lock_and_read_the_token_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "smc.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-from-env")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    deps = api._build_run_deps(tmp_path / "smc.db")

    assert deps.scan_lock is api._scan_lock
    assert deps.telegram_token == "tok-from-env"
    assert deps.default_chat_id == "42"
    assert not deps.stop_event.is_set()


def test_real_service_starts_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(SCHEDULER_ENV, "1")
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "smc.db"))
    seen: list[SchedulerService] = []
    real_build = api._build_scheduler

    def spy() -> SchedulerService:
        service = real_build()
        seen.append(service)
        return service

    monkeypatch.setattr(api, "_build_scheduler", spy)

    for _ in range(2):  # start-stop-start
        with TestClient(app, base_url="http://localhost") as client:
            assert seen[-1].running
            assert client.get("/health").status_code == 200
        assert not seen[-1].running
        assert seen[-1].stop_event.is_set()

    assert len(seen) == 2 and seen[0] is not seen[1]
