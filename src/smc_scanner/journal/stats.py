"""Pure journal statistics. R is the primary measure: profit divided by the initial risk.

An entry's risk is ``|entry - stop|``; a trade that exits at its stop is -1R. Open trades have no
R and are left out of every aggregate. With no closed trades the ratios are None, never an error.
Currency P&L is optional free input and deliberately plays no part here.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from smc_scanner.journal.models import JournalEntryOut


@dataclass(frozen=True)
class CumulativePoint:
    entry_id: int
    closed_at: datetime
    r: float
    cumulative_r: float


@dataclass(frozen=True)
class JournalStats:
    closed_trades: int
    open_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float | None
    average_r: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    expectancy: float | None
    total_r: float


def r_multiple(entry: JournalEntryOut) -> float | None:
    """Result in units of initial risk; None while the trade is open."""
    if entry.exit is None:
        return None
    risk = abs(entry.entry - entry.stop)
    move = entry.exit - entry.entry if entry.side == "long" else entry.entry - entry.exit
    return move / risk


def _closed_rs(entries: Iterable[JournalEntryOut]) -> list[float]:
    return [r for r in map(r_multiple, entries) if r is not None]


def _mean(values: list[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def win_rate(entries: Iterable[JournalEntryOut]) -> float | None:
    """Share of closed trades with R above zero (breakeven is not a win)."""
    rs = _closed_rs(entries)
    return sum(r > 0 for r in rs) / len(rs) if rs else None


def average_r(entries: Iterable[JournalEntryOut]) -> float | None:
    return _mean(_closed_rs(entries))


def expectancy(entries: Iterable[JournalEntryOut]) -> float | None:
    """Expected R per trade: win rate x average win + loss rate x average loss.

    Breakeven trades add zero, so this equals ``average_r``; it keeps its own name because
    traders look for it."""
    return average_r(entries)


def cumulative_r(entries: Iterable[JournalEntryOut]) -> list[CumulativePoint]:
    """Running R total over closed trades, in close order (id breaks ties)."""
    closed = [
        (e, e.closed_at, r)
        for e in entries
        if e.closed_at is not None and (r := r_multiple(e)) is not None
    ]
    closed.sort(key=lambda item: (item[1], item[0].id))
    points: list[CumulativePoint] = []
    total = 0.0
    for e, closed_at, r in closed:
        total += r
        points.append(CumulativePoint(e.id, closed_at, r, total))
    return points


def summarize(entries: Iterable[JournalEntryOut]) -> JournalStats:
    items = list(entries)
    rs = _closed_rs(items)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    return JournalStats(
        closed_trades=len(rs),
        open_trades=len(items) - len(rs),
        wins=len(wins),
        losses=len(losses),
        breakeven=len(rs) - len(wins) - len(losses),
        win_rate=len(wins) / len(rs) if rs else None,
        average_r=_mean(rs),
        avg_win_r=_mean(wins),
        avg_loss_r=_mean(losses),
        expectancy=expectancy(items),
        total_r=math.fsum(rs),
    )
