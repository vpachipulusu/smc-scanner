"""Signals, outcomes and strategies shared by the backtest tests."""

from typing import Any

import pandas as pd
from conftest import OB_SETUP, OB_TOUCH_LAST, Candle, with_warmup

from smc_scanner.backtest.outcome import ExitReason, Outcome
from smc_scanner.backtest.replay import Signal, ZoneKey
from smc_scanner.models import BULLISH, Direction, ScanRow
from smc_scanner.strategy import DEFAULT_STRATEGY_SLUG, Strategy
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES

SWING = 2
# The bullish OB in ``conftest.OB_SETUP``: block candle index, touched on the candle after it.
OB_FORMED = 16 + 3
OB_TOUCH_INDEX = 16 + len(OB_SETUP)


def strategy(**overrides: Any) -> Strategy:
    base = BUILTIN_STRATEGIES[DEFAULT_STRATEGY_SLUG].model_dump()
    return Strategy.model_validate({**base, "builtin": False, "slug": "test", **overrides})


# Bullish OBs touched on the latest candle only: the conftest OB fires once, at its touch.
OB_TOUCH = strategy(swing_length=SWING, zone_kinds=["OB"], statuses=["TOUCHING"])


def ob_frame(after: list[Candle] | None = None) -> pd.DataFrame:
    """The conftest OB touched at ``OB_TOUCH_INDEX``, then ``after``."""
    return with_warmup([*OB_SETUP, OB_TOUCH_LAST, *(after or [])])


def make_signal(
    *,
    direction: Direction = BULLISH,
    low: float = 99.0,
    high: float = 100.0,
    bar_index: int = 0,
    price: float = 100.5,
) -> Signal:
    side = "bull" if direction == BULLISH else "bear"
    row = ScanRow(
        instrument="SYN",
        status="TOUCHING",
        zone=f"{side} OB",
        zone_low=low,
        zone_high=high,
        price=price,
        dist_atr=0.0,
        bias="range",
        in_ote=False,
        trendline_ok=False,
        ob_fvg=False,
        score=0,
        zone_age=1,
        prior_touches=0,
        bar_time=f"bar-{bar_index}",
    )
    zone = ZoneKey("OB", direction, bar_index - 1, high, low)
    return Signal(bar_index=bar_index, bar_time=row.bar_time, row=row, zone=zone)


def make_outcome(
    r: float | None, *, reason: ExitReason | None = None, bars_held: int = 1, bar_index: int = 0
) -> Outcome:
    if reason is None:
        reason = "open" if r is None else ("target" if r > 0 else "stop")
    return Outcome(
        signal=make_signal(bar_index=bar_index),
        exit_reason=reason,
        r_multiple=r,
        bars_held=bars_held,
        entry=100.0,
        stop=99.0,
        target=102.0,
        exit_price=None,
        atr=1.0,
        fwd_5_atr=None,
        fwd_10_atr=None,
        fwd_20_atr=None,
    )
