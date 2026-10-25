"""Point-in-time replay: first hit per zone, no lookahead, last step equals the live scan."""

from dataclasses import replace

import pandas as pd
import pytest
from backtest_support import OB_FORMED, OB_TOUCH, OB_TOUCH_INDEX, ob_frame
from conftest import OB_BOTTOM, OB_TOP

from smc_scanner.backtest.replay import Signal, ZoneKey, replay, scan_at, zone_key
from smc_scanner.config import MIN_BARS
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.models import BEARISH, BULLISH
from smc_scanner.strategy.engine import scan_instrument_with_strategy

DEMO_BARS = 200


@pytest.fixture(scope="module")
def demo() -> pd.DataFrame:
    return DemoLoader().load("EURUSD", "1h", DEMO_BARS)


@pytest.fixture(scope="module")
def demo_signals(demo: pd.DataFrame) -> tuple[Signal, ...]:
    return replay("EURUSD", demo, None)


def test_known_ob_signals_once_at_its_touch_bar() -> None:
    ohlc = ob_frame()
    signals = replay("SYN", ohlc, OB_TOUCH)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.bar_index == OB_TOUCH_INDEX
    assert signal.bar_time == str(ohlc["time"].iloc[OB_TOUCH_INDEX])
    assert signal.zone == ZoneKey("OB", BULLISH, OB_FORMED, OB_TOP, OB_BOTTOM)
    assert signal.direction == BULLISH
    assert signal.row.status == "TOUCHING" and signal.row.zone == "bull OB"


def test_later_bars_neither_change_the_signal_nor_repeat_it() -> None:
    retouch = [(105.0, 106.0, 101.8, 104.0), (104.0, 105.0, 101.6, 103.0)]
    crash = [(103.0, 103.0, 80.0, 81.0), (81.0, 82.0, 79.0, 80.0)]
    base = replay("SYN", ob_frame(), OB_TOUCH)
    extended = replay("SYN", ob_frame([*retouch, *crash]), OB_TOUCH)

    assert extended[: len(base)] == base
    assert all(signal.zone != base[0].zone for signal in extended[len(base) :])


def test_last_replay_step_equals_the_live_scan(demo: pd.DataFrame) -> None:
    last = len(demo) - 1

    assert scan_at("EURUSD", demo, None, last) == scan_instrument_with_strategy("EURUSD", demo)


def test_signals_on_the_last_bar_are_live_scan_rows(
    demo: pd.DataFrame, demo_signals: tuple[Signal, ...]
) -> None:
    live = scan_instrument_with_strategy("EURUSD", demo)
    last = [signal.row for signal in demo_signals if signal.bar_index == len(demo) - 1]

    assert all(row in live for row in last)


@pytest.mark.parametrize("cut", [120, 160])
def test_replay_reads_nothing_after_each_bar(
    demo: pd.DataFrame, demo_signals: tuple[Signal, ...], cut: int
) -> None:
    truncated = replay("EURUSD", demo.iloc[: cut + 1], None)

    assert truncated == tuple(signal for signal in demo_signals if signal.bar_index <= cut)


def test_each_zone_signals_once_with_a_consistent_key(
    demo: pd.DataFrame, demo_signals: tuple[Signal, ...]
) -> None:
    assert demo_signals, "the demo frame should produce signals"
    # Unique without the edges too: a zone whose edges drifted between prefixes would re-signal.
    origins = [(s.zone.kind, s.zone.direction, s.zone.formed_index) for s in demo_signals]
    assert len(origins) == len(set(origins))
    for signal in demo_signals:
        assert signal.bar_index >= MIN_BARS
        assert signal.zone.formed_index == signal.bar_index - signal.row.zone_age
        assert signal.row.bar_time == str(demo["time"].iloc[signal.bar_index])
        assert signal.direction in (BULLISH, BEARISH)


def test_stride_signals_a_subset_of_the_zones(
    demo: pd.DataFrame, demo_signals: tuple[Signal, ...]
) -> None:
    sampled = replay("EURUSD", demo, None, stride=5)

    assert {signal.zone for signal in sampled} <= {signal.zone for signal in demo_signals}
    assert all((signal.bar_index - MIN_BARS) % 5 == 0 for signal in sampled)


def test_frame_shorter_than_start_has_no_signals() -> None:
    assert replay("SYN", ob_frame().iloc[:MIN_BARS], OB_TOUCH) == ()


@pytest.mark.parametrize(("start", "stride"), [(MIN_BARS - 2, 1), (MIN_BARS, 0)])
def test_replay_rejects_bad_start_or_stride(start: int, stride: int) -> None:
    with pytest.raises(ValueError):
        replay("SYN", ob_frame(), OB_TOUCH, start=start, stride=stride)


@pytest.mark.parametrize("index", [-1, OB_TOUCH_INDEX + 1])
def test_scan_at_rejects_an_index_outside_the_frame(index: int) -> None:
    with pytest.raises(IndexError):
        scan_at("SYN", ob_frame(), OB_TOUCH, index)


def test_zone_key_rejects_an_unknown_label() -> None:
    row = scan_at("SYN", ob_frame(), OB_TOUCH, OB_TOUCH_INDEX)[0]

    assert zone_key(row, OB_TOUCH_INDEX).kind == "OB"
    with pytest.raises(ValueError, match="zone label"):
        zone_key(replace(row, zone="sideways OB"), OB_TOUCH_INDEX)
