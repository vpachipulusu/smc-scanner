"""Running a backtest as a job: the walk-forward runner, loading, and background runs.

The walk-forward evaluation (``walkforward.walk_forward``) is injected through the
``WalkForwardRunner`` Protocol: ``walk_forward_runner`` adapts the real one to it, and tests pass
fakes.

``execute`` loads every symbol once, up front, under an optional lock (the API passes its scan
lock: the MetaTrader 5 connection is process-wide), then replays from memory, so a run of several
minutes holds that lock only while loading. ``BacktestJobs`` runs one backtest at a time per
process on a background thread and records its progress in a ``BacktestRepository``. A stored
error is always one of the fixed messages below, never exception text; the details go to the log.

The guard is per process and ``submit`` treats any unfinished row as a dead process's, so run the
API with a single worker (as for the scheduler): a second worker would fail the first one's job.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, closing, nullcontext
from dataclasses import asdict, dataclass
from typing import Any, Final, Protocol, get_args

import pandas as pd

from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.backtest.store import (
    BacktestRecord,
    BacktestRepository,
    JsonObject,
    NewBacktest,
    Verdict,
    parse_verdict,
)
from smc_scanner.backtest.walkforward import DEFAULT_TRAIN_FRACTION, SplitKind, walk_forward
from smc_scanner.loaders import LoaderError, make_loader
from smc_scanner.loaders.base import Loader
from smc_scanner.strategy.models import Strategy

log = logging.getLogger(__name__)

SPLIT_KINDS: Final[tuple[str, ...]] = get_args(SplitKind)
MIN_TRAIN_FRACTION: Final = 0.3  # a smaller in-sample part says little
MAX_TRAIN_FRACTION: Final = 0.9
MAX_SEED: Final = 2**32 - 1  # the walk-forward's own limit; fits a SQLite INTEGER
# The walk-forward names its baselines ``random_baseline`` and ``flipped_baseline``.
BASELINE_KEYS: Final = {"random": "random_baseline", "flipped": "flipped_baseline"}

JOB_FAILED_MESSAGE: Final = "Backtest failed; see the server log"
NOTHING_LOADED_MESSAGE: Final = "No symbol could be loaded"
INTERRUPTED_MESSAGE: Final = "Backtest interrupted by a server restart"
SYMBOL_FAILED_MESSAGE: Final = "Symbol could not be backtested"
_NOT_LOADED: Final = "symbol not loaded"


class BacktestRunningError(Exception):
    """A backtest is already running in this process."""


class NothingLoadedError(Exception):
    """No symbol could be loaded, so there is nothing to backtest."""


@dataclass(frozen=True)
class SplitSpec:
    """How the walk-forward splits the data: by time (each symbol's first ``train_fraction`` of
    bars in-sample) or by symbols (that fraction of the symbols in-sample)."""

    kind: SplitKind = "time"
    train_fraction: float = DEFAULT_TRAIN_FRACTION

    def __post_init__(self) -> None:
        if self.kind not in SPLIT_KINDS:
            raise ValueError("split must be time or symbols")
        fraction = self.train_fraction
        if isinstance(fraction, bool) or not isinstance(fraction, int | float):
            raise ValueError("train_fraction must be a number")
        if not MIN_TRAIN_FRACTION <= fraction <= MAX_TRAIN_FRACTION:
            raise ValueError(
                f"train_fraction must be between {MIN_TRAIN_FRACTION} and {MAX_TRAIN_FRACTION}"
            )


class WalkForwardResult(Protocol):
    """What a walk-forward run returns (``walkforward.WalkForwardResult``); ``to_dict()`` is
    strict JSON. Only ``verdict`` and ``to_dict()`` are read here."""

    @property
    def verdict(self) -> str: ...  # "pass" | "fail" | "insufficient"

    def to_dict(self) -> dict[str, Any]: ...


class WalkForwardRunner(Protocol):
    def __call__(
        self,
        loader: Loader,
        symbols: Sequence[str],
        timeframe: str,
        bars: int,
        strategy: Strategy,
        rules: ExitRules,
        *,
        split: SplitSpec,
        seed: int,
        stride: int,
        lookback: int | None = None,
    ) -> WalkForwardResult: ...


def run_walk_forward(
    loader: Loader,
    symbols: Sequence[str],
    timeframe: str,
    bars: int,
    strategy: Strategy,
    rules: ExitRules,
    *,
    split: SplitSpec,
    seed: int,
    stride: int,
    lookback: int | None = None,
) -> WalkForwardResult:
    """``walkforward.walk_forward`` as a ``WalkForwardRunner``: the split unpacked. The API
    never passes ``lookback``; the CLI's ``--lookback`` does."""
    return walk_forward(
        loader,
        list(symbols),
        timeframe,
        bars,
        strategy,
        rules,
        split=split.kind,
        train_fraction=split.train_fraction,
        seed=seed,
        stride=stride,
        lookback=lookback,
    )


def walk_forward_runner() -> WalkForwardRunner:
    """The runner the API and CLI use; tests swap it for a fake."""
    return run_walk_forward


@dataclass(frozen=True)
class BacktestRequest:
    """One strategy's backtest, fully validated (``ExitRules`` and ``SplitSpec`` check
    themselves; the caller checks bars, symbols, seed and stride). A symbol split needs at least
    two distinct symbols (ValueError)."""

    strategy: Strategy
    source: str
    timeframe: str
    bars: int
    symbols: tuple[str, ...]
    rules: ExitRules
    split: SplitSpec
    seed: int
    stride: int

    def __post_init__(self) -> None:
        if self.split.kind == "symbols" and len(set(self.symbols)) < 2:
            raise ValueError("a symbol split needs at least 2 distinct symbols")

    def new_row(self) -> NewBacktest:
        """The pending row this request starts as."""
        return NewBacktest(
            strategy=self.strategy.slug,
            source=self.source,
            timeframe=self.timeframe,
            bars=self.bars,
            symbols=self.symbols,
            rules=asdict(self.rules),
            split=self.split.kind,
            train_fraction=self.split.train_fraction,
            seed=self.seed,
            stride=self.stride,
        )


@dataclass(frozen=True)
class JobOutcome:
    stats: JsonObject
    verdict: Verdict | None


class PreloadedLoader:
    """A ``Loader`` over frames loaded once: replays never touch the source again. A symbol
    that failed to load raises ``LoaderError`` with a fixed message."""

    def __init__(self, frames: Mapping[str, pd.DataFrame]) -> None:
        self._frames = dict(frames)

    @property
    def loaded(self) -> tuple[str, ...]:
        return tuple(self._frames)

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        frame = self._frames.get(symbol)
        if frame is None:
            raise LoaderError(_NOT_LOADED)
        return frame.tail(bars).reset_index(drop=True)

    def close(self) -> None:
        return None


def preload(loader: Loader, symbols: Sequence[str], timeframe: str, bars: int) -> PreloadedLoader:
    """Every symbol's frame, loaded once; failures are logged and skipped. ``loader`` is closed
    afterwards."""
    frames: dict[str, pd.DataFrame] = {}
    with closing(loader):
        for symbol in symbols:
            try:
                frames[symbol] = loader.load(symbol, timeframe, bars)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
                log.error("%r: not loaded (%s: %r)", symbol, type(exc).__name__, exc)
    return PreloadedLoader(frames)


def scrub_failures(value: Any) -> Any:
    """``value`` with the text of every ``failures[].error`` replaced by a fixed message:
    ``ScanFailure.error`` carries raw exception text."""
    if isinstance(value, dict):
        scrubbed = {key: scrub_failures(item) for key, item in value.items()}
        failures = scrubbed.get("failures")
        if isinstance(failures, list):
            scrubbed["failures"] = [
                {**item, "error": SYMBOL_FAILED_MESSAGE} if isinstance(item, dict) else item
                for item in failures
            ]
        return scrubbed
    if isinstance(value, list):
        return [scrub_failures(item) for item in value]
    return value


def baselines_of(stats: JsonObject) -> dict[str, Any]:
    """The baseline stats keyed ``random`` and ``flipped``: a ``baselines`` mapping, or the
    walk-forward's ``random_baseline`` and ``flipped_baseline``. Missing ones are left out."""
    nested = stats.get("baselines")
    if isinstance(nested, dict):
        return dict(nested)
    return {name: stats[key] for name, key in BASELINE_KEYS.items() if key in stats}


def replay_cost(symbols: int, bars: int, stride: int) -> int:
    """A run's cost in bar-steps: ``symbols x bars / stride`` replayed prefixes, each costing
    about its length, so ``symbols x bars^2 / stride``."""
    return symbols * bars * bars // stride


def execute(
    request: BacktestRequest,
    runner: WalkForwardRunner,
    *,
    loader_factory: Callable[[str], Loader] = make_loader,
    load_lock: AbstractContextManager[object] | None = None,
) -> JobOutcome:
    """Load every symbol under ``load_lock``, then walk forward from memory.
    ``NothingLoadedError`` when no symbol loads."""
    with nullcontext() if load_lock is None else load_lock:
        loader = preload(
            loader_factory(request.source), request.symbols, request.timeframe, request.bars
        )
    if not loader.loaded:
        raise NothingLoadedError(NOTHING_LOADED_MESSAGE)
    result = runner(  # every symbol: the ones that did not load show up as failures
        loader,
        request.symbols,
        request.timeframe,
        request.bars,
        request.strategy,
        request.rules,
        split=request.split,
        seed=request.seed,
        stride=request.stride,
    )
    stats: JsonObject = scrub_failures(result.to_dict())
    verdict = parse_verdict(result.verdict)
    if verdict is None:
        log.error("walk-forward returned an unknown verdict; storing none")
    return JobOutcome(stats=stats, verdict=verdict)


def _start_thread(target: Callable[[], None]) -> None:
    # Daemon: a run takes minutes and must not hold up shutdown; an interrupted row is marked
    # failed by the next submit (see ``BacktestJobs.submit``).
    threading.Thread(target=target, name="smc-backtest", daemon=True).start()


class BacktestJobs:
    """At most one backtest at a time in this process, each on its own background thread.

    ``submit`` refuses a second run with ``BacktestRunningError`` (like ``RunGuard``, the guard
    is per process). While nothing runs here, a pending or running row can only be left over
    from a process that died, so ``submit`` marks those failed first. ``start`` runs the job;
    tests pass one that calls it inline.
    """

    def __init__(
        self,
        *,
        loader_factory: Callable[[str], Loader] = make_loader,
        load_lock: AbstractContextManager[object] | None = None,
        start: Callable[[Callable[[], None]], None] = _start_thread,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._busy = threading.Lock()
        self._loader_factory = loader_factory
        self._load_lock = load_lock
        self._start = start
        self._clock = clock

    @property
    def running(self) -> bool:
        return self._busy.locked()

    def submit(
        self, request: BacktestRequest, runner: WalkForwardRunner, repository: BacktestRepository
    ) -> BacktestRecord:
        """Record ``request`` as pending and start it; the pending row is returned."""
        if not self._busy.acquire(blocking=False):
            raise BacktestRunningError("a backtest is already running")
        try:
            stale = repository.fail_unfinished(INTERRUPTED_MESSAGE)
            if stale:
                log.warning("marked %d interrupted backtest(s) failed", stale)
            record = repository.insert(request.new_row())
        except BaseException:
            self._busy.release()
            raise
        try:
            self._start(lambda: self._run(record.id, request, runner, repository))
        except BaseException:  # the job never started, so the guard and the row are still ours
            log.exception("backtest %d could not start", record.id)
            self._fail(repository, record.id, JOB_FAILED_MESSAGE, None)
            self._busy.release()
            raise
        return record

    def _run(
        self,
        backtest_id: int,
        request: BacktestRequest,
        runner: WalkForwardRunner,
        repository: BacktestRepository,
    ) -> None:
        started = self._clock()
        try:
            repository.mark_running(backtest_id)
            outcome = execute(
                request, runner, loader_factory=self._loader_factory, load_lock=self._load_lock
            )
            duration = self._clock() - started
            repository.finish(backtest_id, outcome.stats, outcome.verdict, duration)
            log.info("backtest %d finished in %.1f s", backtest_id, duration)
        except NothingLoadedError:
            log.error("backtest %d: no symbol could be loaded", backtest_id)
            self._fail(repository, backtest_id, NOTHING_LOADED_MESSAGE, started)
        except Exception:  # noqa: BLE001 - a job must always end in a stored status
            log.exception("backtest %d failed", backtest_id)
            self._fail(repository, backtest_id, JOB_FAILED_MESSAGE, started)
        finally:
            self._busy.release()

    def _fail(
        self, repository: BacktestRepository, backtest_id: int, error: str, started: float | None
    ) -> None:
        duration = None if started is None else self._clock() - started
        try:
            repository.fail(backtest_id, error, duration)
        except Exception:  # noqa: BLE001 - nothing else can record it; the log keeps it
            log.exception("backtest %d: could not record the failure", backtest_id)
