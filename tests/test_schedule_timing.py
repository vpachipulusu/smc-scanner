"""Schedule timing: UTC candle boundaries, grace, broker offset, missed-run collapse."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc_scanner.schedule.timing import (
    GRACE,
    SERVER_TZ_ENV,
    SERVER_ZONE,
    candle_close_after,
    is_due,
    missed_slots,
    next_run_after,
    server_zone_from_env,
)


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


@pytest.mark.parametrize(
    ("frequency", "now", "close"),
    [
        ("15m", utc(2026, 3, 1, 12, 7), utc(2026, 3, 1, 12, 15)),
        ("15m", utc(2026, 3, 1, 12, 45, 1), utc(2026, 3, 1, 13, 0)),
        ("1h", utc(2026, 3, 1, 12, 59, 59), utc(2026, 3, 1, 13, 0)),
        ("1h", utc(2026, 3, 1, 23, 30), utc(2026, 3, 2, 0, 0)),
        ("4h", utc(2026, 3, 1, 3, 59), utc(2026, 3, 1, 4, 0)),
        ("4h", utc(2026, 3, 1, 20, 0), utc(2026, 3, 2, 0, 0)),
        ("1d", utc(2026, 3, 1, 0, 0, 1), utc(2026, 3, 2, 0, 0)),
        ("1d", utc(2026, 12, 31, 23, 59), utc(2027, 1, 1, 0, 0)),
    ],
)
def test_next_candle_close_is_the_following_utc_boundary(
    frequency: str, now: datetime, close: datetime
) -> None:
    assert candle_close_after(now, frequency) == close


def test_a_moment_exactly_on_a_close_moves_to_the_next_one() -> None:
    assert candle_close_after(utc(2026, 3, 1, 12, 0), "1h") == utc(2026, 3, 1, 13, 0)


def test_next_run_adds_grace_after_the_close() -> None:
    assert next_run_after(utc(2026, 3, 1, 12, 7), "1h") == utc(2026, 3, 1, 13, 0) + GRACE


def test_inside_the_grace_window_the_run_is_still_this_close() -> None:
    now = utc(2026, 3, 1, 13, 0) + GRACE / 2

    assert next_run_after(now, "1h") == utc(2026, 3, 1, 13, 0) + GRACE


def test_just_after_the_grace_window_the_run_moves_to_the_next_close() -> None:
    now = utc(2026, 3, 1, 13, 0) + GRACE

    assert next_run_after(now, "1h") == utc(2026, 3, 1, 14, 0) + GRACE


ATHENS = ZoneInfo("Europe/Athens")  # UTC+2, UTC+3 from the last Sunday of March


def test_quarter_hour_and_hourly_grids_ignore_the_server_zone() -> None:
    now = utc(2026, 3, 1, 12, 7)

    assert candle_close_after(now, "15m", ATHENS) == utc(2026, 3, 1, 12, 15)
    assert candle_close_after(now, "1h", ATHENS) == utc(2026, 3, 1, 13, 0)


def test_4h_and_1d_follow_the_server_wall_clock() -> None:
    now = utc(2026, 3, 1, 12, 7)  # 14:07 in Athens

    assert candle_close_after(now, "4h", ATHENS) == utc(2026, 3, 1, 14, 0)  # 16:00 local
    assert candle_close_after(now, "1d", ATHENS) == utc(2026, 3, 1, 22, 0)  # 00:00 local


def test_daily_close_follows_the_zone_across_a_dst_change() -> None:
    before = utc(2026, 3, 28, 12, 0)  # still UTC+2
    first = candle_close_after(before, "1d", ATHENS)
    second = candle_close_after(first, "1d", ATHENS)

    assert first == utc(2026, 3, 28, 22, 0)  # Mar 29 00:00 at UTC+2
    assert second == utc(2026, 3, 29, 21, 0)  # Mar 30 00:00 at UTC+3
    assert second - first == timedelta(hours=23)  # the DST day is an hour short


def test_4h_close_after_the_spring_forward_uses_the_new_offset() -> None:
    now = utc(2026, 3, 28, 22, 30)  # 00:30 local on the DST day, 03:00 -> 04:00 at 01:00Z

    assert candle_close_after(now, "4h", ATHENS) == utc(2026, 3, 29, 1, 0)  # 04:00 at UTC+3
    assert candle_close_after(utc(2026, 3, 29, 1, 0), "4h", ATHENS) == utc(2026, 3, 29, 5, 0)


def test_daily_close_follows_the_zone_across_the_autumn_change() -> None:
    first = candle_close_after(utc(2026, 10, 24, 12, 0), "1d", ATHENS)  # Oct 25 00:00 at UTC+3
    second = candle_close_after(first, "1d", ATHENS)  # Oct 26 00:00 at UTC+2

    assert second - first == timedelta(hours=25)


def test_default_zone_is_utc_and_documented() -> None:
    assert UTC == SERVER_ZONE
    assert "UTC" in (candle_close_after.__doc__ or "")


def test_server_zone_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SERVER_TZ_ENV, raising=False)
    assert server_zone_from_env() is SERVER_ZONE
    monkeypatch.setenv(SERVER_TZ_ENV, "  ")
    assert server_zone_from_env() is SERVER_ZONE
    monkeypatch.setenv(SERVER_TZ_ENV, "Europe/Athens")
    assert server_zone_from_env() == ATHENS
    monkeypatch.setenv(SERVER_TZ_ENV, "Mars/Olympus")
    with pytest.raises(ValueError, match=SERVER_TZ_ENV):
        server_zone_from_env()


def test_unknown_frequency_is_rejected() -> None:
    with pytest.raises(ValueError, match="frequency"):
        candle_close_after(utc(2026, 3, 1), "5m")


def test_naive_moment_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        candle_close_after(datetime(2026, 3, 1, 12), "1h")


def test_is_due_when_next_run_is_now_or_past() -> None:
    now = utc(2026, 3, 1, 12, 0)

    assert is_due(now, now)
    assert is_due(now - timedelta(hours=3), now)
    assert not is_due(now + timedelta(seconds=1), now)
    assert not is_due(None, now)  # unscheduled: the service gives it a slot, no instant run


def test_missed_slots_counts_whole_periods_of_downtime() -> None:
    due = utc(2026, 3, 1, 12, 0, 5)

    assert missed_slots(due, due, "1h") == 0
    assert missed_slots(due, due + timedelta(hours=3, minutes=1), "1h") == 3


def test_missed_runs_after_downtime_collapse_into_one_run() -> None:
    stale_next_run = utc(2026, 3, 1, 12, 0, 5)
    now = stale_next_run + timedelta(hours=9)

    assert is_due(stale_next_run, now)
    upcoming = next_run_after(now, "1h")
    assert upcoming > now
    assert upcoming - now <= timedelta(hours=1) + GRACE  # one run now, then back on the grid
    assert not is_due(upcoming, now)
