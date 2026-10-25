"""Walk-forward: no-leak splits, out-of-sample stats against the baselines, the verdict, sweeps."""

import importlib
import json
from dataclasses import replace
from typing import Any

import pandas as pd
import pytest
from backtest_support import OB_TOUCH, make_outcome, make_signal, ob_frame, strategy
from conftest import Candle
from mtf_support import TfLoader

from smc_scanner import backtest
from smc_scanner.backtest import walkforward
from smc_scanner.backtest.baseline import random_signals
from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.backtest.replay import Signal, replay
from smc_scanner.backtest.stats import LOW_SAMPLE_N, summarise
from smc_scanner.backtest.sweep import sweep, sweep_variants
from smc_scanner.backtest.walkforward import (
    RANDOM_DRAWS,
    WalkForwardResult,
    split_by_symbols,
    split_by_time,
    split_outcomes,
    verdict,
    walk_forward,
)
from smc_scanner.config import ATR_PERIOD, MIN_BARS
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.strategy import ConditionParamError

# The package re-exports the ``sweep`` function under the module's own name.
sweep_module = importlib.import_module("smc_scanner.backtest.sweep")
RULES = ExitRules(rr=1.0, time_stop_bars=5)
# After the OB touch at bar 24 (close 103): entry 103, stop 99.5, target 106.5 at rr 1.
ENTRY: Candle = (103.0, 104.0, 102.5, 103.8)
WIN: Candle = (103.8, 107.0, 103.5, 106.8)
LOSS: Candle = (103.8, 104.0, 99.0, 99.4)
HOLD_WIN: Candle = (106.8, 106.9, 106.6, 106.8)
HOLD_LOSS: Candle = (99.4, 99.6, 99.2, 99.4)
WIN_FRAME = ob_frame([ENTRY, WIN, HOLD_WIN, HOLD_WIN, HOLD_WIN])  # 30 bars, signal at bar 24
LOSS_FRAME = ob_frame([ENTRY, LOSS, HOLD_LOSS, HOLD_LOSS, HOLD_LOSS])
FRAME_BARS = len(WIN_FRAME)
SIGNAL_BAR = 24
MANY = [f"S{i:02d}" for i in range(LOW_SAMPLE_N + 5)]


def replay_signals() -> tuple[Signal, ...]:
    return replay("A", WIN_FRAME, OB_TOUCH)  # one signal, at SIGNAL_BAR


def _shifted(frame: pd.DataFrame, offset: float) -> pd.DataFrame:
    return frame.assign(**{c: frame[c] + offset for c in ("open", "high", "low", "close")})


def loader_of(frame: pd.DataFrame, symbols: list[str]) -> TfLoader:
    """``frame`` per symbol, each shifted by its own price level: same pattern, distinct data."""
    return TfLoader({(s, "1h"): _shifted(frame, 10.0 * i) for i, s in enumerate(symbols)})


@pytest.fixture(scope="module")
def winning() -> WalkForwardResult:
    return walk_forward(loader_of(WIN_FRAME, MANY), MANY, "1h", 100, OB_TOUCH, RULES, split="time")


@pytest.fixture(scope="module")
def demo() -> pd.DataFrame:
    return DemoLoader().load("EURUSD", "1h", 300)


# --- splits -------------------------------------------------------------------------------


def test_split_by_time_returns_the_first_test_bar() -> None:
    assert split_by_time(WIN_FRAME) == int(FRAME_BARS * 0.6)
    assert split_by_time(WIN_FRAME, 0.5) == FRAME_BARS // 2
    assert split_by_time(WIN_FRAME.iloc[:2], 0.01) == 1  # both parts keep at least one bar
    assert split_by_time(WIN_FRAME.iloc[:2], 0.99) == 1


def test_splits_floor_without_float_error() -> None:
    assert split_by_time(pd.DataFrame({"close": range(90)}), 0.7) == 63  # 90 * 0.7 = 62.99...
    train, _ = split_by_symbols([f"Z{i}" for i in range(100)], 0.29, seed=0)
    assert len(train) == 29  # 100 * 0.29 = 28.99...


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, float("nan"), True, "0.5"])
def test_split_by_time_rejects_a_bad_fraction(fraction: float) -> None:
    with pytest.raises(ValueError, match="train_fraction"):
        split_by_time(WIN_FRAME, fraction)


def test_split_by_time_needs_two_bars() -> None:
    with pytest.raises(ValueError, match="2 bars"):
        split_by_time(WIN_FRAME.iloc[:1])


def test_split_by_symbols_is_a_seeded_partition() -> None:
    symbols = [f"X{i}" for i in range(10)]
    train, test = split_by_symbols([*symbols, "X3"], 0.6, seed=1)

    assert len(train) == 6 and len(test) == 4
    assert sorted((*train, *test)) == sorted(symbols)
    assert split_by_symbols(symbols, 0.6, seed=1) == (train, test)
    assert list(train) == [s for s in symbols if s in train]  # input order is kept
    others = {split_by_symbols(symbols, 0.6, seed=seed) for seed in range(2, 8)}
    assert any(other != (train, test) for other in others)


def test_split_by_symbols_keeps_one_symbol_on_each_side() -> None:
    assert split_by_symbols(["A", "B"], 0.99, seed=0)[1] != ()
    assert split_by_symbols(["A", "B"], 0.01, seed=0)[0] != ()
    with pytest.raises(ValueError, match="2 distinct"):
        split_by_symbols(["A", "A"], 0.5, seed=0)
    with pytest.raises(ValueError, match="seed"):
        split_by_symbols(["A", "B"], 0.5, seed=-1)


# --- no leakage across the boundary ---------------------------------------------------------


def _scaled(ohlc: pd.DataFrame, rows: slice, factor: float) -> pd.DataFrame:
    changed = ohlc.copy()
    for column in ("open", "high", "low", "close"):
        changed.loc[rows, column] = changed.loc[rows, column] * factor
    return changed


def test_split_outcomes_put_each_signal_on_its_side_of_the_boundary(demo: pd.DataFrame) -> None:
    signals = random_signals(demo, 40, seed=1)
    in_sample, out_of_sample = split_outcomes(demo, signals, 180, RULES)

    assert len(in_sample) + len(out_of_sample) == len(signals)
    assert all(o.signal.bar_index < 180 for o in in_sample)
    assert all(o.signal.bar_index >= 180 for o in out_of_sample)


def test_in_sample_outcomes_never_see_test_bars(demo: pd.DataFrame) -> None:
    close = float(demo["close"].iloc[178])
    straddling = make_signal(low=close - 0.002, high=close, bar_index=178, price=close)
    signals = (*random_signals(demo, 40, seed=1), straddling)
    in_sample, _ = split_outcomes(demo, signals, 180, RULES)
    shifted, _ = split_outcomes(_scaled(demo, slice(180, None), 1.5), signals, 180, RULES)

    assert shifted == in_sample
    assert in_sample[-1].signal == straddling and in_sample[-1].exit_reason == "open"
    for outcome in in_sample:
        if outcome.r_multiple is not None:  # closed: the whole horizon lies in the train part
            assert outcome.signal.bar_index + RULES.time_stop_bars < 180


def test_out_of_sample_outcomes_read_no_train_bar_but_their_own_atr_history(
    demo: pd.DataFrame,
) -> None:
    signals = random_signals(demo, 40, seed=1, start=180)
    _, out_of_sample = split_outcomes(demo, signals, 180, RULES)
    first = min(signal.bar_index for signal in signals)
    history = first - ATR_PERIOD - 1  # bars before this feed no out-of-sample ATR
    _, shifted = split_outcomes(_scaled(demo, slice(0, history - 1), 0.7), signals, 180, RULES)

    assert shifted == out_of_sample
    assert all(o.signal.bar_index >= 180 for o in out_of_sample)


def test_walk_forward_in_sample_ignores_bars_after_the_boundary() -> None:
    symbols = ["A", "B"]
    late = 0.9  # boundary 27: the bar-24 trade's horizon crosses it, so it stays in-sample open
    base = walk_forward(
        loader_of(WIN_FRAME, symbols),
        symbols,
        "1h",
        100,
        OB_TOUCH,
        RULES,
        split="time",
        train_fraction=late,
    )
    crashed = walk_forward(
        loader_of(_scaled(WIN_FRAME, slice(27, None), 0.5), symbols),
        symbols,
        "1h",
        100,
        OB_TOUCH,
        RULES,
        split="time",
        train_fraction=late,
    )

    assert base.windows[0].boundary == 27
    assert base.in_sample == crashed.in_sample
    assert base.in_sample.n_open == 2 and base.in_sample.n == 0
    assert base.out_of_sample.n == 0


# --- verdict --------------------------------------------------------------------------------


def _stats(*rs: float) -> backtest.BacktestStats:
    return summarise(make_outcome(r) for r in rs)


def _full(r: float) -> backtest.BacktestStats:
    """A baseline of exactly ``LOW_SAMPLE_N`` trades of ``r``."""
    return _stats(*[r] * LOW_SAMPLE_N)


def test_verdict_passes_a_positive_interval_above_both_baselines() -> None:
    assert verdict(_full(1.0), _full(0.0), _full(-1.0)) == "pass"


def test_verdict_checks_the_sample_size_first() -> None:
    small = _stats(*[1.0] * (LOW_SAMPLE_N - 1))

    assert verdict(small, _full(0.0), _full(-1.0)) == "insufficient"


def test_verdict_is_insufficient_without_a_full_baseline() -> None:
    thin = _stats(*[0.0] * (LOW_SAMPLE_N - 1))

    assert verdict(_full(1.0), _stats(), _full(-1.0)) == "insufficient"
    assert verdict(_full(1.0), _full(0.0), _stats()) == "insufficient"
    assert verdict(_full(1.0), thin, _full(-1.0)) == "insufficient"
    assert verdict(_full(1.0), _full(0.0), thin) == "insufficient"


def test_verdict_fails_an_interval_touching_zero_or_a_tied_baseline() -> None:
    coin = _stats(*[1.0, -1.0] * LOW_SAMPLE_N)

    assert verdict(coin, _full(-1.0), _full(-1.0)) == "fail"
    assert verdict(_full(1.0), _full(1.0), _full(-1.0)) == "fail"
    assert verdict(_full(1.0), _full(0.0), _full(1.5)) == "fail"


# --- walk-forward end to end ----------------------------------------------------------------


def test_a_strategy_right_by_construction_passes(winning: WalkForwardResult) -> None:
    assert winning.verdict == "pass"
    assert winning.out_of_sample.n == len(MANY)
    assert winning.out_of_sample.expectancy_r == pytest.approx(1.0)
    assert winning.in_sample.n == 0  # every signal sits after the 60% boundary
    assert winning.flipped_baseline.expectancy_r == pytest.approx(-1.0)
    random = winning.random_baseline
    assert random.n + random.n_open + random.n_void == RANDOM_DRAWS * len(MANY)
    assert random.n >= LOW_SAMPLE_N
    assert random.expectancy_r is not None and random.expectancy_r < 0.5
    assert winning.random_draws == RANDOM_DRAWS
    assert all(w.boundary == split_by_time(WIN_FRAME) for w in winning.windows)
    assert all(w.out_of_sample_signals == 1 and w.in_sample_signals == 0 for w in winning.windows)
    assert winning.windows[0].boundary_time == str(WIN_FRAME["time"].iloc[18])


def test_the_same_strategy_wrong_by_construction_fails() -> None:
    result = walk_forward(
        loader_of(LOSS_FRAME, MANY), MANY, "1h", 100, OB_TOUCH, RULES, split="time"
    )

    assert result.verdict == "fail"
    assert result.out_of_sample.expectancy_r == pytest.approx(-1.0)
    assert result.flipped_baseline.expectancy_r == pytest.approx(1.0)


def test_few_out_of_sample_trades_are_insufficient() -> None:
    symbols = MANY[:3]
    result = walk_forward(
        loader_of(WIN_FRAME, symbols), symbols, "1h", 100, OB_TOUCH, RULES, split="time"
    )

    assert result.out_of_sample.n == 3 and result.verdict == "insufficient"


def test_symbol_split_trains_and_tests_on_different_symbols() -> None:
    symbols = [f"Y{i}" for i in range(6)]
    result = walk_forward(
        loader_of(WIN_FRAME, symbols),
        symbols,
        "1h",
        100,
        OB_TOUCH,
        RULES,
        split="symbols",
        train_fraction=0.5,
        seed=2,
    )
    train, test = split_by_symbols(symbols, 0.5, seed=2)

    roles = {w.symbol: w.boundary for w in result.windows}
    assert {s for s, b in roles.items() if b == FRAME_BARS} == set(train)
    assert {s for s, b in roles.items() if b == 0} == set(test)
    assert all(w.boundary_time is None for w in result.windows if w.symbol in train)
    assert result.in_sample.n == 3 and result.out_of_sample.n == 3
    assert result.flipped_baseline.n == 3
    random = result.random_baseline
    assert random.n + random.n_open + random.n_void == RANDOM_DRAWS * 3


def test_the_seed_drives_the_random_baseline(winning: WalkForwardResult) -> None:
    other = walk_forward(
        loader_of(WIN_FRAME, MANY), MANY, "1h", 100, OB_TOUCH, RULES, split="time", seed=1
    )

    assert other.random_baseline != winning.random_baseline
    assert other.out_of_sample.n == winning.out_of_sample.n
    assert other.flipped_baseline.expectancy_r == winning.flipped_baseline.expectancy_r


def test_the_random_baseline_stays_on_the_test_window(monkeypatch: pytest.MonkeyPatch) -> None:
    drawn: list[Signal] = []

    def recording(*args: Any, **kwargs: Any) -> tuple[Signal, ...]:
        signals = random_signals(*args, **kwargs)
        drawn.extend(signals)
        return signals

    monkeypatch.setattr(walkforward, "random_signals", recording)
    symbols = ["A", "B"]
    result = walk_forward(
        loader_of(WIN_FRAME, symbols), symbols, "1h", 100, OB_TOUCH, RULES, split="time"
    )

    boundary = result.windows[0].boundary
    assert boundary > MIN_BARS  # so starting the draws at MIN_BARS would reach the train part
    assert len(drawn) == RANDOM_DRAWS * len(symbols)
    assert all(signal.bar_index >= boundary for signal in drawn)


def test_one_bare_string_of_symbols_is_rejected() -> None:
    with pytest.raises(ValueError, match="not one string"):
        walk_forward(loader_of(WIN_FRAME, ["A"]), "AB", "1h", 100, OB_TOUCH, RULES, split="time")


@pytest.mark.parametrize("boundary", [-1, FRAME_BARS + 1])
def test_split_outcomes_reject_a_boundary_outside_the_frame(boundary: int) -> None:
    with pytest.raises(ValueError, match="outside"):
        split_outcomes(WIN_FRAME, (), boundary, RULES)


def test_split_outcomes_at_the_frame_edges() -> None:
    signals = replay_signals()

    assert split_outcomes(WIN_FRAME, signals, 0, RULES)[0] == ()
    assert split_outcomes(WIN_FRAME, signals, FRAME_BARS, RULES)[1] == ()
    at, before = (
        split_outcomes(WIN_FRAME, signals, b, RULES) for b in (SIGNAL_BAR, SIGNAL_BAR + 1)
    )
    assert len(at[1]) == 1 and at[1][0].exit_reason == "target"  # bar s itself is out-of-sample
    assert len(before[0]) == 1 and before[0][0].exit_reason == "open"  # bar s - 1 stays in-sample


def test_a_failing_symbol_is_recorded_and_skipped() -> None:
    loader = loader_of(WIN_FRAME, ["A", "B"])
    result = walk_forward(loader, ["A", "MISSING", "B"], "1h", 100, OB_TOUCH, RULES, split="time")

    assert [w.symbol for w in result.windows] == ["A", "B"]
    assert [f.symbol for f in result.failures] == ["MISSING"]
    assert not loader.closed


def test_duplicate_symbols_are_backtested_once() -> None:
    loader = loader_of(WIN_FRAME, ["A"])
    result = walk_forward(loader, ["A", "A"], "1h", 100, OB_TOUCH, RULES, split="time")

    assert [w.symbol for w in result.windows] == ["A"] and loader.calls == [("A", "1h")]


def test_a_frame_longer_than_bars_is_trimmed() -> None:
    result = walk_forward(
        loader_of(WIN_FRAME, ["A"]), ["A"], "1h", FRAME_BARS - 2, OB_TOUCH, RULES, split="time"
    )

    assert result.windows[0].bars == FRAME_BARS - 2


def test_same_inputs_same_result(winning: WalkForwardResult) -> None:
    again = walk_forward(loader_of(WIN_FRAME, MANY), MANY, "1h", 100, OB_TOUCH, RULES, split="time")

    assert again == winning


def test_to_dict_is_strict_json(winning: WalkForwardResult) -> None:
    odd = replace(winning, in_sample=replace(winning.in_sample, total_r=float("inf")))
    payload = json.loads(json.dumps(odd.to_dict(), allow_nan=False))

    assert payload["verdict"] == "pass" and payload["split"] == "time"
    assert payload["train_fraction"] == 0.6 and payload["strategy"] == "test"
    assert payload["in_sample"]["total_r"] is None
    assert payload["out_of_sample"]["n"] == len(MANY)
    assert set(payload) >= {"random_baseline", "flipped_baseline", "rules", "failures"}
    assert payload["random_draws"] == RANDOM_DRAWS
    assert payload["windows"][0] == {
        "symbol": MANY[0],
        "bars": FRAME_BARS,
        "boundary": 18,
        "boundary_time": str(WIN_FRAME["time"].iloc[18]),
        "in_sample_signals": 0,
        "out_of_sample_signals": 1,
    }


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"split": "random"}, "split"),
        ({"split": "time", "train_fraction": 1.0}, "train_fraction"),
        ({"split": "time", "seed": -1}, "seed"),
        ({"split": "time", "seed": 2**32}, "seed"),
        ({"split": "time", "stride": 0}, "stride"),
        ({"split": "time", "stride": True}, "stride"),
        ({"split": "time", "bars": 100.0}, "bars"),
        ({"split": "symbols", "bars": 1}, "bars"),
    ],
)
def test_bad_arguments_raise_before_anything_loads(kwargs: dict[str, object], match: str) -> None:
    loader = loader_of(WIN_FRAME, ["A", "B"])
    args: dict[str, object] = {"bars": 100, **kwargs}
    bars = args.pop("bars")

    with pytest.raises(ValueError, match=match):
        walk_forward(loader, ["A", "B"], "1h", bars, OB_TOUCH, RULES, **args)  # type: ignore[arg-type]
    assert loader.calls == []


def test_symbol_split_with_one_symbol_raises_before_loading() -> None:
    loader = loader_of(WIN_FRAME, ["A"])

    with pytest.raises(ValueError, match="2 distinct"):
        walk_forward(loader, ["A"], "1h", 100, OB_TOUCH, RULES, split="symbols")
    assert loader.calls == []


# --- sweep ----------------------------------------------------------------------------------

AGED = strategy(
    swing_length=2,
    zone_kinds=["OB"],
    statuses=["TOUCHING"],
    require=[{"key": "max_zone_age", "params": {"bars": 10}}],
)


def test_sweep_variants_change_one_condition_param() -> None:
    variants = sweep_variants(AGED, "max_zone_age", {"bars": [1, 10, 50]})

    assert [params for params, _ in variants] == [(("bars", 1),), (("bars", 10),), (("bars", 50),)]
    assert [v.require[0].params["bars"] for _, v in variants] == [1, 10, 50]
    assert all(v.slug == AGED.slug and v.zone_kinds == AGED.zone_kinds for _, v in variants)


@pytest.mark.parametrize(
    ("condition", "grid", "match"),
    [
        ("max_zone_age", {}, "at least one"),
        ("max_zone_age", {"bars": [1, 2, 3, 4]}, "at most"),
        ("max_zone_age", {"bars": []}, "at least one"),
        ("max_zone_age", {"bars": [1, 1]}, "duplicate"),
        ("max_zone_age", {"bars": "abc"}, "list"),
        ("max_zone_age", {"bars": [1.0, float("nan")]}, "finite"),
        ("max_zone_age", {"bars": [[1], [2]]}, "numbers"),
        ("max_zone_age", {f"p{i}": [1, 2, 3] for i in range(4)}, "variants"),
        ("fresh", {"bars": [1]}, "not used"),
    ],
)
def test_sweep_variants_reject_a_bad_grid(
    condition: str, grid: dict[str, list[int]], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        sweep_variants(AGED, condition, grid)


def test_sweep_variants_validate_the_condition_params() -> None:
    with pytest.raises(ConditionParamError):
        sweep_variants(AGED, "max_zone_age", {"bars": [0]})


def test_sweep_reports_out_of_sample_only_and_loads_each_symbol_once() -> None:
    symbols = ["A", "B", "C"]
    loader = loader_of(WIN_FRAME, symbols)
    points = sweep(
        loader,
        symbols,
        "1h",
        100,
        AGED,
        RULES,
        condition="max_zone_age",
        grid={"bars": [1, 10]},
        split="time",
    )

    assert [dict(p.params) for p in points] == [{"bars": 1}, {"bars": 10}]
    assert all(p.n_variants == 2 for p in points)
    assert [p.out_of_sample.n for p in points] == [0, 3]  # the OB is 5 bars old at its touch
    assert [p.verdict for p in points] == ["insufficient", "insufficient"]
    assert sorted(loader.calls) == [(s, "1h") for s in symbols]
    payload = json.loads(json.dumps([p.to_dict() for p in points], allow_nan=False))
    assert "in_sample" not in payload[0] and not hasattr(points[0], "in_sample")
    assert payload[1]["params"] == {"bars": 10} and payload[1]["out_of_sample"]["n"] == 3
    assert payload[1]["n_variants"] == 2


def test_sweep_loads_a_failing_symbol_once_and_records_it_on_every_point() -> None:
    loader = loader_of(WIN_FRAME, ["A"])
    points = sweep(
        loader,
        ["A", "MISSING"],
        "1h",
        100,
        AGED,
        RULES,
        condition="max_zone_age",
        grid={"bars": [1, 10, 50]},
        split="symbols",
        train_fraction=0.5,
    )

    assert loader.calls.count(("MISSING", "1h")) == 1 and loader.calls.count(("A", "1h")) == 1
    assert all([f.symbol for f in p.failures] == ["MISSING"] for p in points)


def test_a_symbol_split_sweep_gives_every_variant_the_same_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partitions: list[dict[str, int]] = []

    def recording(*args: Any, **kwargs: Any) -> WalkForwardResult:
        result = walk_forward(*args, **kwargs)
        partitions.append({w.symbol: w.boundary for w in result.windows})
        return result

    monkeypatch.setattr(sweep_module, "walk_forward", recording)
    symbols = ["A", "B", "C", "D"]
    sweep(
        loader_of(WIN_FRAME, symbols),
        symbols,
        "1h",
        100,
        AGED,
        RULES,
        condition="max_zone_age",
        grid={"bars": [1, 10, 50]},
        split="symbols",
        train_fraction=0.5,
        seed=3,
    )

    train, _ = split_by_symbols(symbols, 0.5, seed=3)
    assert len(partitions) == 3 and all(p == partitions[0] for p in partitions)
    assert {s for s, b in partitions[0].items() if b > 0} == set(train)


def test_sweep_rejects_a_bad_param_before_anything_loads() -> None:
    loader = loader_of(WIN_FRAME, ["A"])

    with pytest.raises(ConditionParamError):
        sweep(
            loader,
            ["A"],
            "1h",
            100,
            AGED,
            RULES,
            condition="max_zone_age",
            grid={"bars": [0, 5]},
            split="time",
        )
    assert loader.calls == []
