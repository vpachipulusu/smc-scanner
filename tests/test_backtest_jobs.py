"""Backtest jobs: the runner contract, loading once, and one background run at a time."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from backtest_job_support import SECRET, FakeRunner

from smc_scanner.ai.store import StoreError
from smc_scanner.backtest import jobs as jobs_module
from smc_scanner.backtest.jobs import (
    INTERRUPTED_MESSAGE,
    JOB_FAILED_MESSAGE,
    NOTHING_LOADED_MESSAGE,
    SYMBOL_FAILED_MESSAGE,
    BacktestJobs,
    BacktestRequest,
    BacktestRunningError,
    NothingLoadedError,
    PreloadedLoader,
    SplitSpec,
    baselines_of,
    execute,
    preload,
    replay_cost,
    scrub_failures,
    walk_forward_runner,
)
from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.backtest.store import NewBacktest, SqliteBacktestRepository
from smc_scanner.loaders import LoaderError
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES

STRATEGY = BUILTIN_STRATEGIES["smc-default"]


def request(**changes: Any) -> BacktestRequest:
    base: dict[str, Any] = {
        "strategy": STRATEGY,
        "source": "demo",
        "timeframe": "1h",
        "bars": 120,
        "symbols": ("EURUSD", "XAUUSD"),
        "rules": ExitRules(rr=1.5),
        "split": SplitSpec("symbols", 0.5),
        "seed": 4,
        "stride": 3,
    }
    return BacktestRequest(**{**base, **changes})


class FailingLoader:
    """Fails for the symbols in ``bad``; counts loads and closes."""

    def __init__(self, bad: set[str]) -> None:
        self.bad = bad
        self.loads: list[str] = []
        self.closed = False
        self.inner = DemoLoader(seed=1)

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        self.loads.append(symbol)
        if symbol in self.bad:
            raise LoaderError(SECRET)
        return self.inner.load(symbol, timeframe, bars)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def repo(tmp_path: Path) -> SqliteBacktestRepository:
    return SqliteBacktestRepository(tmp_path / "smc.db")


def inline(target: Callable[[], None]) -> None:
    target()


# --- SplitSpec and the runner contract --------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "fraction", "message"),
    [
        ("dates", 0.5, "split"),
        ("time", 0.25, "train_fraction"),
        ("time", 0.95, "train_fraction"),
        ("time", True, "number"),
        ("time", "0.5", "number"),
    ],
)
def test_split_spec_validates(kind: Any, fraction: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SplitSpec(kind, fraction)


def test_the_real_runner_is_called_with_the_split_unpacked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def walk_forward(*args: Any, **kwargs: Any) -> str:
        seen.update(args=args, kwargs=kwargs)
        return "result"

    monkeypatch.setattr(jobs_module, "walk_forward", walk_forward)
    loader = DemoLoader()
    rules = ExitRules()

    result = walk_forward_runner()(
        loader,
        ("A", "B"),
        "4h",
        300,
        STRATEGY,
        rules,
        split=SplitSpec("symbols", 0.6),
        seed=7,
        stride=2,
    )

    assert cast(object, result) == "result"
    assert seen["args"] == (loader, ["A", "B"], "4h", 300, STRATEGY, rules)
    assert seen["kwargs"] == {
        "split": "symbols",
        "train_fraction": 0.6,
        "seed": 7,
        "stride": 2,
        "lookback": None,  # the API never windows; the CLI's --lookback does
    }


def test_the_real_walk_forward_runs_through_the_job(repo: SqliteBacktestRepository) -> None:
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(seed=1), start=inline)
    real = request(bars=150, stride=10, split=SplitSpec())

    record = jobs.submit(real, walk_forward_runner(), repo)

    done = repo.get(record.id)
    assert done is not None and done.status == "done", done
    assert done.verdict in {"pass", "fail", "insufficient"}
    assert done.stats is not None
    assert {"in_sample", "out_of_sample", "random_baseline", "flipped_baseline"} <= set(done.stats)
    assert baselines_of(done.stats).keys() == {"random", "flipped"}


# --- loading ---------------------------------------------------------------------------------


def test_preload_loads_each_symbol_once_skips_failures_and_closes() -> None:
    source = FailingLoader({"BAD"})

    loader = preload(source, ["EURUSD", "BAD"], "1h", 100)

    assert loader.loaded == ("EURUSD",) and source.loads == ["EURUSD", "BAD"]
    assert source.closed
    assert len(loader.load("EURUSD", "1h", 40)) == 40
    with pytest.raises(LoaderError) as raised:
        loader.load("BAD", "1h", 40)
    assert SECRET not in str(raised.value)
    loader.close()


def test_execute_loads_under_the_lock_and_passes_every_symbol() -> None:
    lock = threading.Lock()
    held: list[bool] = []
    source = FailingLoader({"XAUUSD"})

    def factory(name: str) -> FailingLoader:
        held.append(lock.locked())
        assert name == "demo"
        return source

    runner = FakeRunner()

    outcome = execute(request(), runner, loader_factory=factory, load_lock=lock)

    assert held == [True] and not lock.locked()
    call = runner.calls[0]
    assert call["symbols"] == ["EURUSD", "XAUUSD"] and call["loaded"] == [120, 0]
    assert call["split"] == SplitSpec("symbols", 0.5) and call["seed"] == 4
    assert call["stride"] == 3 and call["rules"] == ExitRules(rr=1.5)
    assert outcome.verdict == "pass"
    assert outcome.stats["failures"] == [{"symbol": "BAD", "error": SYMBOL_FAILED_MESSAGE}]
    assert SECRET not in str(outcome.stats)


def test_execute_without_any_loaded_symbol_raises() -> None:
    with pytest.raises(NothingLoadedError):
        execute(
            request(symbols=("A",), split=SplitSpec()),
            FakeRunner(),
            loader_factory=lambda _: FailingLoader({"A"}),
        )


def test_an_unknown_verdict_is_stored_as_none(caplog: pytest.LogCaptureFixture) -> None:
    outcome = execute(request(), FakeRunner(verdict="great"), loader_factory=lambda _: DemoLoader())

    assert outcome.verdict is None
    assert "unknown verdict" in caplog.text


def test_scrub_failures_reaches_nested_lists() -> None:
    value = {"a": [{"failures": [{"symbol": "X", "error": SECRET}, "odd"]}], "failures": "text"}

    assert scrub_failures(value) == {
        "a": [{"failures": [{"symbol": "X", "error": SYMBOL_FAILED_MESSAGE}, "odd"]}],
        "failures": "text",
    }


def test_preloaded_loader_trims_to_the_bars_asked_for() -> None:
    frame = DemoLoader().load("EURUSD", "1h", 50)

    loaded = PreloadedLoader({"EURUSD": frame}).load("EURUSD", "1h", 10)

    assert len(loaded) == 10 and loaded.index[0] == 0
    assert loaded["time"].iloc[-1] == frame["time"].iloc[-1]


# --- BacktestJobs ----------------------------------------------------------------------------


def test_submit_records_pending_then_the_job_finishes(repo: SqliteBacktestRepository) -> None:
    ticks = iter([10.0, 14.5, 14.5])
    jobs = BacktestJobs(
        loader_factory=lambda _: DemoLoader(), start=inline, clock=lambda: next(ticks)
    )

    record = jobs.submit(request(), FakeRunner(), repo)

    assert record.status == "pending" and record.strategy == "smc-default"
    assert record.split == "symbols" and record.train_fraction == 0.5
    assert record.rules["rr"] == 1.5
    done = repo.get(record.id)
    assert done is not None and done.status == "done" and done.verdict == "pass"
    assert done.duration_seconds == 4.5
    assert done.stats is not None and "signals" not in done.stats
    assert done.stats["out_of_sample"]["n"] == 20
    assert not jobs.running


def test_a_second_submit_while_one_runs_is_refused(repo: SqliteBacktestRepository) -> None:
    started: list[Callable[[], None]] = []
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(), start=started.append)

    first = jobs.submit(request(), FakeRunner(), repo)

    assert jobs.running
    with pytest.raises(BacktestRunningError):
        jobs.submit(request(), FakeRunner(), repo)
    started[0]()
    assert not jobs.running
    after = repo.get(first.id)
    assert after is not None and after.status == "done"
    assert len(repo.list()) == 1


def test_a_failing_runner_stores_a_generic_error(
    repo: SqliteBacktestRepository, caplog: pytest.LogCaptureFixture
) -> None:
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(), start=inline)

    record = jobs.submit(request(), FakeRunner(error=RuntimeError(SECRET)), repo)

    failed = repo.get(record.id)
    assert failed is not None and failed.status == "failed"
    assert failed.error == JOB_FAILED_MESSAGE and failed.duration_seconds is not None
    assert SECRET not in str(failed)
    assert SECRET in caplog.text  # the details stay in the server log
    assert not jobs.running


def test_nothing_loaded_is_its_own_message(repo: SqliteBacktestRepository) -> None:
    jobs = BacktestJobs(loader_factory=lambda _: FailingLoader({"A"}), start=inline)

    record = jobs.submit(request(symbols=("A",), split=SplitSpec()), FakeRunner(), repo)

    failed = repo.get(record.id)
    assert failed is not None and failed.error == NOTHING_LOADED_MESSAGE


def test_submit_marks_rows_of_a_dead_process_interrupted(repo: SqliteBacktestRepository) -> None:
    stale = repo.insert(request().new_row())
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(), start=inline)

    jobs.submit(request(), FakeRunner(), repo)

    old = repo.get(stale.id)
    assert old is not None and old.status == "failed" and old.error == INTERRUPTED_MESSAGE


class BrokenRepository:
    """Inserts work, everything after fails, as when the disk goes away mid-run."""

    def __init__(self, inner: SqliteBacktestRepository, *, insert_fails: bool = False) -> None:
        self.inner = inner
        self.insert_fails = insert_fails

    def fail_unfinished(self, error: str) -> int:
        return 0

    def insert(self, run: NewBacktest) -> Any:
        if self.insert_fails:
            raise StoreError("disk full")
        return self.inner.insert(run)

    def _broken(self, *_: object) -> None:
        raise StoreError("disk gone")

    mark_running = finish = fail = _broken


def test_a_store_failure_during_the_run_is_logged_and_releases_the_guard(
    repo: SqliteBacktestRepository, caplog: pytest.LogCaptureFixture
) -> None:
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(), start=inline)

    jobs.submit(request(), FakeRunner(), BrokenRepository(repo))  # type: ignore[arg-type]

    assert "could not record the failure" in caplog.text
    assert not jobs.running


def test_a_failed_insert_releases_the_guard(repo: SqliteBacktestRepository) -> None:
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(), start=inline)
    broken = BrokenRepository(repo, insert_fails=True)

    with pytest.raises(StoreError):
        jobs.submit(request(), FakeRunner(), broken)  # type: ignore[arg-type]

    assert not jobs.running


def test_the_default_start_runs_the_job_on_a_daemon_thread(
    repo: SqliteBacktestRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[threading.Thread] = []
    real_start = threading.Thread.start

    def recording_start(thread: threading.Thread) -> None:
        threads.append(thread)
        real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", recording_start)
    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader())

    record = jobs.submit(request(), FakeRunner(), repo)
    threads[0].join(timeout=30)

    assert threads[0].daemon and threads[0].name == "smc-backtest"
    done = repo.get(record.id)
    assert done is not None and done.status == "done"
    assert not jobs.running
    assert SplitSpec().train_fraction == 0.6  # the walk-forward's own default


def test_a_symbol_split_needs_two_symbols() -> None:
    with pytest.raises(ValueError, match="2 distinct symbols"):
        request(symbols=("EURUSD", "EURUSD"))


def test_baselines_of_reads_either_shape() -> None:
    flat = {"random_baseline": {"n": 1}, "flipped_baseline": {"n": 2}}

    assert baselines_of(flat) == {"random": {"n": 1}, "flipped": {"n": 2}}
    assert baselines_of({"baselines": {"random": {"n": 3}}}) == {"random": {"n": 3}}
    assert baselines_of({"pooled": {}}) == {}


def test_replay_cost_grows_with_the_square_of_the_bars() -> None:
    assert replay_cost(1, 5000, 1) == 25_000_000
    assert replay_cost(2, 100, 1) == 20_000
    assert replay_cost(3, 100, 30) == 1000


def test_a_thread_that_cannot_start_fails_its_row(repo: SqliteBacktestRepository) -> None:
    def refuse(_: Callable[[], None]) -> None:
        raise RuntimeError("can't start new thread")

    jobs = BacktestJobs(loader_factory=lambda _: DemoLoader(), start=refuse)

    with pytest.raises(RuntimeError):
        jobs.submit(request(), FakeRunner(), repo)

    row = repo.list()[0]
    assert row.status == "failed" and row.error == JOB_FAILED_MESSAGE
    assert not jobs.running
