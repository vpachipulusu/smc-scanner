"""The backtest routes: start in the background, list, read, the strategy badge, and the guards."""

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from backtest_job_support import SECRET, FakeRunner
from fastapi.testclient import TestClient

from smc_scanner.ai.store import StoreError
from smc_scanner.api import app
from smc_scanner.api import deps as deps_module
from smc_scanner.api.constants import MAX_BACKTEST_STRIDE, MAX_SYMBOLS
from smc_scanner.backtest.jobs import JOB_FAILED_MESSAGE, BacktestJobs, walk_forward_runner
from smc_scanner.config import MAX_BARS
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.ratelimit import RateLimiter

client = TestClient(app, base_url="http://localhost")

BODY: dict[str, Any] = {
    "strategy": "smc-default",
    "source": "demo",
    "tf": "1h",
    "bars": 200,
    "symbols": ["EURUSD", "XAUUSD"],
}
STRATEGY: dict[str, Any] = {
    "slug": "my-ob",
    "name": "My OB",
    "zone_kinds": ["OB"],
    "require": [{"key": "aligned"}],
}


def inline(target: Callable[[], None]) -> None:
    target()


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def started() -> list[Callable[[], None]]:
    return []


@pytest.fixture(autouse=True)
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner) -> Iterator[Path]:
    path = tmp_path / "smc.db"
    monkeypatch.setenv("SMC_DB_PATH", str(path))
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(seed=1), start=inline)
    app.dependency_overrides[deps_module.get_backtest_jobs] = lambda: jobs
    app.dependency_overrides[deps_module.get_runner_factory] = lambda: lambda: runner
    yield path
    app.dependency_overrides.clear()


def _post(**changes: Any) -> dict[str, Any]:
    response = client.post("/backtests", json={**BODY, **changes})
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def _hold_jobs(started: list[Callable[[], None]]) -> BacktestJobs:
    """Jobs whose runs wait in ``started`` until a test runs them."""
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(seed=1), start=started.append)
    app.dependency_overrides[deps_module.get_backtest_jobs] = lambda: jobs
    return jobs


# --- POST /backtests -------------------------------------------------------------------------


def test_post_returns_202_with_the_pending_row_and_the_job_completes(runner: FakeRunner) -> None:
    body = {**BODY, "rules": {"rr": 3, "spread": 0.0002}, "seed": 5, "stride": 4}
    response = client.post("/backtests", json={**body, "split": "symbols"})
    created = response.json()

    assert response.status_code == 202
    assert response.headers["Location"] == f"/backtests/{created['id']}"

    assert created["status"] == "pending" and created["id"] >= 1
    assert created["results"] is None and created["verdict"] is None
    assert created["rules"]["rr"] == 3.0 and created["rules"]["spread"] == 0.0002
    assert created["split"] == "symbols" and created["train_fraction"] == 0.6
    call = runner.calls[0]
    assert call["symbols"] == ["EURUSD", "XAUUSD"] and call["loaded"] == [200, 200]
    assert call["seed"] == 5 and call["stride"] == 4 and call["strategy"] == "smc-default"

    done = client.get(f"/backtests/{created['id']}").json()
    assert done["status"] == "done" and done["verdict"] == "pass"
    assert done["results"]["out_of_sample"]["n"] == 20
    assert done["results"]["baselines"]["flipped"]["expectancy_r"] == -0.3
    assert done["results"]["baselines"]["random"]["expectancy_r"] == -0.1
    assert done["results"]["pooled"] is None  # the walk-forward has no pooled part
    assert done["error"] is None and "lookback" not in done
    assert SECRET not in str(done)


def test_post_drops_duplicate_symbols(runner: FakeRunner) -> None:
    created = _post(symbols=["EURUSD", "EURUSD", "XAUUSD"])

    assert created["symbols"] == ["EURUSD", "XAUUSD"]
    assert runner.calls[0]["symbols"] == ["EURUSD", "XAUUSD"]


def test_post_without_symbols_uses_the_demo_watchlist(runner: FakeRunner) -> None:
    body = {key: value for key, value in BODY.items() if key != "symbols"}

    response = client.post("/backtests", json=body)

    assert response.status_code == 202
    assert len(runner.calls[0]["symbols"]) >= 1


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "csv"},
        {"source": "csv", "symbols": ["C:/data/EURUSD.csv"]},
        {"bars": MAX_BARS + 1},
        {"bars": 1},
        {"symbols": [f"S{i}" for i in range(MAX_SYMBOLS + 1)]},
        {"symbols": []},
        {"symbols": ["bad symbol!"]},
        {"strategy": "Not A Slug"},
        {"rules": {"rr": 0}},
        {"rules": {"rr": 101}},
        {"rules": {"rr": True}},
        {"rules": {"rr": "2"}},
        {"rules": {"spread": -1}},
        {"rules": {"time_stop_bars": 0}},
        {"rules": {"time_stop_bars": 1.5}},
        {"rules": {"stop_buffer_atr": 51}},
        {"rules": {"min_risk_atr": -0.1}},
        {"rules": {"surprise": 1}},
        {"split": "dates"},
        {"train_fraction": 0.99},
        {"seed": -1},
        {"stride": 0},
        {"stride": MAX_BACKTEST_STRIDE + 1},
        {"bars": "200"},
        {"extra": 1},
    ],
)
def test_post_rejects_invalid_bodies_with_a_fixed_message(
    changes: dict[str, Any], runner: FakeRunner
) -> None:
    response = client.post("/backtests", json={**BODY, **changes})

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}
    assert runner.calls == []


def test_post_over_the_cost_cap_is_422(runner: FakeRunner) -> None:
    five = [f"S{i}" for i in range(5)]  # 5 x 5000^2 = 1.25e8, over the 1.2e8 cap

    response = client.post("/backtests", json={**BODY, "symbols": five, "bars": 5000})
    strided = client.post("/backtests", json={**BODY, "symbols": five, "bars": 5000, "stride": 2})
    four = client.post("/backtests", json={**BODY, "symbols": five[:4], "bars": 5000})

    assert response.status_code == 422
    assert response.json()["error"] == (
        "Backtest too large; use fewer symbols or bars, or a larger stride"
    )
    assert strided.status_code == 202 and four.status_code == 202


def test_a_symbol_split_with_one_symbol_is_422(runner: FakeRunner) -> None:
    response = client.post("/backtests", json={**BODY, "symbols": ["EURUSD"], "split": "symbols"})

    assert response.status_code == 422
    assert response.json()["error"] == "Invalid request"
    assert runner.calls == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/backtests", {**BODY, "source": "csv"}),
        ("get", "/backtests/0", None),
        ("get", "/backtests?limit=0", None),
        ("get", "/strategies/Bad!/backtest", None),
    ],
)
def test_invalid_input_is_422_even_when_the_store_is_down(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    app.dependency_overrides[deps_module.get_backtest_store] = _BrokenStore

    assert client.request(method, path, json=body).status_code == 422


def test_post_with_an_unknown_strategy_is_422(runner: FakeRunner) -> None:
    response = client.post("/backtests", json={**BODY, "strategy": "nope"})

    assert response.status_code == 422
    assert response.json()["error"] == "Unknown strategy"
    assert runner.calls == []


def test_post_while_one_runs_is_409(started: list[Callable[[], None]]) -> None:
    _hold_jobs(started)
    first = _post()

    second = client.post("/backtests", json=BODY)

    assert second.status_code == 409
    assert second.json()["error"] == "Backtest already running"
    assert client.get(f"/backtests/{first['id']}").json()["status"] == "pending"
    started[0]()
    assert client.get(f"/backtests/{first['id']}").json()["status"] == "done"
    assert client.post("/backtests", json=BODY).status_code == 202


def test_a_failed_job_stores_a_generic_error(runner: FakeRunner) -> None:
    runner.error = RuntimeError(SECRET)

    created = _post()

    failed = client.get(f"/backtests/{created['id']}").json()
    assert failed["status"] == "failed" and failed["error"] == JOB_FAILED_MESSAGE
    assert failed["results"] is None and SECRET not in str(failed)


def test_the_real_walk_forward_completes_through_the_api() -> None:
    app.dependency_overrides[deps_module.get_runner_factory] = lambda: walk_forward_runner

    created = _post(bars=150, stride=10)

    done = client.get(f"/backtests/{created['id']}").json()
    assert done["status"] == "done", done
    assert done["verdict"] in {"pass", "fail", "insufficient"}
    results = done["results"]
    assert results["in_sample"] is not None and results["out_of_sample"] is not None
    assert set(results["baselines"]) == {"random", "flipped"} and results["pooled"] is None
    badge = client.get("/strategies/smc-default/backtest").json()
    assert badge["id"] == created["id"] and badge["n"] == results["out_of_sample"]["n"]


# --- reads -----------------------------------------------------------------------------------


def test_list_items_are_summaries_without_results() -> None:
    created = _post()

    item = client.get("/backtests").json()["items"][0]

    assert item == {
        "id": created["id"],
        "strategy": "smc-default",
        "created_at": created["created_at"],
        "verdict": "pass",
        "n": 20,
        "expectancy_r": 0.2,
        "ci_low": pytest.approx(0.0),
        "ci_high": 0.4,
        "low_sample": True,
        "status": "done",
        "source": "demo",
        "tf": "1h",
        "bars": 200,
        "duration_seconds": item["duration_seconds"],
        "error": None,
    }


def test_list_is_newest_first_and_filters_by_strategy() -> None:
    first = _post()
    other = _post(strategy="fresh-ob-trend")
    last = _post()

    every = client.get("/backtests").json()["items"]
    mine = client.get("/backtests", params={"strategy": "smc-default"}).json()["items"]
    one = client.get("/backtests", params={"limit": 1}).json()["items"]

    assert [item["id"] for item in every] == [last["id"], other["id"], first["id"]]
    assert [item["id"] for item in mine] == [last["id"], first["id"]]
    assert [item["id"] for item in one] == [last["id"]]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"strategy": "Bad Slug"}, {"limit": "x"}]
)
def test_list_rejects_bad_parameters(params: dict[str, Any]) -> None:
    assert client.get("/backtests", params=params).status_code == 422


def test_get_unknown_or_invalid_id(db_path: Path) -> None:
    assert client.get("/backtests/1").status_code == 404
    assert client.get("/backtests/1").json()["error"] == "Backtest not found"
    assert client.get("/backtests/0").status_code == 422
    assert client.get("/backtests/abc").status_code == 422


def test_the_badge_is_404_without_a_finished_backtest(started: list[Callable[[], None]]) -> None:
    assert client.get("/strategies/smc-default/backtest").status_code == 404
    _hold_jobs(started)
    _post()  # pending only

    response = client.get("/strategies/smc-default/backtest")

    assert response.status_code == 404
    assert response.json()["error"] == "No finished backtest for this strategy"


def test_the_badge_shows_the_latest_finished_out_of_sample_result() -> None:
    _post()
    latest = _post()

    badge = client.get("/strategies/smc-default/backtest").json()

    assert badge == {
        "id": latest["id"],
        "strategy": "smc-default",
        "created_at": latest["created_at"],
        "verdict": "pass",
        "n": 20,
        "expectancy_r": 0.2,
        "ci_low": pytest.approx(0.0),
        "ci_high": 0.4,
        "low_sample": True,
    }


def test_the_badge_of_an_unknown_strategy_is_404() -> None:
    assert client.get("/strategies/nope/backtest").status_code == 404
    assert client.get("/strategies/Bad!/backtest").status_code == 422


def test_rows_of_a_deleted_strategy_are_hidden_from_list_and_badge() -> None:
    assert client.post("/strategies", json=STRATEGY).status_code == 201
    mine = _post(strategy="my-ob")
    kept = _post()
    assert client.get("/strategies/my-ob/backtest").status_code == 200

    assert client.delete("/strategies/my-ob").status_code == 204

    items = client.get("/backtests").json()["items"]
    assert [item["id"] for item in items] == [kept["id"]]
    assert client.get("/backtests", params={"strategy": "my-ob"}).json()["items"] == []
    assert client.get("/strategies/my-ob/backtest").status_code == 404
    assert client.get(f"/backtests/{mine['id']}").json()["strategy"] == "my-ob"


def test_stats_that_do_not_fit_the_schema_read_as_null(db_path: Path) -> None:
    from smc_scanner.backtest.store import NewBacktest, SqliteBacktestRepository

    repo = SqliteBacktestRepository(db_path)
    record = repo.insert(
        NewBacktest(
            strategy="smc-default",
            source="demo",
            timeframe="1h",
            bars=200,
            symbols=("EURUSD",),
            rules={"rr": "odd"},  # type: ignore[dict-item]
            split="time",
            train_fraction=None,
            seed=0,
            stride=1,
            status="done",
            stats={"pooled": {"n": "many"}},
            verdict="fail",
            duration_seconds=1.0,
        )
    )

    body = client.get(f"/backtests/{record.id}").json()
    badge = client.get("/strategies/smc-default/backtest").json()

    assert body["results"] is None and body["rules"] is None
    assert badge["verdict"] == "fail" and badge["n"] is None and badge["expectancy_r"] is None


# --- guards ----------------------------------------------------------------------------------


class _BrokenStore:
    def _fail(self, *_: object, **__: object) -> Any:
        raise StoreError("backtest database C:/secret/smc.db: disk I/O error")

    insert = get = list = latest_done = mark_running = finish = fail = fail_unfinished = _fail


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/backtests"),
        ("get", "/backtests/1"),
        ("get", "/strategies/smc-default/backtest"),
        ("post", "/backtests"),
    ],
)
def test_an_unusable_store_is_503_without_the_path(method: str, path: str) -> None:
    app.dependency_overrides[deps_module.get_backtest_store] = _BrokenStore

    response = client.request(method, path, json=BODY if method == "post" else None)

    assert response.status_code == 503
    assert response.json() == {"success": False, "error": "Backtest database unavailable"}


def test_a_missing_database_directory_is_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "missing" / "smc.db"))

    response = client.get("/backtests")

    assert response.status_code == 503
    assert response.json()["error"] == "Backtest database unavailable"


def test_a_read_only_database_is_503_on_post(db_path: Path) -> None:
    import os
    import stat

    from smc_scanner.backtest.store import SqliteBacktestRepository

    SqliteBacktestRepository(db_path)
    os.chmod(db_path, stat.S_IREAD)
    try:
        response = client.post("/backtests", json=BODY)
    finally:
        os.chmod(db_path, stat.S_IREAD | stat.S_IWRITE)

    assert response.status_code == 503
    assert response.json()["error"] == "Backtest database unavailable"


def test_the_read_rate_limit_is_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(deps_module.RATE_LIMITERS, "backtests", RateLimiter(1, 60.0))

    assert client.get("/backtests").status_code == 200
    response = client.get("/backtests/1")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert response.json()["error"] == "Too many requests; try again shortly"
    assert client.post("/backtests", json=BODY).status_code == 202  # polling never starves it


def test_starting_runs_has_its_own_tighter_limit() -> None:
    codes = [client.post("/backtests", json=BODY).status_code for _ in range(7)]

    assert codes == [202] * 6 + [429]
    assert client.get("/backtests").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/backtests"),
        ("get", "/backtests/1"),
        ("get", "/strategies/smc-default/backtest"),
        ("post", "/backtests"),
    ],
)
def test_every_route_needs_the_internal_key(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, runner: FakeRunner
) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", "s3cret")

    response = client.request(method, path, json=BODY if method == "post" else None)
    allowed = client.request(
        method,
        path,
        json=BODY if method == "post" else None,
        headers={"X-Internal-Key": "s3cret"},
    )

    assert response.status_code == 401
    assert allowed.status_code in {200, 202, 404}
    assert len(runner.calls) == (1 if method == "post" else 0)


def test_the_default_dependencies_resolve() -> None:
    app.dependency_overrides.clear()

    assert isinstance(deps_module.get_backtest_jobs(), BacktestJobs)
    assert deps_module.get_runner_factory() is walk_forward_runner
    assert client.get("/backtests").status_code == 200


def test_config_is_unchanged_by_backtests() -> None:
    body = client.get("/config").json()

    assert "backtests" not in body and "backtest" not in str(body.keys())


# --- the real thread, startup and process-wide state -----------------------------------------


class _BlockedRunner(FakeRunner):
    """Waits for ``release`` before finishing, so a test can see the run in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        assert self.release.wait(timeout=30)
        return super().__call__(*args, **kwargs)


def _wait_for(backtest_id: int, status: str) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for _ in range(300):
        body = client.get(f"/backtests/{backtest_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.05)
    raise AssertionError(f"backtest {backtest_id} never reached {status}: {body}")


def test_a_run_on_the_real_thread_reads_running_then_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(deps_module.RATE_LIMITERS, "backtests", RateLimiter(10_000, 60.0))
    blocked = _BlockedRunner()
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(seed=1))  # the default thread start
    app.dependency_overrides[deps_module.get_backtest_jobs] = lambda: jobs
    app.dependency_overrides[deps_module.get_runner_factory] = lambda: lambda: blocked

    created = _post()
    running = _wait_for(created["id"], "running")
    busy = client.post("/backtests", json=BODY)
    blocked.release.set()
    done = _wait_for(created["id"], "done")

    assert running["results"] is None and busy.status_code == 409
    assert done["verdict"] == "pass" and len(blocked.calls) == 1
    for _ in range(100):  # the guard is released just after the row is written
        if not jobs.running:
            break
        time.sleep(0.05)
    assert not jobs.running


def _stale_rows(path: Path) -> tuple[int, int, int]:
    from smc_scanner.backtest.store import NewBacktest, SqliteBacktestRepository

    repo = SqliteBacktestRepository(path)
    new = NewBacktest(
        strategy="smc-default",
        source="demo",
        timeframe="1h",
        bars=200,
        symbols=("EURUSD",),
        rules={"rr": 2.0},
        split="time",
        train_fraction=0.6,
        seed=0,
        stride=1,
    )
    pending, running = repo.insert(new), repo.insert(new)
    repo.mark_running(running.id)
    done = repo.insert(
        NewBacktest(**{**new.__dict__, "status": "done", "stats": {}, "duration_seconds": 1.0})
    )
    return pending.id, running.id, done.id


def test_startup_marks_rows_left_unfinished_failed(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMC_SCHEDULER", raising=False)
    pending, running, done = _stale_rows(db_path)

    with TestClient(app, base_url="http://localhost") as started:
        rows = {i: started.get(f"/backtests/{i}").json() for i in (pending, running, done)}

    assert rows[pending]["status"] == rows[running]["status"] == "failed"
    assert rows[pending]["error"] == "Backtest interrupted by a server restart"
    assert rows[done]["status"] == "done"


def test_the_startup_sweep_leaves_a_missing_database_alone(db_path: Path) -> None:
    assert deps_module.sweep_interrupted_backtests() == 0
    assert not db_path.exists()


def test_the_startup_sweep_survives_an_unusable_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database at all, just some text" * 50)
    monkeypatch.setenv("SMC_DB_PATH", str(broken))

    assert deps_module.sweep_interrupted_backtests() == 0
    assert "interrupted backtests not swept" in caplog.text


def test_the_store_is_opened_once_per_path(db_path: Path) -> None:
    first = deps_module.get_backtest_store()
    second = deps_module.get_backtest_store()

    assert first.list() == [] and second.list() == []
    assert first._repository() is second._repository()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("env", "argv", "warned"),
    [
        ({"WEB_CONCURRENCY": "2"}, [], True),
        ({}, ["uvicorn", "--workers", "3"], True),
        ({}, ["uvicorn", "--workers=2"], True),
        ({"WEB_CONCURRENCY": "1"}, [], False),
        ({"WEB_CONCURRENCY": "lots"}, [], False),
        ({}, ["uvicorn"], False),
    ],
)
def test_several_workers_warn_about_backtests(
    env: dict[str, str], argv: list[str], warned: bool
) -> None:
    from smc_scanner.api import startup_warnings

    warnings = startup_warnings(env, argv)

    assert any("backtests run one at a time per process" in w for w in warnings) is warned
