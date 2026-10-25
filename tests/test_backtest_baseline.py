"""Null baselines: random entries with the strategy's count and R geometry, and flipped signals."""

import pandas as pd
import pytest
from backtest_support import OB_TOUCH, make_signal, ob_frame
from conftest import Candle

from smc_scanner.backtest.baseline import (
    MAX_RANDOM_SIGNALS,
    direction_flipped,
    flipped_signals,
    random_entries,
    random_signals,
)
from smc_scanner.backtest.outcome import ExitRules, label
from smc_scanner.backtest.replay import Signal, replay
from smc_scanner.backtest.stats import summarise
from smc_scanner.config import MIN_BARS
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.models import BEARISH, BULLISH, Direction
from smc_scanner.structure import atr as average_true_range

RULES = ExitRules(rr=1.0, time_stop_bars=5)
ENTRY: Candle = (103.0, 104.0, 102.5, 103.8)
WIN: Candle = (103.8, 107.0, 103.5, 106.8)
HOLD: Candle = (106.8, 106.9, 106.6, 106.8)


@pytest.fixture(scope="module")
def demo() -> pd.DataFrame:
    return DemoLoader().load("EURUSD", "1h", 300)


@pytest.fixture(scope="module")
def winner() -> tuple[pd.DataFrame, tuple[Signal, ...]]:
    ohlc = ob_frame([ENTRY, WIN, HOLD, HOLD, HOLD])
    return ohlc, replay("SYN", ohlc, OB_TOUCH)


def test_random_entries_place_the_requested_number_of_signals(demo: pd.DataFrame) -> None:
    signals = random_signals(demo, 40, seed=1)
    stats = random_entries(demo, 40, RULES, seed=1)

    assert len(signals) == 40
    assert stats.n + stats.n_open + stats.n_void == 40
    assert all(MIN_BARS <= s.bar_index < len(demo) for s in signals)
    assert [s.bar_index for s in signals] == sorted(s.bar_index for s in signals)
    assert {s.direction for s in signals} == {BULLISH, BEARISH}
    assert len({s.bar_index for s in signals}) == 40  # distinct bars while the window has room


def test_more_random_entries_than_bars_reuse_bars(demo: pd.DataFrame) -> None:
    signals = random_signals(demo, 30, seed=1, start=len(demo) - 10)

    assert len(signals) == 30 and {s.bar_index for s in signals} <= set(range(len(demo) - 10, 300))


def test_random_entries_copy_the_strategy_direction_mix(demo: pd.DataFrame) -> None:
    def at(index: int, direction: Direction) -> Signal:
        close = float(demo["close"].iloc[index])
        low, high = close - 0.002, close + 0.002
        return make_signal(direction=direction, low=low, high=high, bar_index=index, price=close)

    strategy_signals = [at(100, BULLISH), at(120, BULLISH), at(140, BULLISH), at(160, BEARISH)]
    randoms = random_signals(demo, strategy_signals, seed=6)

    assert sorted(s.direction for s in randoms) == sorted(s.direction for s in strategy_signals)


def test_random_entries_match_the_strategy_signal_count(
    winner: tuple[pd.DataFrame, tuple[Signal, ...]],
) -> None:
    ohlc, signals = winner
    stats = random_entries(ohlc, signals, RULES, seed=3)

    assert stats.n + stats.n_open + stats.n_void == len(signals)


def test_random_entries_are_seeded(demo: pd.DataFrame) -> None:
    first = random_entries(demo, 60, RULES, seed=7)

    assert random_entries(demo, 60, RULES, seed=7) == first
    assert random_signals(demo, 60, seed=7) == random_signals(demo, 60, seed=7)
    assert random_entries(demo, 60, RULES, seed=8) != first


def test_random_entries_default_to_one_atr_of_risk(demo: pd.DataFrame) -> None:
    for signal in random_signals(demo, 10, seed=2):
        bar_atr = average_true_range(demo.iloc[: signal.bar_index + 1])
        close = float(demo["close"].iloc[signal.bar_index])
        far_edge = signal.zone.bottom if signal.direction == BULLISH else signal.zone.top
        assert abs(close - far_edge) == pytest.approx(bar_atr)
        assert signal.zone.bottom <= signal.zone.top
        assert signal.bar_time == str(demo["time"].iloc[signal.bar_index])
        assert signal.row.price == close


def test_random_entries_reuse_the_strategy_stop_distance(demo: pd.DataFrame) -> None:
    index = 100
    close = float(demo["close"].iloc[index])
    bar_atr = average_true_range(demo.iloc[: index + 1])
    strategy_signal = make_signal(
        low=close - 2.5 * bar_atr, high=close + bar_atr, bar_index=index, price=close
    )
    (random,) = random_signals(demo, [strategy_signal], seed=4)

    random_atr = average_true_range(demo.iloc[: random.bar_index + 1])
    random_close = float(demo["close"].iloc[random.bar_index])
    far_edge = random.zone.bottom if random.direction == BULLISH else random.zone.top
    assert abs(random_close - far_edge) / random_atr == pytest.approx(2.5)
    assert random.zone.kind == "OB" and random.row.instrument == "SYN"


def test_a_strategy_signal_beyond_its_own_stop_gives_a_zero_distance(demo: pd.DataFrame) -> None:
    close = float(demo["close"].iloc[100])
    beyond = make_signal(low=close + 0.01, high=close + 0.02, bar_index=100, price=close)
    (random,) = random_signals(demo, [beyond], seed=4)

    random_close = float(demo["close"].iloc[random.bar_index])
    assert random.zone.top == random.zone.bottom == random_close


def test_random_entries_respect_start_and_an_empty_window(demo: pd.DataFrame) -> None:
    late = random_signals(demo, 25, seed=5, start=250)

    assert all(signal.bar_index >= 250 for signal in late)
    assert random_signals(demo, 5, seed=5, start=len(demo)) == ()
    assert random_signals(demo, 0, seed=5) == ()
    assert random_entries(demo, 0, RULES, seed=5).n == 0


@pytest.mark.parametrize("count", [-1, True, MAX_RANDOM_SIGNALS + 1])
def test_random_entries_reject_a_bad_count(demo: pd.DataFrame, count: int) -> None:
    with pytest.raises(ValueError, match="count"):
        random_signals(demo, count, seed=0)


@pytest.mark.parametrize("seed", [-1, True, 1.5, 2**32])
def test_random_entries_reject_a_bad_seed(demo: pd.DataFrame, seed: int) -> None:
    with pytest.raises(ValueError, match="seed"):
        random_signals(demo, 3, seed=seed)


def test_random_entries_reject_a_start_before_the_atr_warmup(demo: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="start"):
        random_signals(demo, 3, seed=0, start=MIN_BARS - 2)


def test_flipped_signals_mirror_stop_and_target_around_the_entry(
    winner: tuple[pd.DataFrame, tuple[Signal, ...]],
) -> None:
    ohlc, signals = winner
    (flipped,) = flipped_signals(ohlc, signals)
    original, mirrored = label(ohlc, signals[0], RULES), label(ohlc, flipped, RULES)

    assert flipped.direction == BEARISH and flipped.row.zone == "bear OB"
    assert flipped.bar_index == signals[0].bar_index
    assert original.entry is not None and original.stop is not None
    assert original.target is not None
    assert mirrored.entry == original.entry
    assert mirrored.stop == pytest.approx(2 * original.entry - original.stop)
    assert mirrored.target == pytest.approx(2 * original.entry - original.target)
    assert original.r_multiple == pytest.approx(1.0)
    assert mirrored.exit_reason == "stop" and mirrored.r_multiple == pytest.approx(-1.0)


def test_flipping_twice_restores_the_trade(
    winner: tuple[pd.DataFrame, tuple[Signal, ...]],
) -> None:
    ohlc, signals = winner
    twice = flipped_signals(ohlc, flipped_signals(ohlc, signals))

    assert twice[0].direction == signals[0].direction
    assert label(ohlc, twice[0], RULES).stop == pytest.approx(label(ohlc, signals[0], RULES).stop)


def test_direction_flipped_counts_the_same_signals(demo: pd.DataFrame) -> None:
    signals = random_signals(demo, 30, seed=9)
    original = summarise(label(demo, s, RULES) for s in signals)
    flipped = direction_flipped(demo, signals, RULES)

    assert flipped.n + flipped.n_open + flipped.n_void == len(signals)
    assert flipped.n_open == original.n_open
    assert direction_flipped(demo, signals, RULES) == flipped


def test_a_signal_on_the_last_bar_flips_around_its_close() -> None:
    ohlc = ob_frame()
    last = len(ohlc) - 1
    close = float(ohlc["close"].iloc[last])
    signal = make_signal(low=close - 1.0, high=close, bar_index=last, price=close)
    (flipped,) = flipped_signals(ohlc, [signal])

    assert flipped.zone.top == pytest.approx(close + 1.0)
    assert label(ohlc, flipped, RULES).exit_reason == "open"
