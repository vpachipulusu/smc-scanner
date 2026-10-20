"""Spend caps: env parsing, the guard's checks, UTC rollover and concurrent reservation."""

import pickle
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from smc_scanner.ai.budget import (
    CALLS_ENV,
    COST_ENV,
    BudgetConfigError,
    BudgetExceededError,
    BudgetGuard,
    BudgetLimits,
    DayUsage,
    estimate_cost,
    limits_from_env,
)

NOON = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
NO_USAGE = DayUsage(calls=0, cost=0.0)


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Usage:
    """A mutable usage reader standing in for the store query; records the days it is asked for."""

    def __init__(self, calls: int = 0, cost: float = 0.0, *, delay: float = 0.0) -> None:
        self.value = DayUsage(calls=calls, cost=cost)
        self.days: list[date] = []
        self.delay = delay

    @property
    def reads(self) -> int:
        return len(self.days)

    def __call__(self, day: date) -> DayUsage:
        self.days.append(day)
        if self.delay:
            time.sleep(self.delay)  # widens the check-then-claim window a missing lock would leave
        return self.value


class Mono:
    """A fake monotonic clock. ``delay`` sleeps on every read: the guard reads it between its
    cap check and recording a reservation, so this widens the window a missing lock would leave."""

    def __init__(self, delay: float = 0.0) -> None:
        self.now = 1000.0
        self.delay = delay

    def __call__(self) -> float:
        if self.delay:
            time.sleep(self.delay)
        return self.now


def make_guard(
    usage: Usage,
    *,
    max_calls: int | None = None,
    max_cost: float | None = None,
    clock: Clock | None = None,
    monotonic: Mono | None = None,
    ttl: timedelta = timedelta(minutes=10),
) -> BudgetGuard:
    return BudgetGuard(
        BudgetLimits(max_calls=max_calls, max_cost=max_cost),
        usage,
        clock=clock or Clock(),
        monotonic=monotonic or Mono(),
        reservation_ttl=ttl,
    )


def run_workers(count: int, work: Callable[[], None]) -> list[BaseException]:
    """Run ``work`` on ``count`` threads released together; return any exceptions they raised."""
    barrier = threading.Barrier(count, timeout=5)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def target() -> None:
        try:
            barrier.wait()
            work()
        except BaseException as exc:  # surfaced to the test, not swallowed
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=target) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads), "worker threads did not finish"
    return errors


# --- environment -------------------------------------------------------------------------


@pytest.mark.parametrize("env", [{}, {CALLS_ENV: "", COST_ENV: "   "}])
def test_unset_or_blank_means_unlimited(env: dict[str, str]) -> None:
    assert limits_from_env(env) == BudgetLimits(max_calls=None, max_cost=None)


def test_limits_are_parsed_and_stripped() -> None:
    env = {CALLS_ENV: " 25 ", COST_ENV: "1.5"}

    assert limits_from_env(env) == BudgetLimits(max_calls=25, max_cost=1.5)


@pytest.mark.parametrize(("env_name", "cap"), [(CALLS_ENV, "calls"), (COST_ENV, "cost")])
def test_zero_is_a_valid_cap_that_blocks_everything(env_name: str, cap: str) -> None:
    limits = limits_from_env({env_name: "0"})
    guard = make_guard(Usage(), max_calls=limits.max_calls, max_cost=limits.max_cost)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.cap == cap


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (CALLS_ENV, "-1"),
        (CALLS_ENV, "abc"),
        (CALLS_ENV, "1.5"),
        (CALLS_ENV, "1e3"),
        (CALLS_ENV, "99999999999999999999999999"),
        (CALLS_ENV, "9" * 5000),
        (CALLS_ENV, "1_000"),
        (COST_ENV, "1_0.5"),
        (COST_ENV, "-0.01"),
        (COST_ENV, "nan"),
        (COST_ENV, "inf"),
        (COST_ENV, "$5"),
    ],
)
def test_invalid_config_is_a_clear_error_never_unlimited(name: str, value: str) -> None:
    with pytest.raises(BudgetConfigError) as caught:
        limits_from_env({name: value})

    assert name in str(caught.value)
    assert f"{value!r}" not in str(caught.value)


def test_limits_from_env_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CALLS_ENV, "7")
    monkeypatch.delenv(COST_ENV, raising=False)

    assert limits_from_env() == BudgetLimits(max_calls=7, max_cost=None)


def test_direct_limits_reject_invalid_values() -> None:
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_calls=-1)
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_cost=-0.5)
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_cost=float("nan"))
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_calls=True)
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_calls=2.5)  # type: ignore[arg-type]
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_cost=True)
    with pytest.raises(BudgetConfigError):
        BudgetLimits(max_cost="1")  # type: ignore[arg-type]


# --- price table -------------------------------------------------------------------------


def test_cost_estimate_uses_the_model_prefix() -> None:
    cost = estimate_cost("claude-sonnet-5-5-20261001", 1_000_000, 1_000_000)

    assert cost == pytest.approx(18.0)


def test_unknown_model_is_priced_at_the_dearest_known_rate() -> None:
    unknown = estimate_cost("mystery-model", 1_000_000, 1_000_000)
    dearest = estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000)

    assert unknown == dearest


def test_the_longest_matching_model_prefix_wins() -> None:
    assert estimate_cost("claude-haiku-5-5-xl", 1_000_000, 0) == pytest.approx(1.0)


@pytest.mark.parametrize("tokens", [(-1, 0), (0, -1), (True, 0), (0, False), (1.5, 0), (0, "7")])
def test_invalid_tokens_are_rejected(tokens: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="tokens"):
        estimate_cost("claude-opus-5-5", *tokens)


# --- guard -------------------------------------------------------------------------------


def test_unlimited_never_raises_and_skips_the_reader() -> None:
    usage = Usage(calls=10**9, cost=10**9)
    guard = make_guard(usage)

    guard.check()
    with guard.reserve(estimated_cost=1e9):
        pass

    assert usage.reads == 0


def test_calls_cap_blocks_when_reached() -> None:
    guard = make_guard(Usage(calls=5), max_calls=5)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.cap == "calls"
    assert CALLS_ENV in str(caught.value)


def test_calls_cap_boundary_one_below_is_allowed() -> None:
    make_guard(Usage(calls=4), max_calls=5).check()


def test_cost_cap_blocks_when_reached() -> None:
    guard = make_guard(Usage(cost=2.0), max_cost=2.0)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.cap == "cost"
    assert COST_ENV in str(caught.value)


def test_cost_cap_just_below_is_allowed() -> None:
    make_guard(Usage(cost=1.99), max_cost=2.0).check()


def test_estimated_cost_may_land_exactly_on_the_cap_but_not_past_it() -> None:
    guard = make_guard(Usage(cost=1.5), max_cost=2.0)

    with guard.reserve(estimated_cost=0.5):
        pass
    with pytest.raises(BudgetExceededError) as caught, guard.reserve(estimated_cost=0.51):
        pass

    assert caught.value.cap == "cost"


def test_calls_cap_is_reported_before_cost_when_both_are_hit() -> None:
    guard = make_guard(Usage(calls=1, cost=9.0), max_calls=1, max_cost=1.0)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.cap == "calls"


def test_retry_after_is_seconds_until_utc_midnight() -> None:
    clock = Clock(datetime(2026, 10, 20, 23, 0, 0, tzinfo=UTC))
    guard = make_guard(Usage(calls=1), max_calls=1, clock=clock)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.retry_after_seconds == 3600


def test_retry_after_rounds_up_and_is_at_least_one_second() -> None:
    clock = Clock(datetime(2026, 10, 20, 23, 59, 59, 500_000, tzinfo=UTC))
    guard = make_guard(Usage(calls=1), max_calls=1, clock=clock)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.retry_after_seconds == 1


def test_non_utc_clock_is_converted() -> None:
    plus_two = timezone(timedelta(hours=2))
    clock = Clock(datetime(2026, 10, 21, 1, 0, 0, tzinfo=plus_two))  # 23:00 UTC on the 20th
    guard = make_guard(Usage(calls=1), max_calls=1, clock=clock)

    with pytest.raises(BudgetExceededError) as caught:
        guard.check()

    assert caught.value.retry_after_seconds == 3600


def test_naive_clock_is_rejected() -> None:
    guard = make_guard(Usage(), max_calls=1, clock=Clock(datetime(2026, 10, 20, 12, 0, 0)))

    with pytest.raises(ValueError, match="timezone-aware"):
        guard.check()


def test_reader_receives_the_guards_utc_day() -> None:
    plus_two = timezone(timedelta(hours=2))
    clock = Clock(datetime(2026, 10, 21, 1, 0, 0, tzinfo=plus_two))  # 23:00 UTC on the 20th
    usage = Usage()
    guard = make_guard(usage, max_calls=5, clock=clock)

    guard.check()
    clock.now = datetime(2026, 10, 21, 0, 30, 0, tzinfo=UTC)
    guard.check()

    assert usage.days == [date(2026, 10, 20), date(2026, 10, 21)]


def test_midnight_rollover_reopens_the_budget() -> None:
    clock = Clock(datetime(2026, 10, 20, 23, 59, 59, tzinfo=UTC))
    usage = Usage(calls=3)
    guard = make_guard(usage, max_calls=3, clock=clock)
    with pytest.raises(BudgetExceededError):
        guard.check()

    clock.now = datetime(2026, 10, 21, 0, 0, 0, tzinfo=UTC)
    usage.value = NO_USAGE  # the store query now covers the new UTC day

    guard.check()


def test_in_flight_reservations_count_until_released() -> None:
    guard = make_guard(Usage(calls=1), max_calls=2)

    with guard.reserve(estimated_cost=0.0), pytest.raises(BudgetExceededError):
        guard.check()
    guard.check()


def test_release_is_idempotent() -> None:
    guard = make_guard(Usage(calls=1), max_calls=3)
    reservation = guard.reserve(estimated_cost=0.0)

    reservation.release()
    reservation.release()

    assert guard.in_flight() == NO_USAGE


def test_reservation_released_when_the_call_fails() -> None:
    guard = make_guard(Usage(), max_calls=1)

    with pytest.raises(RuntimeError), guard.reserve(estimated_cost=0.0):
        raise RuntimeError("provider down")

    assert guard.in_flight() == NO_USAGE


def test_reservation_from_yesterday_does_not_count_today() -> None:
    clock = Clock(datetime(2026, 10, 20, 23, 59, 59, tzinfo=UTC))
    guard = make_guard(Usage(), max_calls=1, clock=clock)
    reservation = guard.reserve(estimated_cost=0.0)

    clock.now = datetime(2026, 10, 21, 0, 0, 1, tzinfo=UTC)

    guard.check()
    assert guard.in_flight() == NO_USAGE
    reservation.release()


def test_backwards_clock_step_keeps_reservations_from_a_later_day() -> None:
    clock = Clock(datetime(2026, 10, 21, 0, 0, 5, tzinfo=UTC))
    guard = make_guard(Usage(), max_calls=1, clock=clock)
    guard.reserve(estimated_cost=0.0)

    clock.now = datetime(2026, 10, 20, 23, 59, 0, tzinfo=UTC)  # NTP stepped the clock back

    with pytest.raises(BudgetExceededError):
        guard.check()
    assert guard.in_flight().calls == 1


def test_leaked_reservation_expires_after_the_ttl() -> None:
    mono = Mono()
    guard = make_guard(Usage(), max_calls=1, monotonic=mono, ttl=timedelta(minutes=10))
    guard.reserve(estimated_cost=0.0)  # never released

    mono.now += 599
    with pytest.raises(BudgetExceededError):
        guard.check()
    mono.now += 2

    guard.check()
    assert guard.in_flight() == NO_USAGE


def test_default_ttl_is_ten_minutes() -> None:
    mono = Mono()
    guard = BudgetGuard(BudgetLimits(max_calls=1), Usage(), clock=Clock(), monotonic=mono)
    guard.reserve(estimated_cost=0.0)

    mono.now += 599
    with pytest.raises(BudgetExceededError):
        guard.check()
    mono.now += 2

    guard.check()


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_ttl_is_rejected(ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="reservation_ttl"):
        make_guard(Usage(), max_calls=1, ttl=ttl)


def test_negative_estimated_cost_is_rejected() -> None:
    guard = make_guard(Usage(), max_cost=1.0)

    with pytest.raises(ValueError, match="estimated_cost"):
        guard.reserve(estimated_cost=-1.0)


def test_reader_errors_propagate_so_the_guard_fails_closed() -> None:
    def broken(day: date) -> DayUsage:
        raise OSError("db unavailable")

    guard = BudgetGuard(BudgetLimits(max_calls=1), broken, clock=Clock())

    with pytest.raises(OSError, match="db unavailable"):
        guard.check()


def test_concurrent_reservations_cannot_overshoot_the_cap() -> None:
    cap = 5
    workers = 20
    guard = make_guard(Usage(delay=0.001), max_calls=cap, monotonic=Mono(delay=0.001))
    outcomes: list[bool] = []

    def work() -> None:
        try:
            guard.reserve(estimated_cost=0.0)
        except BudgetExceededError:
            outcomes.append(False)
        else:
            outcomes.append(True)

    errors = run_workers(workers, work)

    assert errors == []
    assert outcomes.count(True) == cap
    assert outcomes.count(False) == workers - cap
    assert guard.in_flight().calls == cap


def test_concurrent_reservations_cannot_overshoot_the_cost_cap() -> None:
    guard = make_guard(Usage(delay=0.001), max_cost=1.0, monotonic=Mono(delay=0.001))
    outcomes: list[bool] = []

    def work() -> None:
        try:
            guard.reserve(estimated_cost=0.25)
        except BudgetExceededError:
            outcomes.append(False)
        else:
            outcomes.append(True)

    errors = run_workers(20, work)

    assert errors == []
    assert outcomes.count(True) == 4
    assert guard.in_flight().cost == pytest.approx(1.0)


def test_reservation_cost_counts_toward_the_cost_cap() -> None:
    guard = make_guard(Usage(cost=0.5), max_cost=1.0)

    with guard.reserve(estimated_cost=0.4), pytest.raises(BudgetExceededError) as caught:
        guard.reserve(estimated_cost=0.2)

    assert caught.value.cap == "cost"


def test_reserve_at_the_calls_boundary() -> None:
    guard = make_guard(Usage(calls=3), max_calls=5)

    first = guard.reserve(estimated_cost=0.0)
    second = guard.reserve(estimated_cost=0.0)  # 3 stored + 2 held = 5: the last slot
    with pytest.raises(BudgetExceededError) as caught:
        guard.reserve(estimated_cost=0.0)

    assert caught.value.cap == "calls"
    first.release()
    second.release()
    assert guard.in_flight() == NO_USAGE


def test_only_the_configured_cap_applies() -> None:
    make_guard(Usage(calls=10**6), max_cost=1.0).check()
    make_guard(Usage(cost=10**6), max_calls=5).check()


def test_unlimited_mode_holds_nothing() -> None:
    guard = make_guard(Usage())

    reservations = [guard.reserve(estimated_cost=1.0) for _ in range(100)]
    for reservation in reservations:
        reservation.release()

    assert guard.in_flight() == NO_USAGE
    assert guard._held == {}  # no state grows when nothing is capped


@pytest.mark.parametrize(
    ("calls", "cost"),
    [
        (-1, 0.0),
        (0, -0.1),
        (0, float("nan")),
        (0, float("inf")),
        (True, 0.0),
        (1.5, 0.0),
        (0, "x"),
        (0, True),
    ],
)
def test_invalid_usage_values_are_rejected(calls: int, cost: float) -> None:
    with pytest.raises(ValueError, match="usage"):
        DayUsage(calls=calls, cost=cost)


def test_budget_exceeded_error_survives_pickling() -> None:
    original = BudgetExceededError("cost", 42)

    copy = pickle.loads(pickle.dumps(original))  # noqa: S301

    assert (copy.cap, copy.retry_after_seconds, str(copy)) == (
        "cost",
        42,
        str(original),
    )
