"""The in-process sliding-window limiter."""

import threading

import pytest

from smc_scanner.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_reports_retry_after() -> None:
    clock = Clock()
    limiter = RateLimiter(limit=2, window_seconds=60.0, clock=clock)

    assert limiter.take() is None
    assert limiter.take() is None
    clock.now += 10
    assert limiter.take() == 50


def test_window_slides_so_old_hits_expire() -> None:
    clock = Clock()
    limiter = RateLimiter(limit=1, window_seconds=60.0, clock=clock)
    assert limiter.take() is None
    clock.now += 60
    assert limiter.take() is None


def test_retry_after_is_at_least_one_second() -> None:
    clock = Clock()
    limiter = RateLimiter(limit=1, window_seconds=60.0, clock=clock)
    limiter.take()
    clock.now += 59.9
    assert limiter.take() == 1


def test_rejected_hits_are_not_counted() -> None:
    clock = Clock()
    limiter = RateLimiter(limit=1, window_seconds=10.0, clock=clock)
    limiter.take()
    for _ in range(5):
        clock.now += 1
        assert limiter.take() is not None
    clock.now += 5  # 10s after the one accepted hit
    assert limiter.take() is None


def test_reset_clears_the_window() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60.0, clock=Clock())
    limiter.take()
    limiter.reset()
    assert limiter.take() is None


@pytest.mark.parametrize(("limit", "window"), [(0, 1.0), (-1, 1.0), (1, 0.0), (1, float("nan"))])
def test_invalid_settings_are_rejected(limit: int, window: float) -> None:
    with pytest.raises(ValueError):
        RateLimiter(limit=limit, window_seconds=window)


def test_concurrent_callers_never_exceed_the_limit() -> None:
    limiter = RateLimiter(limit=5, window_seconds=60.0, clock=Clock())
    accepted: list[int] = []

    def worker() -> None:
        if limiter.take() is None:
            accepted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(accepted) == 5
