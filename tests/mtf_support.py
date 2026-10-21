"""Frames and a fake multi-timeframe loader shared by the multi-timeframe tests."""

import pandas as pd
from conftest import FLAT, FVG_SETUP, TOUCH_LAST, frame

from smc_scanner.loaders.base import LoaderError

SWING = 2
# 1h frame whose latest candle touches a bullish FVG: one "bull FVG" hit.
HIT_FRAME = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST])


def zigzag(drift: int, cycles: int = 8) -> pd.DataFrame:
    """Runs of 6 bars one way, then 3 back, repeated: drift>0 gives HH+HL, <0 LH+LL, 0 a range."""
    step_up, step_down = (6, 6) if drift == 0 else (6, 3)
    sign = -1 if drift < 0 else 1
    closes: list[float] = []
    level = 200.0
    for _ in range(cycles):
        for _ in range(step_up):
            level += sign
            closes.append(level)
        for _ in range(step_down):
            level -= sign
            closes.append(level)
    candles = []
    previous = 200.0
    for close in closes:
        candles.append((previous, max(previous, close) + 0.3, min(previous, close) - 0.3, close))
        previous = close
    return frame(candles)


class TfLoader:
    """Serves frames by (symbol, timeframe) and records every load."""

    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        self.calls.append((symbol, timeframe))
        try:
            return self.frames[(symbol, timeframe)]
        except KeyError:
            raise LoaderError(f"no {timeframe} data for {symbol}") from None

    def close(self) -> None:
        self.closed = True
