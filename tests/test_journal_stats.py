"""Journal statistics: R-multiple for both sides, aggregates, cumulative series."""

from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from smc_scanner.journal.models import JournalEntryOut
from smc_scanner.journal.stats import (
    average_r,
    cumulative_r,
    expectancy,
    r_multiple,
    summarize,
    win_rate,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def make(
    n: int,
    *,
    side: Literal["long", "short"] = "long",
    stop: float | None = None,
    exit: float | None = None,
    closed_hours: int | None = None,
) -> JournalEntryOut:
    if stop is None:
        stop = 99.0 if side == "long" else 101.0
    closed = None if exit is None else T0 + timedelta(hours=closed_hours or n)
    return JournalEntryOut(
        id=n,
        created_at=T0,
        updated_at=T0,
        symbol="EURUSD",
        timeframe="1h",
        side=side,
        entry=100.0,
        stop=stop,
        exit=exit,
        opened_at=T0,
        closed_at=closed,
    )


@pytest.mark.parametrize(
    ("side", "stop", "exit", "expected"),
    [
        ("long", 99.0, 102.0, 2.0),
        ("long", 99.0, 99.0, -1.0),
        ("long", 99.0, 100.0, 0.0),
        ("long", 99.0, 98.0, -2.0),
        ("short", 101.0, 98.0, 2.0),
        ("short", 101.0, 101.0, -1.0),
        ("short", 101.0, 102.0, -2.0),
        ("short", 102.0, 97.0, 1.5),
    ],
)
def test_r_multiple(
    side: Literal["long", "short"], stop: float, exit: float, expected: float
) -> None:
    assert r_multiple(make(1, side=side, stop=stop, exit=exit)) == pytest.approx(expected)


def test_open_trade_has_no_r() -> None:
    assert r_multiple(make(1)) is None


def test_zero_trades_give_none_not_errors() -> None:
    assert win_rate([]) is None
    assert average_r([]) is None
    assert expectancy([]) is None
    assert cumulative_r([]) == []
    summary = summarize([])
    assert summary.closed_trades == 0 and summary.win_rate is None and summary.total_r == 0.0


def test_open_trades_are_excluded_everywhere() -> None:
    entries = [make(1, exit=102.0), make(2)]
    assert win_rate(entries) == 1.0
    assert len(cumulative_r(entries)) == 1
    assert summarize(entries).open_trades == 1


def test_aggregates() -> None:
    # R: +2, -1, 0, +1
    entries = [
        make(1, exit=102.0),
        make(2, exit=99.0),
        make(3, exit=100.0),
        make(4, exit=101.0),
    ]
    assert win_rate(entries) == pytest.approx(0.5)
    assert average_r(entries) == pytest.approx(0.5)
    assert expectancy(entries) == pytest.approx(0.5)
    summary = summarize(entries)
    assert (summary.wins, summary.losses, summary.breakeven) == (2, 1, 1)
    assert summary.avg_win_r == pytest.approx(1.5)
    assert summary.avg_loss_r == pytest.approx(-1.0)
    assert summary.total_r == pytest.approx(2.0)


def test_all_wins_have_no_average_loss() -> None:
    summary = summarize([make(1, exit=102.0)])
    assert summary.avg_loss_r is None and summary.expectancy == pytest.approx(2.0)


def test_all_losses_have_no_average_win() -> None:
    summary = summarize([make(1, exit=99.0)])
    assert summary.avg_win_r is None and summary.win_rate == 0.0


def test_cumulative_series_is_ordered_by_close_time() -> None:
    entries = [
        make(1, exit=102.0, closed_hours=5),  # +2 closes last
        make(2, exit=99.0, closed_hours=1),  # -1 closes first
        make(3, exit=101.0, closed_hours=3),  # +1
    ]
    points = cumulative_r(entries)
    assert [p.entry_id for p in points] == [2, 3, 1]
    assert [p.cumulative_r for p in points] == pytest.approx([-1.0, 0.0, 2.0])
