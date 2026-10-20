"""Daily spend caps for LLM calls: standard library only, wired in by the callers.

``BudgetGuard`` compares today's usage (UTC day, supplied by an injected reader such as a store
query) plus in-flight reservations against the limits from ``AI_MAX_CALLS_PER_DAY`` and
``AI_MAX_COST_PER_DAY``. An unset or blank variable means unlimited; an invalid one is a
``BudgetConfigError``, never silent unlimited. Reservations make check-and-claim atomic so
concurrent callers cannot overshoot a cap. Messages name variables only, never their values.
"""

import math
import os
import re
import threading
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType, TracebackType
from typing import Final, Literal, Self

CALLS_ENV: Final = "AI_MAX_CALLS_PER_DAY"
COST_ENV: Final = "AI_MAX_COST_PER_DAY"
MAX_CONFIGURED: Final = 1_000_000_000  # sanity bound for either cap
MAX_DIGITS: Final = 10  # longer call counts are rejected before int() is attempted
COST_EPSILON: Final = 1e-9  # float noise when summing small costs against the cap
TOKENS_PER_PRICE_UNIT: Final = 1_000_000
DEFAULT_RESERVATION_TTL: Final = timedelta(minutes=10)

# Rough USD per million tokens (input, output), matched by model-name prefix. Estimates only:
# check the provider's price list before relying on them for billing. This is the one price
# table: ai/analyst.py prices stored analyses with ``lookup_price`` too.
PRICE_PER_MTOK: Final[Mapping[str, tuple[float, float]]] = MappingProxyType(
    {
        "claude-opus-5-5": (5.0, 25.0),
        "claude-sonnet-5-5": (3.0, 15.0),
        "claude-haiku-5-5": (1.0, 5.0),
    }
)
# Unknown-model policy: a cap must not be bypassed by a model name missing from the table, so an
# unpriced model is charged the dearest known input and output rate (over-estimates, never under).
FALLBACK_PRICE: Final = (
    max(price_in for price_in, _ in PRICE_PER_MTOK.values()),
    max(price_out for _, price_out in PRICE_PER_MTOK.values()),
)

_COUNT_PATTERN: Final = re.compile(r"[0-9]+")
_DECIMAL_PATTERN: Final = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")

Cap = Literal["calls", "cost"]


class BudgetConfigError(ValueError):
    """A spend-cap setting is invalid. Names the variable, never its value."""


class BudgetExceededError(Exception):
    """A daily cap is reached. ``retry_after_seconds`` is the time to UTC midnight (Retry-After)."""

    def __init__(self, cap: Cap, retry_after_seconds: int) -> None:
        self.cap: Cap = cap
        self.retry_after_seconds = retry_after_seconds
        super().__init__(cap, retry_after_seconds)  # keeps the error picklable and copyable

    def __str__(self) -> str:
        env = CALLS_ENV if self.cap == "calls" else COST_ENV
        return (
            f"daily AI {self.cap} cap reached ({env}); "
            f"retry after {self.retry_after_seconds} seconds"
        )


def _is_number(value: object) -> bool:
    """An int or float that is not a bool."""
    return type(value) in (int, float)


@dataclass(frozen=True)
class DayUsage:
    """Calls made and estimated USD spent during one UTC day. Invalid values raise ValueError,
    so a corrupt reader cannot widen the budget (NaN would make every comparison False)."""

    calls: int
    cost: float

    def __post_init__(self) -> None:
        if (
            type(self.calls) is not int
            or self.calls < 0
            or not _is_number(self.cost)
            or not (math.isfinite(self.cost) and self.cost >= 0)
        ):
            raise ValueError("usage must be a non-negative call count and a finite cost")


@dataclass(frozen=True)
class BudgetLimits:
    """Daily caps; None means unlimited. Zero is a valid cap that blocks everything."""

    max_calls: int | None = None
    max_cost: float | None = None

    def __post_init__(self) -> None:
        calls, cost = self.max_calls, self.max_cost
        if calls is not None and (type(calls) is not int or not 0 <= calls <= MAX_CONFIGURED):
            raise BudgetConfigError(f"{CALLS_ENV} must be a whole number of calls, 0 or more")
        if cost is not None and not (
            _is_number(cost) and math.isfinite(cost) and 0 <= cost <= MAX_CONFIGURED
        ):
            raise BudgetConfigError(f"{COST_ENV} must be a finite amount in USD, 0 or more")

    @property
    def unlimited(self) -> bool:
        return self.max_calls is None and self.max_cost is None


def _setting(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def limits_from_env(env: Mapping[str, str] | None = None) -> BudgetLimits:
    """Read the caps; unset or blank is unlimited, anything invalid raises BudgetConfigError."""
    source = os.environ if env is None else env
    calls_text = _setting(source, CALLS_ENV)
    cost_text = _setting(source, COST_ENV)
    if calls_text is not None and (
        len(calls_text) > MAX_DIGITS or not _COUNT_PATTERN.fullmatch(calls_text)
    ):
        raise BudgetConfigError(f"{CALLS_ENV} must be a whole number of calls, 0 or more")
    if cost_text is not None and not _DECIMAL_PATTERN.fullmatch(cost_text):
        raise BudgetConfigError(f"{COST_ENV} must be a finite amount in USD, 0 or more")
    return BudgetLimits(
        max_calls=None if calls_text is None else int(calls_text),
        max_cost=None if cost_text is None else float(cost_text),
    )


def lookup_price(model: str) -> tuple[float, float] | None:
    """(input, output) USD per million tokens by longest model-name prefix, or None if unpriced."""
    matches = [name for name in PRICE_PER_MTOK if model.startswith(name)]
    if not matches:
        return None
    return PRICE_PER_MTOK[max(matches, key=len)]


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """USD estimate from token counts. An unpriced model gets the dearest known rate."""
    if type(tokens_in) is not int or type(tokens_out) is not int or tokens_in < 0 or tokens_out < 0:
        raise ValueError("tokens must be non-negative integers")
    price_in, price_out = lookup_price(model) or FALLBACK_PRICE
    return (tokens_in * price_in + tokens_out * price_out) / TOKENS_PER_PRICE_UNIT


class Reservation:
    """A claim on one call (and its estimated cost) until released; use as a context manager."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release
        self._done = False
        self._lock = threading.Lock()

    def release(self) -> None:
        """Give the claim back once the call is recorded or abandoned; safe to repeat."""
        with self._lock:
            if self._done:
                return
            self._done = True
        self._release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


@dataclass(frozen=True)
class _Held:
    day: date
    cost: float
    expires: float  # monotonic seconds


def _release_nothing() -> None:
    """Release for a reservation that was never recorded (no cap configured)."""


class BudgetGuard:
    """Enforces the daily caps against stored usage plus in-flight reservations.

    ``read_usage(day)`` returns the calls and cost already recorded for that UTC day (the
    guard's current day, so the reader and guard never disagree about it). It runs under the
    guard's lock so check-and-reserve is atomic: it must be a short, in-process query (such as
    one SQLite read) that never calls back into the guard, since the lock is not reentrant.
    Reader errors and invalid usage propagate, so the guard fails closed.

    Record the call in the store first, then release the reservation: the brief double count
    can only refuse early, while the reverse order leaves a window where the call is counted
    nowhere. Prefer ``with guard.reserve(...)``; a leaked reservation is dropped after
    ``reservation_ttl`` (monotonic time). State is per process: several workers each see only
    their own reservations, so the cap can be overshot by up to the number of workers times
    their concurrency. Actual cost above the estimate is only seen once recorded. ``check()``
    is advisory (a later call can still be refused); ``reserve()`` is the atomic gate.

    A reservation stops counting after its TTL, or once its UTC day is past (the reader's
    totals restart at midnight and the call is charged to the day the store records it on). If
    the clock steps backwards, reservations from a later day are kept. When a calls cap is hit
    only because of in-flight reservations, ``retry_after_seconds`` is still the time to
    midnight, an upper bound on the wait. With no cap configured nothing is held or read.
    """

    def __init__(
        self,
        limits: BudgetLimits,
        read_usage: Callable[[date], DayUsage],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time_module.monotonic,
        reservation_ttl: timedelta = DEFAULT_RESERVATION_TTL,
    ) -> None:
        if reservation_ttl <= timedelta(0):
            raise ValueError("reservation_ttl must be positive")
        self._limits = limits
        self._read_usage = read_usage
        self._clock = clock
        self._monotonic = monotonic
        self._ttl = reservation_ttl.total_seconds()
        self._lock = threading.Lock()
        self._held: dict[int, _Held] = {}
        self._next_id = 0

    def check(self) -> None:
        """Raise BudgetExceededError if a call made now would not fit under a cap."""
        with self._lock:
            self._enforce(estimated_cost=0.0)

    def reserve(self, *, estimated_cost: float) -> Reservation:
        """Atomically check the caps and claim one call at ``estimated_cost`` USD.

        The estimate is required: a zero default would let concurrent callers overshoot the
        cost cap. Use ``estimate_cost`` with the request's maximum output tokens.
        """
        if (
            not _is_number(estimated_cost)
            or not math.isfinite(estimated_cost)
            or estimated_cost < 0
        ):
            raise ValueError("estimated_cost must be a finite amount, 0 or more")
        with self._lock:
            today = self._enforce(estimated_cost)
            if self._limits.unlimited:
                return Reservation(_release_nothing)
            ident = self._next_id
            self._next_id += 1
            self._held[ident] = _Held(today, estimated_cost, self._monotonic() + self._ttl)
        return Reservation(lambda: self._drop(ident))

    def in_flight(self) -> DayUsage:
        """Live reservations for the current UTC day or later."""
        with self._lock:
            today = self._now().date()
            self._expire(today)
            return self._held_usage()

    def _drop(self, ident: int) -> None:
        with self._lock:
            self._held.pop(ident, None)

    def _now(self) -> datetime:
        moment = self._clock()
        if moment.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return moment.astimezone(UTC)

    def _expire(self, today: date) -> None:
        """Drop reservations from past days and those past their TTL (caller holds the lock)."""
        now = self._monotonic()
        self._held = {
            ident: held
            for ident, held in self._held.items()
            if held.day >= today and held.expires > now
        }

    def _held_usage(self) -> DayUsage:
        return DayUsage(
            calls=len(self._held), cost=math.fsum(held.cost for held in self._held.values())
        )

    def _enforce(self, estimated_cost: float) -> date:
        """Raise if over a cap (caller holds the lock); return the UTC day checked."""
        now = self._now()
        today = now.date()
        self._expire(today)
        if self._limits.unlimited:
            return today
        stored = self._read_usage(today)
        held = self._held_usage()
        calls = stored.calls + held.calls
        spent = stored.cost + held.cost
        max_calls, max_cost = self._limits.max_calls, self._limits.max_cost
        if max_calls is not None and calls + 1 > max_calls:
            raise BudgetExceededError("calls", _seconds_to_midnight(now))
        if max_cost is not None and (
            spent >= max_cost - COST_EPSILON or spent + estimated_cost > max_cost + COST_EPSILON
        ):
            raise BudgetExceededError("cost", _seconds_to_midnight(now))
        return today


def _seconds_to_midnight(now: datetime) -> int:
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
    return max(1, math.ceil((midnight - now).total_seconds()))
