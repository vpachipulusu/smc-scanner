"""Outcome labelling: entry next open, stop beyond the zone, target at rr, conservative fills."""

import math
from typing import Any

import pytest
from backtest_support import make_signal
from conftest import FLAT, Candle, frame, with_warmup

from smc_scanner.backtest.outcome import ExitRules, label
from smc_scanner.models import BEARISH
from smc_scanner.structure import atr

# A bullish zone 99-100 signalled on bar 0 (close 100.5): entry 100.5 at bar 1's open,
# stop 99, risk 1.5, target 103.5 at rr 2. Rules use a 3-bar time stop, so bars 1-3 decide it.
SIGNAL_BAR: Candle = (100.6, 101.0, 99.8, 100.5)
ENTRY_BAR: Candle = (100.5, 101.0, 100.2, 100.8)
QUIET: Candle = (100.8, 101.2, 100.4, 101.0)
RULES = ExitRules(rr=2.0, time_stop_bars=3)
ATR = 1.0


def _label(candles: list[Candle], rules: ExitRules = RULES, **signal: Any) -> Any:
    return label(frame(candles), make_signal(**signal), rules, ATR)


def test_target_before_stop_labels_plus_rr() -> None:
    hit = (100.8, 103.6, 100.6, 103.2)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, hit, QUIET])

    assert outcome.exit_reason == "target"
    assert outcome.r_multiple == pytest.approx(2.0)
    assert outcome.bars_held == 2
    assert (outcome.entry, outcome.stop, outcome.target) == (100.5, 99.0, 103.5)
    assert outcome.exit_price == 103.5


def test_stop_first_labels_minus_one_minus_spread() -> None:
    stopped = (100.8, 101.0, 98.9, 99.2)
    rules = ExitRules(rr=2.0, time_stop_bars=3, spread=0.15)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, stopped, (103.0, 104.0, 102.0, 103.8)], rules)

    assert outcome.exit_reason == "stop"
    assert outcome.r_multiple == pytest.approx(-1.0 - 0.15 / 1.5)
    assert outcome.bars_held == 2


def test_spread_is_deducted_from_a_winner_too() -> None:
    rules = ExitRules(rr=2.0, time_stop_bars=3, spread=0.3)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, (100.8, 103.6, 100.6, 103.2), QUIET], rules)

    assert outcome.r_multiple == pytest.approx(2.0 - 0.2)


def test_bar_touching_both_stop_and_target_is_a_loss() -> None:
    both = (100.8, 103.6, 98.9, 101.0)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, both, QUIET])

    assert outcome.exit_reason == "stop"
    assert outcome.r_multiple == pytest.approx(-1.0)


def test_the_entry_bar_itself_can_stop_out() -> None:
    outcome = _label([SIGNAL_BAR, (100.5, 100.9, 98.5, 99.0), QUIET, QUIET])

    assert outcome.exit_reason == "stop"
    assert outcome.bars_held == 1


def test_time_stop_closes_at_that_bars_close() -> None:
    last = (101.0, 101.4, 100.9, 101.25)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, QUIET, last, (101.0, 110.0, 101.0, 109.0)])

    assert outcome.exit_reason == "time"
    assert outcome.bars_held == 3
    assert outcome.exit_price == 101.25
    assert outcome.r_multiple == pytest.approx((101.25 - 100.5) / 1.5)


def test_horizon_beyond_the_frame_is_open_with_no_r() -> None:
    hit = (100.8, 103.6, 100.6, 103.2)  # would be a target, but the 3-bar horizon is cut off
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, hit])

    assert outcome.exit_reason == "open"
    assert outcome.r_multiple is None
    assert outcome.bars_held == 2


def test_signal_on_the_last_bar_has_no_entry() -> None:
    outcome = _label([SIGNAL_BAR])

    assert outcome.exit_reason == "open"
    assert outcome.r_multiple is None and outcome.entry is None
    assert outcome.bars_held == 0


def test_bearish_target_is_below_entry() -> None:
    hit = (100.4, 100.6, 97.4, 97.6)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, hit, QUIET], direction=BEARISH, low=101.0, high=102.0)

    assert (outcome.stop, outcome.target) == (102.0, 97.5)
    assert outcome.exit_reason == "target"
    assert outcome.r_multiple == pytest.approx(2.0)


def test_bearish_stop_above_zone_high() -> None:
    stopped = (100.8, 102.1, 100.5, 101.9)
    outcome = _label(
        [SIGNAL_BAR, ENTRY_BAR, stopped, QUIET], direction=BEARISH, low=101.0, high=102.0
    )

    assert outcome.exit_reason == "stop"
    assert outcome.r_multiple == pytest.approx(-1.0)


def test_gap_through_the_stop_fills_at_the_open() -> None:
    gapped = (98.5, 99.0, 98.0, 98.8)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, gapped, QUIET])

    assert outcome.exit_reason == "stop"
    assert outcome.exit_price == 98.5
    assert outcome.r_multiple == pytest.approx((98.5 - 100.5) / 1.5)


def test_bearish_gap_through_the_stop_fills_at_the_open() -> None:
    gapped = (102.5, 103.0, 102.2, 102.8)
    outcome = _label(
        [SIGNAL_BAR, ENTRY_BAR, gapped, QUIET], direction=BEARISH, low=101.0, high=102.0
    )

    assert outcome.exit_price == 102.5
    assert outcome.r_multiple == pytest.approx(-2.0 / 1.5)


def test_entry_opening_beyond_the_stop_is_void() -> None:
    outcome = _label([SIGNAL_BAR, (98.8, 99.5, 98.5, 99.2), QUIET, QUIET])

    assert outcome.exit_reason == "void"
    assert outcome.r_multiple is None
    assert outcome.entry == 98.8 and outcome.bars_held == 0


def test_entry_with_risk_under_min_risk_atr_is_void() -> None:
    sliver = (99.05, 99.5, 99.02, 99.3)  # 0.05 above the 99 stop: under 0.1 ATR of risk
    outcome = _label([SIGNAL_BAR, sliver, QUIET, QUIET])

    assert outcome.exit_reason == "void" and outcome.r_multiple is None
    allowed = _label(
        [SIGNAL_BAR, sliver, QUIET, QUIET], ExitRules(time_stop_bars=3, min_risk_atr=0)
    )
    assert allowed.exit_reason != "void"


def test_target_on_the_last_bar_of_the_horizon_beats_the_time_stop() -> None:
    hit = (101.0, 103.6, 100.9, 101.25)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, QUIET, hit])

    assert outcome.exit_reason == "target" and outcome.bars_held == 3


def test_gap_through_the_target_fills_at_the_target() -> None:
    gapped = (104.5, 105.0, 104.0, 104.8)
    outcome = _label([SIGNAL_BAR, ENTRY_BAR, gapped, QUIET])

    assert outcome.exit_reason == "target"
    assert outcome.exit_price == 103.5
    assert outcome.r_multiple == pytest.approx(2.0)


def test_stop_buffer_is_in_atr_units() -> None:
    rules = ExitRules(rr=2.0, stop_buffer_atr=0.5, time_stop_bars=3)
    candles = [SIGNAL_BAR, ENTRY_BAR, QUIET, QUIET]
    outcome = label(frame(candles), make_signal(), rules, 2.0)

    assert outcome.stop == pytest.approx(98.0)
    assert outcome.target == pytest.approx(100.5 + 2 * 2.5)


def _rising(count: int) -> list[Candle]:
    return [
        (100.0 + 0.1 * i, 100.2 + 0.1 * i, 99.9 + 0.1 * i, 100.1 + 0.1 * i) for i in range(count)
    ]


def test_forward_returns_from_the_signal_close_in_atr_units() -> None:
    candles = _rising(14)
    outcome = label(frame(candles), make_signal(price=100.1), RULES, 0.5)

    assert outcome.fwd_5_atr == pytest.approx((candles[5][3] - 100.1) / 0.5)
    assert outcome.fwd_10_atr == pytest.approx((candles[10][3] - 100.1) / 0.5)
    assert outcome.fwd_20_atr is None


def test_forward_returns_are_signed_by_direction() -> None:
    candles = _rising(6)
    outcome = label(
        frame(candles), make_signal(direction=BEARISH, low=101, high=102, price=100.1), RULES, 1.0
    )

    assert outcome.fwd_5_atr == pytest.approx(-(candles[5][3] - 100.1))


def test_atr_defaults_to_the_signal_bar_prefix_only() -> None:
    ohlc = with_warmup([FLAT] * 4 + [(100.0, 140.0, 60.0, 100.0)] * 3)
    index = 19
    outcome = label(ohlc, make_signal(bar_index=index), RULES)

    assert outcome.atr == pytest.approx(atr(ohlc.iloc[: index + 1]))
    assert outcome.atr < atr(ohlc)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rr": 0.0},
        {"rr": math.inf},
        {"stop_buffer_atr": -0.1},
        {"stop_buffer_atr": math.nan},
        {"rr": 101.0},
        {"rr": True},
        {"rr": "2"},
        {"stop_buffer_atr": 51.0},
        {"time_stop_bars": 0},
        {"time_stop_bars": 5001},
        {"time_stop_bars": 5.0},
        {"time_stop_bars": True},
        {"spread": -1.0},
        {"spread": math.inf},
        {"spread": 2e9},
        {"min_risk_atr": -0.1},
        {"min_risk_atr": 51.0},
    ],
)
def test_exit_rules_reject_bad_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ExitRules(**kwargs)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan])
def test_label_rejects_a_bad_atr(bad: float) -> None:
    with pytest.raises(ValueError, match="ATR"):
        label(frame([SIGNAL_BAR, ENTRY_BAR]), make_signal(), RULES, bad)
