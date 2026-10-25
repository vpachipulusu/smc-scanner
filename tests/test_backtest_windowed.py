"""Windowed replay (``lookback``): each step scans the window the live scan sees with
``bars=lookback``, signals keep absolute bar indices, and the runners take long histories."""

import importlib
import json
import time
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest
from backtest_support import OB_TOUCH, strategy
from mtf_support import TfLoader

from smc_scanner.backtest.outcome import ExitRules, label
from smc_scanner.backtest.replay import Signal, replay, scan_at, zone_key
from smc_scanner.backtest.report import run_backtest
from smc_scanner.backtest.sweep import sweep
from smc_scanner.backtest.walkforward import walk_forward
from smc_scanner.config import MAX_BACKTEST_BARS, MAX_BARS, MIN_BARS
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.strategy.engine import scan_instrument_with_strategy
from smc_scanner.structure import atr, atr_at

# The package re-exports the ``replay`` function under the module's own name.
replay_module = importlib.import_module("smc_scanner.backtest.replay")
DEMO_BARS = 260
LOOKBACK = 80
RULES = ExitRules(rr=1.0, time_stop_bars=5)
# The runtime guard replays only the last GUARD_STEPS steps of a 20k-bar demo history: all 20k
# steps cost minutes. The deterministic window-size tests below carry the real guarantee.
GUARD_BARS = 20_000
GUARD_STEPS = 300
GUARD_LOOKBACK = 500
GUARD_BUDGET_SECONDS = 120.0  # CPU time, loose on purpose
AGED = strategy(
    swing_length=2,
    zone_kinds=["OB"],
    statuses=["TOUCHING"],
    require=[{"key": "max_zone_age", "params": {"bars": 10}}],
)
BAD_LOOKBACKS = [0, MIN_BARS - 1, MAX_BARS + 1, True, 50.0, "50"]


@pytest.fixture(scope="module")
def demo() -> pd.DataFrame:
    return DemoLoader().load("EURUSD", "1h", DEMO_BARS)


@pytest.fixture(scope="module")
def windowed(demo: pd.DataFrame) -> tuple[Signal, ...]:
    return replay("EURUSD", demo, None, lookback=LOOKBACK)


@pytest.fixture(scope="module")
def unwindowed(demo: pd.DataFrame) -> tuple[Signal, ...]:
    return replay("EURUSD", demo, None)


def live_window(ohlc: pd.DataFrame, index: int, bars: int) -> pd.DataFrame:
    """What a loader asked for ``bars`` candles returns when bar ``index`` is the latest."""
    return ohlc.iloc[: index + 1].tail(bars).reset_index(drop=True)


# --- replay -------------------------------------------------------------------------------


@pytest.mark.parametrize("index", [MIN_BARS, LOOKBACK - 2, LOOKBACK - 1, LOOKBACK, 150, 259])
def test_each_windowed_step_is_the_live_scan_with_bars_lookback(
    demo: pd.DataFrame, index: int
) -> None:
    live = scan_instrument_with_strategy("EURUSD", live_window(demo, index, LOOKBACK))

    assert scan_at("EURUSD", demo, None, index, lookback=LOOKBACK) == live


def test_windowed_signals_are_live_scan_rows_with_absolute_zone_keys(
    demo: pd.DataFrame, windowed: tuple[Signal, ...]
) -> None:
    assert windowed, "the demo frame should produce windowed signals"
    assert max(signal.bar_index for signal in windowed) >= LOOKBACK  # some steps are windowed
    for signal in windowed:
        live = scan_instrument_with_strategy(
            "EURUSD", live_window(demo, signal.bar_index, LOOKBACK)
        )
        assert signal.row in live
        assert signal.zone == zone_key(signal.row, signal.bar_index)
        assert signal.bar_time == str(demo["time"].iloc[signal.bar_index])
        assert signal.bar_index - LOOKBACK < signal.zone.formed_index <= signal.bar_index


def test_each_zone_signals_once_in_a_windowed_replay(windowed: tuple[Signal, ...]) -> None:
    keys = [signal.zone for signal in windowed]

    assert len(keys) == len(set(keys))
    assert [s.bar_index for s in windowed] == sorted(s.bar_index for s in windowed)


@pytest.mark.parametrize("cut", [120, 200])
def test_windowed_replay_reads_nothing_after_each_bar(
    demo: pd.DataFrame, windowed: tuple[Signal, ...], cut: int
) -> None:
    truncated = replay("EURUSD", demo.iloc[: cut + 1], None, lookback=LOOKBACK)

    assert truncated == tuple(signal for signal in windowed if signal.bar_index <= cut)


@pytest.mark.parametrize("lookback", [DEMO_BARS, DEMO_BARS + 1, MAX_BARS])
def test_a_lookback_covering_the_frame_equals_the_unwindowed_replay(
    demo: pd.DataFrame, unwindowed: tuple[Signal, ...], lookback: int
) -> None:
    assert replay("EURUSD", demo, None, lookback=lookback) == unwindowed


def test_a_window_shorter_than_the_frame_changes_the_replay(
    windowed: tuple[Signal, ...], unwindowed: tuple[Signal, ...]
) -> None:
    assert windowed != unwindowed


def test_windowed_stride_signals_a_subset_of_the_zones(
    demo: pd.DataFrame, windowed: tuple[Signal, ...]
) -> None:
    strided = replay("EURUSD", demo, None, lookback=LOOKBACK, stride=7)

    assert {s.zone for s in strided} <= {s.zone for s in windowed}


@pytest.mark.parametrize("lookback", BAD_LOOKBACKS)
def test_replay_and_scan_at_reject_a_bad_lookback(demo: pd.DataFrame, lookback: object) -> None:
    with pytest.raises(ValueError, match="lookback"):
        replay("EURUSD", demo, None, lookback=lookback)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="lookback"):
        scan_at("EURUSD", demo, None, 100, lookback=lookback)  # type: ignore[arg-type]


@pytest.mark.parametrize("lookback", [MIN_BARS, MAX_BARS])
def test_lookback_accepts_the_bar_limits(demo: pd.DataFrame, lookback: int) -> None:
    rows = scan_at("EURUSD", demo, None, 100, lookback=lookback)

    assert rows == scan_instrument_with_strategy("EURUSD", live_window(demo, 100, lookback))


def test_windowed_replay_at_the_end_of_twenty_thousand_bars_stays_within_its_budget() -> None:
    """Runtime guard, a loose CPU-time bound (``GUARD_BUDGET_SECONDS``): each step scans at
    most ``lookback`` bars however far into the history it is."""
    ohlc = DemoLoader().load("EURUSD", "1h", GUARD_BARS)
    start = GUARD_BARS - GUARD_STEPS

    started = time.process_time()
    signals = replay("EURUSD", ohlc, None, lookback=GUARD_LOOKBACK, start=start)
    elapsed = time.process_time() - started

    assert signals and signals[0].bar_index >= start
    assert elapsed < GUARD_BUDGET_SECONDS, f"windowed replay took {elapsed:.1f} s of CPU"


# --- runners ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def long_frame() -> pd.DataFrame:
    return DemoLoader().load("EURUSD", "1h", MAX_BARS + 60)


def long_loader(frame: pd.DataFrame) -> TfLoader:
    return TfLoader({("AAA", "1h"): frame, ("BBB", "1h"): frame.iloc[30:].reset_index(drop=True)})


def test_run_backtest_takes_more_than_max_bars_with_a_lookback(long_frame: pd.DataFrame) -> None:
    bars = len(long_frame)
    report = run_backtest(
        long_loader(long_frame), ["AAA"], "1h", bars, AGED, RULES, lookback=60, stride=97
    )

    expected = replay("AAA", long_frame, AGED, lookback=60, stride=97)
    assert report.failures == ()
    assert tuple(o.signal for o in report.symbols[0].outcomes) == expected
    assert report.lookback == 60
    payload = json.loads(json.dumps(report.to_dict(), allow_nan=False))
    assert payload["lookback"] == 60 and payload["bars"] == bars


def test_run_backtest_without_a_lookback_records_none(long_frame: pd.DataFrame) -> None:
    frame = long_frame.iloc[:200]
    report = run_backtest(TfLoader({("AAA", "1h"): frame}), ["AAA"], "1h", 200, OB_TOUCH, RULES)

    assert report.lookback is None and report.to_dict()["lookback"] is None


@pytest.mark.parametrize(
    ("bars", "lookback", "match"),
    [
        (MAX_BARS + 1, None, "bars"),
        (MAX_BACKTEST_BARS + 1, 500, "bars"),
        (1000, MIN_BARS - 1, "lookback"),
        (1000, True, "lookback"),
        (1000, 500.0, "lookback"),
        (1000, MAX_BARS + 1, "lookback"),
    ],
)
def test_runners_check_bars_and_lookback_before_anything_loads(
    bars: int, lookback: object, match: str
) -> None:
    loader = TfLoader({})

    with pytest.raises(ValueError, match=match):
        run_backtest(loader, ["A"], "1h", bars, OB_TOUCH, RULES, lookback=lookback)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=match):
        walk_forward(
            loader,
            ["A"],
            "1h",
            bars,
            OB_TOUCH,
            RULES,
            split="time",
            lookback=lookback,  # type: ignore[arg-type]
        )
    assert loader.calls == []


def test_max_backtest_bars_is_accepted_with_a_lookback() -> None:
    report = run_backtest(TfLoader({}), [], "1h", MAX_BACKTEST_BARS, OB_TOUCH, RULES, lookback=500)

    assert report.bars == MAX_BACKTEST_BARS and report.symbols == ()


def test_walk_forward_replays_windowed_and_records_the_lookback(long_frame: pd.DataFrame) -> None:
    bars = len(long_frame)
    result = walk_forward(
        long_loader(long_frame),
        ["AAA", "BBB"],
        "1h",
        bars,
        AGED,
        RULES,
        split="time",
        lookback=60,
        stride=97,
    )

    assert result.failures == ()
    assert [w.bars for w in result.windows] == [bars, bars - 30]
    assert result.lookback == 60 and result.to_dict()["lookback"] == 60
    signals = replay("AAA", long_frame, AGED, lookback=60, stride=97)
    window = result.windows[0]
    assert window.in_sample_signals + window.out_of_sample_signals == len(signals)


def test_sweep_passes_the_lookback_to_every_point(long_frame: pd.DataFrame) -> None:
    frame = long_frame.iloc[: MAX_BARS + 10]
    points = sweep(
        TfLoader({("AAA", "1h"): frame, ("BBB", "1h"): frame}),
        ["AAA", "BBB"],
        "1h",
        len(frame),
        AGED,
        RULES,
        condition="max_zone_age",
        grid={"bars": [5, 50]},
        split="time",
        lookback=60,
        stride=499,
    )

    assert [p.lookback for p in points] == [60, 60]
    assert all(p.to_dict()["lookback"] == 60 for p in points)


def test_walk_forward_and_sweep_without_a_lookback_record_none(long_frame: pd.DataFrame) -> None:
    frame = long_frame.iloc[:120]
    loader = TfLoader({("AAA", "1h"): frame, ("BBB", "1h"): frame})
    result = walk_forward(loader, ["AAA"], "1h", 120, AGED, RULES, split="time", stride=50)
    points = sweep(
        loader,
        ["AAA"],
        "1h",
        120,
        AGED,
        RULES,
        condition="max_zone_age",
        grid={"bars": [5]},
        split="time",
        stride=50,
    )

    assert result.lookback is None and result.to_dict()["lookback"] is None
    assert points[0].lookback is None and points[0].to_dict()["lookback"] is None


# --- window size, deterministically ---------------------------------------------------------


@pytest.fixture
def window_sizes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every frame length the replay scans; the scan itself is stubbed out (no rows)."""
    sizes: list[int] = []

    def scan(symbol: str, window: pd.DataFrame, *args: Any, **kwargs: Any) -> list[object]:
        assert list(window.index) == list(range(len(window)))  # re-indexed like a loaded frame
        sizes.append(len(window))
        return []

    monkeypatch.setattr(replay_module, "scan_instrument_with_strategy", scan)
    return sizes


RUNNERS: dict[str, Callable[[TfLoader, int], object]] = {
    "replay": lambda loader, bars: replay("AAA", loader.frames[("AAA", "1h")], AGED, lookback=60),
    "run_backtest": lambda loader, bars: run_backtest(
        loader, ["AAA"], "1h", bars, AGED, RULES, lookback=60, stride=13
    ),
    "walk_forward": lambda loader, bars: walk_forward(
        loader, ["AAA"], "1h", bars, AGED, RULES, split="time", lookback=60, stride=13
    ),
    "sweep": lambda loader, bars: sweep(
        loader,
        ["AAA"],
        "1h",
        bars,
        AGED,
        RULES,
        condition="max_zone_age",
        grid={"bars": [5, 50]},
        split="time",
        lookback=60,
        stride=13,
    ),
}


@pytest.mark.parametrize("runner", sorted(RUNNERS))
def test_every_runner_scans_at_most_lookback_bars_per_step(
    long_frame: pd.DataFrame, window_sizes: list[int], runner: str
) -> None:
    RUNNERS[runner](TfLoader({("AAA", "1h"): long_frame}), len(long_frame))

    assert window_sizes and max(window_sizes) == 60
    assert min(window_sizes) == MIN_BARS + 1  # the first step, before the window is full


def test_without_a_lookback_each_step_scans_the_whole_prefix(
    demo: pd.DataFrame, window_sizes: list[int]
) -> None:
    replay("EURUSD", demo, None, stride=50)

    assert window_sizes == [index + 1 for index in range(MIN_BARS, DEMO_BARS, 50)]


# --- labelling ATR --------------------------------------------------------------------------


@pytest.mark.parametrize("index", [14, 15, 16, 100, DEMO_BARS - 1])
def test_atr_at_equals_the_atr_of_the_whole_prefix(demo: pd.DataFrame, index: int) -> None:
    assert atr_at(demo, index) == atr(demo.iloc[: index + 1])


def test_atr_at_too_early_raises_like_the_prefix(demo: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="ATR"):
        atr_at(demo, 13)


def test_labels_size_by_the_signal_bar_atr(
    windowed: tuple[Signal, ...], demo: pd.DataFrame
) -> None:
    for signal in windowed[:10]:
        outcome = label(demo, signal, RULES)
        assert outcome.atr == atr(demo.iloc[: signal.bar_index + 1])
