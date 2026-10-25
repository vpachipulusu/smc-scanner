"""Backtest report: per-symbol and pooled results, failures recorded, CSV rows and JSON."""

import ast
import json
import logging
import math
from dataclasses import replace
from pathlib import Path

import pytest
from backtest_support import OB_TOUCH, OB_TOUCH_INDEX, ob_frame, strategy
from conftest import Candle
from mtf_support import TfLoader

from smc_scanner import backtest
from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.backtest.report import ROW_COLUMNS, run_backtest
from smc_scanner.backtest.stats import summarise
from smc_scanner.config import MAX_BARS, MIN_BARS
from smc_scanner.scanner import ScanOptions
from smc_scanner.strategy import UnknownConditionError

# After the OB touch (close 103): entry 103 at the next open, stop 99.5, target 106.5 at rr 1.
ENTRY: Candle = (103.0, 104.0, 102.5, 103.8)
WIN: Candle = (103.8, 107.0, 103.5, 106.8)
LOSS: Candle = (103.8, 104.0, 99.0, 99.4)
HOLD_WIN: Candle = (106.8, 106.9, 106.6, 106.8)
HOLD_LOSS: Candle = (99.4, 99.6, 99.2, 99.4)
RULES = ExitRules(rr=1.0, time_stop_bars=5)


@pytest.fixture
def loader() -> TfLoader:
    return TfLoader(
        {
            ("AAA", "1h"): ob_frame([ENTRY, WIN, HOLD_WIN, HOLD_WIN, HOLD_WIN]),
            ("BBB", "1h"): ob_frame([ENTRY, LOSS, HOLD_LOSS, HOLD_LOSS, HOLD_LOSS]),
        }
    )


def test_report_pools_symbols_and_records_a_failure(
    loader: TfLoader, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="smc_scanner.backtest.report"):
        report = run_backtest(loader, ["AAA", "MISSING", "BBB"], "1h", 100, OB_TOUCH, RULES)

    assert [result.symbol for result in report.symbols] == ["AAA", "BBB"]
    assert [failure.symbol for failure in report.failures] == ["MISSING"]
    assert "LoaderError" in report.failures[0].error
    assert len([r for r in caplog.records if "MISSING" in r.getMessage()]) == 1

    aaa, bbb = report.symbols
    assert aaa.outcomes[0].signal.bar_index == OB_TOUCH_INDEX
    assert aaa.outcomes[0].exit_reason == "target"
    assert aaa.outcomes[0].r_multiple == pytest.approx(1.0)
    assert bbb.outcomes[0].exit_reason == "stop"
    assert report.pooled.n == aaa.stats.n + bbb.stats.n
    assert report.pooled.n >= 2
    assert not loader.closed  # the caller owns the loader


def test_pooled_outcomes_follow_signal_time_then_symbol(loader: TfLoader) -> None:
    report = run_backtest(loader, ["BBB", "AAA"], "1h", 100, OB_TOUCH, RULES)
    pooled = report.pooled_outcomes()

    keys = [(o.signal.bar_time, o.signal.row.instrument) for o in pooled]
    assert keys == sorted(keys)
    assert keys[0][1] == "AAA"  # same bar time: symbol breaks the tie
    assert [row["symbol"] for row in report.to_rows()][0] == "BBB"  # rows keep symbol order
    assert summarise(pooled) == report.pooled


def test_rows_are_flat_records_with_fixed_columns(loader: TfLoader) -> None:
    report = run_backtest(loader, ["AAA", "BBB"], "1h", 100, OB_TOUCH, RULES)
    rows = report.to_rows()

    assert len(rows) == sum(len(result.outcomes) for result in report.symbols)
    assert all(tuple(row) == ROW_COLUMNS for row in rows)
    first = rows[0]
    assert first["symbol"] == "AAA" and first["zone"] == "bull OB"
    assert first["direction"] == 1 and first["exit_reason"] == "target"
    assert all(isinstance(value, str | int | float | bool | type(None)) for value in first.values())


def test_to_dict_is_strict_json(loader: TfLoader) -> None:
    report = run_backtest(loader, ["AAA", "MISSING", "BBB"], "1h", 100, OB_TOUCH, RULES, seed=4)
    payload = json.loads(json.dumps(report.to_dict(), allow_nan=False))

    assert payload["strategy"] == "test" and payload["timeframe"] == "1h"
    assert payload["bars"] == 100 and payload["seed"] == 4
    assert payload["rules"] == {
        "rr": 1.0,
        "stop_buffer_atr": 0.0,
        "time_stop_bars": 5,
        "spread": 0.0,
        "min_risk_atr": 0.1,
    }
    assert payload["stride"] == 1
    assert payload["pooled"]["n"] == report.pooled.n
    assert [item["symbol"] for item in payload["symbols"]] == ["AAA", "BBB"]
    assert payload["failures"][0]["symbol"] == "MISSING"
    assert len(payload["signals"]) == len(report.to_rows())


def test_same_inputs_same_report(loader: TfLoader) -> None:
    first = run_backtest(loader, ["AAA", "BBB"], "1h", 100, OB_TOUCH, RULES)
    second = run_backtest(loader, ["AAA", "BBB"], "1h", 100, OB_TOUCH, RULES)

    assert first == second


@pytest.mark.parametrize("bars", [MIN_BARS - 1, MAX_BARS + 1])
def test_bars_out_of_range_raise(loader: TfLoader, bars: int) -> None:
    with pytest.raises(ValueError, match="bars"):
        run_backtest(loader, ["AAA"], "1h", bars, OB_TOUCH, RULES)
    assert loader.calls == []


@pytest.mark.parametrize(("seed", "stride"), [(-1, 1), (True, 1), (0, 0)])
def test_bad_seed_or_stride_raise_before_anything_loads(
    loader: TfLoader, seed: int, stride: int
) -> None:
    with pytest.raises(ValueError, match="seed|stride"):
        run_backtest(loader, ["AAA"], "1h", 100, OB_TOUCH, RULES, seed=seed, stride=stride)
    assert loader.calls == []


def test_options_override_the_strategy_scan_tuning(loader: TfLoader) -> None:
    wide = run_backtest(loader, ["AAA"], "1h", 100, OB_TOUCH, RULES, options=ScanOptions(8))

    assert all(o.signal.bar_index != OB_TOUCH_INDEX for o in wide.symbols[0].outcomes)


def test_stride_is_passed_to_replay(loader: TfLoader) -> None:
    report = run_backtest(loader, ["AAA"], "1h", 100, OB_TOUCH, RULES, stride=4)

    assert report.stride == 4
    assert all((o.signal.bar_index - MIN_BARS) % 4 == 0 for o in report.symbols[0].outcomes)


def test_a_frame_longer_than_bars_is_trimmed_to_the_latest(loader: TfLoader) -> None:
    rows = len(loader.frames[("AAA", "1h")])
    report = run_backtest(loader, ["AAA"], "1h", rows - 2, OB_TOUCH, RULES)

    assert report.symbols[0].outcomes[0].signal.bar_index == OB_TOUCH_INDEX - 2


def test_to_dict_turns_non_finite_floats_into_none(loader: TfLoader) -> None:
    report = run_backtest(loader, ["AAA"], "1h", 100, OB_TOUCH, RULES)
    odd = replace(report, pooled=replace(report.pooled, best_r=math.inf, worst_r=math.nan))

    payload = odd.to_dict()
    assert payload["pooled"]["best_r"] is None and payload["pooled"]["worst_r"] is None  # type: ignore[index]
    json.dumps(payload, allow_nan=False)


def test_unknown_condition_raises_before_anything_loads(loader: TfLoader) -> None:
    broken = strategy(require=[{"key": "no_such_condition"}])

    with pytest.raises(UnknownConditionError):
        run_backtest(loader, ["AAA"], "1h", 100, broken, RULES)
    assert loader.calls == []


def test_backtest_package_imports_no_api_schedule_or_ai() -> None:
    forbidden = ("smc_scanner.api", "smc_scanner.schedule", "smc_scanner.ai")
    package = Path(backtest.__file__).parent
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"


def test_no_symbols_gives_an_empty_report(loader: TfLoader) -> None:
    report = run_backtest(loader, [], "1h", 100, OB_TOUCH, RULES)

    assert report.symbols == () and report.failures == ()
    assert report.pooled.n == 0 and report.to_rows() == []
