"""Budget guard wired into the analyst: reserve, call, record, release; plus the usage reader."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FLAT, FVG_SETUP, TOUCH_LAST, frame

from smc_scanner.ai import analyst
from smc_scanner.ai.analyst import HitInputs, analyse_hits, hit_inputs_from_ohlc
from smc_scanner.ai.budget import (
    PRICE_PER_MTOK,
    BudgetExceededError,
    BudgetGuard,
    BudgetLimits,
    DayUsage,
    Reservation,
    lookup_price,
)
from smc_scanner.ai.providers import MAX_TOKENS, AiError, AiReply, FakeProvider
from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, SqliteAnalysisStore, StoreError
from smc_scanner.models import ScanRow
from smc_scanner.scanner import ScanOptions, scan_instrument

TF = "1h"
OPTIONS = ScanOptions(swing_length=2)
OHLC = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST])
HOLD = '{"action": "HOLD", "confidence": 40, "reasons": ["weak"], "summary": "No edge."}'
T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
NOTHING = DayUsage(calls=0, cost=0.0)


def _row(symbol: str, score: int = 3) -> ScanRow:
    base = next(r for r in scan_instrument("TEST", OHLC, OPTIONS) if r.zone == "bull FVG")
    return replace(base, instrument=symbol, score=score)


def _source(row: ScanRow) -> HitInputs:
    return hit_inputs_from_ohlc(OHLC, row, OPTIONS)


def _record(
    symbol: str, created_at: str, cost: float | None, error: str | None = None
) -> AnalysisRecord:
    return AnalysisRecord(
        key=AnalysisKey(symbol, TF, "FVG", 1.0, 2.0, "2026-01-01T00:00:00"),
        created_at=created_at,
        zone={"label": "bull FVG"},
        context=None,
        verdict=None if error else {"action": "HOLD"},
        provider="claude",
        model="claude-sonnet-5-5",
        prompt_version="v1",
        tokens_in=1,
        tokens_out=1,
        cost_estimate=cost,
        error=error,
    )


def _guard(
    store: SqliteAnalysisStore, max_calls: int | None = None, max_cost: float | None = None
) -> BudgetGuard:
    return BudgetGuard(
        BudgetLimits(max_calls=max_calls, max_cost=max_cost),
        store.usage_for_day,
        clock=lambda: T0,
    )


def _run(
    rows: list[ScanRow],
    provider: FakeProvider,
    store: SqliteAnalysisStore,
    guard: BudgetGuard | None,
) -> list[analyst.AnalysisResult]:
    return analyse_hits(
        rows, _source, provider, store, timeframe=TF, min_score=0, budget=guard, now=lambda: T0
    )


# --- usage reader --------------------------------------------------------------------


def test_usage_for_day_counts_only_that_utc_day(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    store.save(_record("A", "2026-03-01T00:00:00+00:00", 0.5))
    store.save(_record("B", "2026-03-01T23:59:59.999999+00:00", 0.25))
    store.save(_record("C", "2026-02-28T23:59:59+00:00", 9.0))
    store.save(_record("D", "2026-03-02T00:00:00+00:00", 9.0))
    store.save(_record("E", "2026-03-01T10:00:00+00:00", None, error="AiError: boom"))

    assert store.usage_for_day(date(2026, 3, 1)) == DayUsage(calls=3, cost=0.75)


def test_usage_counts_every_attempt_of_a_retried_row(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    failed = _record("A", "2026-03-01T01:00:00+00:00", None, error="AiError: boom")
    store.save(failed)
    store.save(replace(failed, created_at="2026-03-01T02:00:00+00:00"))  # retried: attempts = 2

    assert store.usage_for_day(date(2026, 3, 1)).calls == 2


def test_unpriced_model_is_stored_at_the_dearest_rate(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    provider = FakeProvider([AiReply(HOLD, 1_000_000, 0, "mystery-model")])
    row = _row("AAA")

    _run([row], provider, store, None)

    stored = store.get(AnalysisKey("AAA", TF, "FVG", row.zone_low, row.zone_high, row.bar_time))
    assert stored is not None
    assert stored.cost_estimate == pytest.approx(max(p[0] for p in PRICE_PER_MTOK.values()))
    assert store.usage_for_day(date(2026, 3, 1)).cost > 0  # so a cost cap still sees it


def test_usage_for_empty_store_is_zero(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    assert store.usage_for_day(date(2026, 3, 1)) == NOTHING


def test_usage_works_on_a_read_only_store(tmp_path: Path) -> None:
    path = tmp_path / "smc.db"
    SqliteAnalysisStore(path).save(_record("A", "2026-03-01T01:00:00+00:00", 1.0))
    ro = SqliteAnalysisStore.open_read_only(path)
    assert ro.usage_for_day(date(2026, 3, 1)).calls == 1


# --- price table is shared -----------------------------------------------------------


def test_analyst_uses_the_budget_price_table() -> None:
    assert not hasattr(analyst, "PRICE_PER_MTOK")
    for model, (price_in, price_out) in PRICE_PER_MTOK.items():
        assert lookup_price(model) == (price_in, price_out)
        assert analyst.estimate_cost(model, 1_000_000, 1_000_000) == pytest.approx(
            price_in + price_out
        )


def test_lookup_price_matches_by_longest_prefix_and_unknown_is_none() -> None:
    assert lookup_price("gpt-x") is None
    assert lookup_price("claude-sonnet-5-5-20260101") == PRICE_PER_MTOK["claude-sonnet-5-5"]


# --- analyst -------------------------------------------------------------------------


def test_no_guard_changes_nothing(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    assert _run([_row("AAA")], FakeProvider([HOLD]), store, None)[0].status == "analysed"


def test_calls_cap_blocks_the_provider_call(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    store.save(_record("OLD", "2026-03-01T01:00:00+00:00", 0.01))
    provider = FakeProvider([HOLD])

    with pytest.raises(BudgetExceededError) as info:
        _run([_row("AAA")], provider, store, _guard(store, max_calls=1))

    assert info.value.cap == "calls"
    assert provider.calls == []


def test_second_row_is_refused_once_the_first_is_recorded(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    provider = FakeProvider([HOLD, HOLD])
    guard = _guard(store, max_calls=1)

    with pytest.raises(BudgetExceededError):
        _run([_row("AAA", 4), _row("BBB", 3)], provider, store, guard)

    first = _row("AAA")
    key = AnalysisKey("AAA", TF, "FVG", first.zone_low, first.zone_high, first.bar_time)
    assert len(provider.calls) == 1
    assert store.get(key) is not None  # the analysed row was recorded before the refusal
    assert guard.in_flight() == NOTHING  # and its reservation released


def test_reservation_is_released_when_the_provider_fails(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    guard = _guard(store, max_calls=5)

    class Boom(FakeProvider):
        def complete(self, system: str, user: str) -> AiReply:
            raise AiError("down")

    result = _run([_row("AAA")], Boom(), store, guard)

    assert result[0].status == "failed"
    assert guard.in_flight() == NOTHING


def test_estimate_uses_the_providers_max_output_tokens(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    seen: list[float] = []

    class Spy(BudgetGuard):
        def reserve(self, *, estimated_cost: float) -> Reservation:
            seen.append(estimated_cost)
            return super().reserve(estimated_cost=estimated_cost)

    guard = Spy(BudgetLimits(max_calls=5), store.usage_for_day, clock=lambda: T0)
    _run([_row("AAA")], FakeProvider([HOLD]), store, guard)

    # the model "fake" is unpriced, so it is charged the dearest rate with the full allowance
    assert seen[0] >= MAX_TOKENS * max(p[1] for p in PRICE_PER_MTOK.values()) / 1_000_000


def test_cost_cap_refuses_before_the_call(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    provider = FakeProvider([HOLD])
    with pytest.raises(BudgetExceededError) as info:
        _run([_row("AAA")], provider, store, _guard(store, max_cost=0.0001))
    assert info.value.cap == "cost"
    assert provider.calls == []


def test_unreadable_usage_fails_the_row_without_a_call(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")

    def broken(_: date) -> DayUsage:
        raise StoreError("locked")

    guard = BudgetGuard(BudgetLimits(max_calls=5), broken, clock=lambda: T0)
    provider = FakeProvider([HOLD])

    result = _run([_row("AAA")], provider, store, guard)

    assert result[0].status == "failed"
    assert provider.calls == []


def test_previous_days_do_not_count(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    store.save(_record("OLD", (T0 - timedelta(days=1)).isoformat(), 50.0))
    guard = _guard(store, max_calls=1, max_cost=1.0)
    assert _run([_row("AAA")], FakeProvider([HOLD]), store, guard)[0].status == "analysed"


# --- retries, billed failures and accumulated cost -----------------------------------


class _SpyGuard(BudgetGuard):
    def __init__(self, store: SqliteAnalysisStore) -> None:
        super().__init__(BudgetLimits(max_calls=50), store.usage_for_day, clock=lambda: T0)
        self.estimates: list[float] = []

    def reserve(self, *, estimated_cost: float) -> Reservation:
        self.estimates.append(estimated_cost)
        return super().reserve(estimated_cost=estimated_cost)


class _Retrying(FakeProvider):
    def __init__(self, replies: list[str], max_retries: int) -> None:
        super().__init__(replies)
        self.max_retries = max_retries


class _Failing(FakeProvider):
    def complete(self, system: str, user: str) -> AiReply:
        raise AiError("timeout")


def _stored(store: SqliteAnalysisStore, row: ScanRow) -> AnalysisRecord:
    key = AnalysisKey(row.instrument, TF, "FVG", row.zone_low, row.zone_high, row.bar_time)
    record = store.get(key)
    assert record is not None
    return record


def test_reservation_covers_every_provider_retry(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    plain, retrying = _SpyGuard(store), _SpyGuard(store)

    _run([_row("AAA")], _Retrying([HOLD], 0), store, plain)
    _run([_row("BBB")], _Retrying([HOLD], 2), store, retrying)

    assert retrying.estimates[0] == pytest.approx(plain.estimates[0] * 3)


def test_a_provider_without_a_retry_setting_reserves_one_request(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    plain, fake = _SpyGuard(store), _SpyGuard(store)

    _run([_row("AAA")], _Retrying([HOLD], 0), store, plain)
    _run([_row("BBB")], FakeProvider([HOLD]), store, fake)

    assert fake.estimates == plain.estimates


def test_a_failed_provider_call_is_stored_at_the_reserved_cost(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    guard = _SpyGuard(store)
    row = _row("AAA")

    assert _run([row], _Failing([]), store, guard)[0].status == "failed"

    assert _stored(store, row).cost_estimate == pytest.approx(guard.estimates[0])
    assert store.usage_for_day(date(2026, 3, 1)).cost == pytest.approx(guard.estimates[0])


def test_a_failure_before_the_provider_costs_nothing(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    row = _row("AAA")

    def broken(_: ScanRow) -> HitInputs:
        raise ValueError("bad data")

    result = analyse_hits(
        [row], broken, FakeProvider([HOLD]), store, timeframe=TF, min_score=0, now=lambda: T0
    )

    assert result[0].status == "failed"
    assert _stored(store, row).cost_estimate is None


def _costed(cost: float | None, error: str | None = None) -> AnalysisRecord:
    return replace(_record("A", "2026-03-01T01:00:00+00:00", cost, error=error), id=None)


def test_overwriting_a_row_accumulates_its_cost(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    store.save(_costed(1.0, "AiError: timeout"))
    store.save(_costed(0.5, "AiError: timeout"))
    store.save(_costed(0.25))  # a success replaces the failure but keeps its billed cost

    [saved] = store.list_recent(1)
    assert saved.cost_estimate == pytest.approx(1.75)


def test_forced_reanalysis_adds_to_the_stored_cost(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    store.save(_costed(1.0))
    store.save(_costed(0.5), overwrite=True)

    [saved] = store.list_recent(1)
    assert saved.cost_estimate == pytest.approx(1.5)


def test_cost_stays_unknown_when_neither_attempt_had_one(tmp_path: Path) -> None:
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    store.save(_costed(None, "AiError: x"))
    store.save(_costed(None, "AiError: x"))

    [saved] = store.list_recent(1)
    assert saved.cost_estimate is None
