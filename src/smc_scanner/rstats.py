"""R-multiple aggregates shared by the trade journal and the backtester.

R is profit divided by the initial risk. Every function takes the R values of closed trades
only and returns None for an empty list, never an error.
"""

import math
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean (``math.fsum``, so long lists keep their precision)."""
    return math.fsum(values) / len(values) if values else None


def hit_rate(rs: Sequence[float]) -> float | None:
    """Share of trades with R above zero (breakeven is not a win)."""
    return sum(r > 0 for r in rs) / len(rs) if rs else None


def expectancy(rs: Sequence[float]) -> float | None:
    """Expected R per trade: win rate x average win + loss rate x average loss.

    Breakeven trades add zero, so this equals the mean R; it keeps its own name because
    traders look for it."""
    return mean(rs)
