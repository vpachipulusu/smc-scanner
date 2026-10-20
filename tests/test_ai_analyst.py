"""Analyst service: gating, cap, dedupe, failure isolation, persistence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from conftest import FLAT, FVG_SETUP, TOUCH_LAST, frame

from smc_scanner.ai.analyst import (
    FAILURE_COOLDOWN,
    MAX_ATTEMPTS,
    AnalysisResult,
    HitInputs,
    analyse_hits,
    estimate_cost,
    hit_inputs_from_ohlc,
)
from smc_scanner.ai.prompt import PROMPT_VERSION
from smc_scanner.ai.providers import AiError, AiReply, FakeProvider
from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, SqliteAnalysisStore, StoreError
from smc_scanner.models import ScanRow
from smc_scanner.scanner import ScanOptions, scan_instrument

TF = "1h"
OPTIONS = ScanOptions(swing_length=2)
OHLC = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST])
HOLD = '{"action": "HOLD", "confidence": 40, "reasons": ["weak"], "summary": "No edge."}'
T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _base_row() -> ScanRow:
    return next(r for r in scan_instrument("TEST", OHLC, OPTIONS) if r.zone == "bull FVG")


def _row(symbol: str = "AAA", score: int = 3, dist: float = 0.0, **changes: object) -> ScanRow:
    return replace(_base_row(), instrument=symbol, score=score, dist_atr=dist, **changes)  # type: ignore[arg-type]


def _source(row: ScanRow) -> HitInputs:
    return hit_inputs_from_ohlc(OHLC, row, OPTIONS)


def _store(tmp_path: Path) -> SqliteAnalysisStore:
    return SqliteAnalysisStore(tmp_path / "smc.db")


def _run(
    rows: list[ScanRow],
    provider: FakeProvider,
    store: SqliteAnalysisStore,
    min_score: int = 2,
    max_rows: int = 5,
    force: bool = False,
    at: datetime = T0,
) -> list[AnalysisResult]:
    return analyse_hits(
        rows,
        _source,
        provider,
        store,
        timeframe=TF,
        min_score=min_score,
        max_rows=max_rows,
        force=force,
        now=lambda: at,
    )


def _statuses(results: list[AnalysisResult]) -> list[str]:
    return [r.status for r in results]


def _by_symbol(results: list[AnalysisResult]) -> dict[str, str]:
    return {r.row.instrument: r.status for r in results}


def _key_of(row: ScanRow) -> AnalysisKey:
    return AnalysisKey(row.instrument, TF, "FVG", row.zone_low, row.zone_high, row.bar_time)


class _Named:
    """Minimal provider base: the Protocol needs a name and an optional model."""

    name = "stub"
    model = None


class _BrokenStore(SqliteAnalysisStore):
    def __init__(self, path: Path, fail_save: bool = False, fail_get: bool = False) -> None:
        super().__init__(path)
        self.fail_save = fail_save
        self.fail_get = fail_get

    def save(self, record: AnalysisRecord, *, overwrite: bool = False) -> None:
        if self.fail_save:
            raise StoreError("disk full")
        super().save(record, overwrite=overwrite)

    def get(self, key: AnalysisKey) -> AnalysisRecord | None:
        if self.fail_get:
            raise StoreError("locked")
        return super().get(key)


def test_analyses_a_row_and_persists_verdict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([AiReply(HOLD, 1000, 200, "claude-sonnet-5-5")])
    row = _row()

    [result] = _run([row], provider, store)

    assert result.status == "analysed"
    assert result.error is None
    assert result.verdict is not None and result.verdict.action == "HOLD"
    saved = store.get(_key_of(row))
    assert saved is not None
    assert saved.verdict is not None and saved.verdict["action"] == "HOLD"
    assert saved.prompt_version == PROMPT_VERSION
    assert saved.provider == "fake"
    assert saved.model == "claude-sonnet-5-5"
    assert (saved.tokens_in, saved.tokens_out) == (1000, 200)
    assert saved.cost_estimate is not None and saved.cost_estimate > 0
    assert saved.context is not None and saved.context["symbol"] == "AAA"
    assert saved.error is None
    assert saved.created_at == T0.isoformat()


def test_provider_receives_system_prompt_and_context_message(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD])

    _run([_row()], provider, _store(tmp_path))

    [(system, user)] = provider.calls
    assert "Smart Money Concepts" in system
    assert user.startswith("Scanner data for this hit:")


def test_created_at_is_converted_to_utc(tmp_path: Path) -> None:
    store = _store(tmp_path)
    local = datetime(2026, 3, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))

    _run([_row()], FakeProvider([HOLD]), store, at=local)

    [saved] = store.list_recent(1)
    assert saved.created_at == "2026-03-01T12:00:00+00:00"


def test_naive_clock_is_rejected_before_any_work(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD])

    with pytest.raises(ValueError, match="timezone-aware"):
        _run([_row()], provider, _store(tmp_path), at=datetime(2026, 3, 1, 12, 0))

    assert provider.calls == []


def test_low_score_rows_are_skipped_without_a_call(tmp_path: Path) -> None:
    provider = FakeProvider([])

    results = _run([_row(score=1), _row("BBB", score=0)], provider, _store(tmp_path))

    assert _statuses(results) == ["skipped_low_score", "skipped_low_score"]
    assert provider.calls == []


def test_min_score_is_configurable(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD])

    [result] = _run([_row(score=1)], provider, _store(tmp_path), min_score=1)

    assert result.status == "analysed"


def test_cap_keeps_best_scores_and_reports_the_rest(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD, HOLD])
    rows = [_row("LOW", 2), _row("TOP", 5), _row("MID", 3), _row("LOW2", 2)]

    results = _run(rows, provider, _store(tmp_path), max_rows=2)

    assert _by_symbol(results) == {
        "TOP": "analysed",
        "MID": "analysed",
        "LOW": "skipped_cap",
        "LOW2": "skipped_cap",
    }
    assert len(provider.calls) == 2


def test_results_keep_input_order(tmp_path: Path) -> None:
    rows = [_row("A", 2), _row("B", 5), _row("C", 1)]

    results = _run(rows, FakeProvider([HOLD, HOLD]), _store(tmp_path))

    assert [r.row.instrument for r in results] == ["A", "B", "C"]


def test_ties_prefer_the_closer_zone(tmp_path: Path) -> None:
    rows = [_row("FAR", 3, dist=0.8), _row("NEAR", 3, dist=0.1)]

    results = _run(rows, FakeProvider([HOLD]), _store(tmp_path), max_rows=1)

    assert _by_symbol(results) == {"NEAR": "analysed", "FAR": "skipped_cap"}


def test_touching_beats_near_at_equal_score(tmp_path: Path) -> None:
    rows = [
        _row("NEAR", 3, dist=0.0, status="NEAR"),
        _row("TOUCH", 3, dist=0.9, status="TOUCHING"),
    ]

    results = _run(rows, FakeProvider([HOLD]), _store(tmp_path), max_rows=1)

    assert _by_symbol(results) == {"TOUCH": "analysed", "NEAR": "skipped_cap"}


def test_non_finite_distance_sorts_last(tmp_path: Path) -> None:
    rows = [_row("NAN", 3, dist=float("nan")), _row("OK", 3, dist=5.0)]

    results = _run(rows, FakeProvider([HOLD]), _store(tmp_path), max_rows=1)

    assert _by_symbol(results) == {"OK": "analysed", "NAN": "skipped_cap"}


def test_rerun_on_same_bar_makes_no_second_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([HOLD, HOLD])
    rows = [_row()]

    first = _run(rows, provider, store)
    second = _run(rows, provider, store)

    assert _statuses(first) == ["analysed"]
    assert _statuses(second) == ["skipped_duplicate"]
    assert len(provider.calls) == 1
    assert second[0].verdict is not None  # the stored verdict is surfaced


def test_same_key_twice_in_one_run_calls_once(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD, HOLD])

    results = _run([_row("AAA", 4), _row("AAA", 3)], provider, _store(tmp_path))

    assert _statuses(results) == ["analysed", "skipped_duplicate"]
    assert results[1].verdict == results[0].verdict
    assert len(provider.calls) == 1


def test_duplicate_in_one_run_even_when_the_store_cannot_save(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD, HOLD])
    store = _BrokenStore(tmp_path / "smc.db", fail_save=True)

    results = _run([_row("AAA", 4), _row("AAA", 3)], provider, store)

    assert _statuses(results) == ["analysed", "skipped_duplicate"]
    assert len(provider.calls) == 1


def test_float_noise_in_zone_bounds_is_still_a_duplicate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([HOLD, HOLD])
    row = _row()

    _run([row], provider, store)
    second = _run([replace(row, zone_low=row.zone_low + 1e-12)], provider, store)

    assert _statuses(second) == ["skipped_duplicate"]
    assert len(provider.calls) == 1


def test_failure_with_unreadable_timestamp_is_retried(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _row()
    _run([row], FakeProvider([]), store)
    [failed] = store.list_recent(1)
    store.save(replace(failed, created_at="not a time", error="AiError: x"))
    provider = FakeProvider([HOLD])

    [result] = _run([row], provider, store)

    assert result.status == "analysed"


def test_duplicates_do_not_consume_the_cap(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([HOLD, HOLD])
    _run([_row("TOP", 5)], provider, store)

    results = _run([_row("TOP", 5), _row("NEW", 2)], provider, store, max_rows=1)

    assert _by_symbol(results) == {"TOP": "skipped_duplicate", "NEW": "analysed"}


def test_new_bar_is_analysed_again(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([HOLD, HOLD])
    later_ohlc = frame([FLAT] * 16 + [*FVG_SETUP, TOUCH_LAST], start="2026-02-01")
    later_row = next(r for r in scan_instrument("AAA", later_ohlc, OPTIONS) if r.zone == "bull FVG")

    def later_source(row: ScanRow) -> HitInputs:
        return hit_inputs_from_ohlc(later_ohlc, row, OPTIONS)

    _run([_row()], provider, store)
    later = analyse_hits([later_row], later_source, provider, store, timeframe=TF)

    assert _statuses(later) == ["analysed"]
    assert len(provider.calls) == 2
    assert len(store.list_recent(10)) == 2


def test_force_reanalyses_and_overwrites_a_stored_success(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([AiReply(HOLD, 0, 0, "old-model"), AiReply(HOLD, 0, 0, "new-model")])
    row = _row()

    _run([row], provider, store)
    forced = _run([row], provider, store, force=True)

    assert _statuses(forced) == ["analysed"]
    assert len(provider.calls) == 2
    saved = store.get(_key_of(row))
    assert saved is not None and saved.model == "new-model"


def test_forced_failure_does_not_clobber_a_stored_success(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _row()
    _run([row], FakeProvider([HOLD]), store)

    forced = _run([row], FakeProvider([]), store, force=True)

    assert _statuses(forced) == ["failed"]
    saved = store.get(_key_of(row))
    assert saved is not None and saved.error is None


def test_provider_failure_is_recorded_and_isolated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rows = [_row("A", 3), _row("B", 2)]

    results = _run(rows, FakeProvider([]), store)  # exhausted at once -> AiError

    assert _statuses(results) == ["failed", "failed"]
    assert results[0].error is not None and "exhausted" in results[0].error
    saved = store.get(_key_of(rows[0]))
    assert saved is not None
    assert saved.verdict is None
    assert saved.error is not None and "exhausted" in saved.error


def test_failure_does_not_stop_later_rows(tmp_path: Path) -> None:
    class Flaky(_Named):
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system: str, user: str) -> AiReply:
            self.calls += 1
            if self.calls == 1:
                raise AiError("rate limited")
            return AiReply(HOLD, 0, 0, "m")

    results = analyse_hits(
        [_row("A", 5), _row("B", 4)], _source, Flaky(), _store(tmp_path), timeframe=TF
    )

    assert _by_symbol(results) == {"A": "failed", "B": "analysed"}


def test_unexpected_provider_exception_never_escapes(tmp_path: Path) -> None:
    class Broken(_Named):
        def complete(self, system: str, user: str) -> AiReply:
            raise RuntimeError("secret-token-123 leaked")

    [result] = analyse_hits([_row()], _source, Broken(), _store(tmp_path), timeframe=TF)

    assert result.status == "failed"
    assert result.error == "RuntimeError"  # class name only; message may hold secrets


def test_failed_row_is_retried_after_the_cooldown(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _row()

    first = _run([row], FakeProvider([]), store)
    provider = FakeProvider([HOLD])
    second = _run([row], provider, store, at=T0 + FAILURE_COOLDOWN + timedelta(seconds=1))

    assert _statuses(first) == ["failed"]
    assert _statuses(second) == ["analysed"]
    assert len(provider.calls) == 1
    assert len(store.list_recent(10)) == 1


def test_recent_failure_is_not_retried_straight_away(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _row()
    _run([row], FakeProvider([]), store)
    provider = FakeProvider([HOLD])

    [again] = _run([row], provider, store, at=T0 + timedelta(minutes=1))

    assert again.status == "skipped_failed_recently"
    assert again.error is not None and "AiError" in again.error
    assert provider.calls == []


def test_row_failing_repeatedly_is_given_up_on(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _row()
    later = T0
    for _ in range(MAX_ATTEMPTS):
        _run([row], FakeProvider([]), store, at=later)
        later += FAILURE_COOLDOWN + timedelta(minutes=1)
    provider = FakeProvider([HOLD])

    [result] = _run([row], provider, store, at=later)

    assert result.status == "skipped_failed_recently"
    assert provider.calls == []


def test_rows_failing_before_the_provider_do_not_use_up_the_cap(tmp_path: Path) -> None:
    def source(row: ScanRow) -> HitInputs:
        if row.instrument == "GOOD":
            return _source(row)
        raise ValueError("no candles")

    bad = [_row(f"BAD{i}", 5) for i in range(5)]
    provider = FakeProvider([HOLD])

    results = analyse_hits(
        [*bad, _row("GOOD", 2)],
        source,
        provider,
        _store(tmp_path),
        timeframe=TF,
        max_rows=1,
        now=lambda: T0,
    )

    assert _by_symbol(results)["GOOD"] == "analysed"
    assert _statuses(results[:5]) == ["failed"] * 5
    assert len(provider.calls) == 1


def test_provider_failures_do_use_up_the_cap(tmp_path: Path) -> None:
    rows = [_row("A", 5), _row("B", 4), _row("C", 3)]

    results = _run(rows, FakeProvider([]), _store(tmp_path), max_rows=2)

    assert _by_symbol(results) == {"A": "failed", "B": "failed", "C": "skipped_cap"}


def test_source_failure_is_recorded_without_leaking_the_message(tmp_path: Path) -> None:
    def bad_source(row: ScanRow) -> HitInputs:
        raise ValueError("no candles for symbol, key=sk-secret")

    provider = FakeProvider([])

    [result] = analyse_hits(
        [_row()], bad_source, provider, _store(tmp_path), timeframe=TF, now=lambda: T0
    )

    assert result.status == "failed"
    assert result.error == "ValueError"
    assert provider.calls == []


def test_non_finite_zone_bounds_fail_the_row_not_the_run(tmp_path: Path) -> None:
    provider = FakeProvider([HOLD])
    rows = [_row("NANZONE", 5, zone_high=float("nan")), _row("OK", 3)]

    results = _run(rows, provider, _store(tmp_path))

    assert _by_symbol(results) == {"NANZONE": "failed", "OK": "analysed"}
    assert results[0].error is not None and "finite" in results[0].error


def test_store_save_error_keeps_the_paid_result_and_the_run_going(tmp_path: Path) -> None:
    store = _BrokenStore(tmp_path / "smc.db", fail_save=True)
    provider = FakeProvider([HOLD, HOLD])

    results = _run([_row("A", 5), _row("B", 4)], provider, store)

    assert _statuses(results) == ["analysed", "analysed"]
    assert all(r.verdict is not None for r in results)
    assert all(r.error is not None and "StoreError" in r.error for r in results)
    assert len(provider.calls) == 2


def test_store_save_error_on_a_failed_row_is_reported(tmp_path: Path) -> None:
    store = _BrokenStore(tmp_path / "smc.db", fail_save=True)

    [result] = _run([_row()], FakeProvider([]), store)

    assert result.status == "failed"
    assert result.error is not None and "AiError" in result.error and "StoreError" in result.error


def test_store_lookup_error_fails_the_row_without_a_provider_call(tmp_path: Path) -> None:
    store = _BrokenStore(tmp_path / "smc.db", fail_get=True)
    provider = FakeProvider([HOLD])

    [result] = _run([_row()], provider, store)

    assert result.status == "failed"
    assert result.error == "StoreError: lookup failed"
    assert provider.calls == []


def test_garbage_model_reply_is_saved_as_downgraded_hold(tmp_path: Path) -> None:
    store = _store(tmp_path)

    [result] = _run([_row()], FakeProvider(["not json at all"]), store)

    assert result.status == "analysed"
    assert result.verdict is not None
    assert result.verdict.action == "HOLD" and result.verdict.downgraded
    [saved] = store.list_recent(1)
    assert saved.verdict is not None and saved.verdict["downgraded"] is True


def test_hostile_reply_text_is_stored_not_executed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    evil = (
        '{"action": "HOLD", "confidence": 1, "reasons": ["x\'); DROP TABLE analyses;--"],'
        ' "summary": "ok"}'
    )

    _run([_row()], FakeProvider([evil]), store)

    assert len(store.list_recent(10)) == 1


def test_duplicate_with_unreadable_stored_verdict_still_skips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    provider = FakeProvider([HOLD])
    row = _row()
    _run([row], provider, store)
    [saved] = store.list_recent(1)
    store.save(replace(saved, verdict={"action": "garbage"}), overwrite=True)

    [result] = _run([row], provider, store)

    assert result.status == "skipped_duplicate"
    assert result.verdict is None
    assert len(provider.calls) == 1


def test_estimate_cost_known_model() -> None:
    cost = estimate_cost("claude-sonnet-5-5", 1_000_000, 1_000_000)

    assert cost is not None and cost > 0


def test_estimate_cost_unknown_model_or_missing_tokens() -> None:
    assert estimate_cost("fake", 10, 10) is None
    assert estimate_cost("claude-sonnet-5-5", None, 10) is None


def test_zero_token_fake_reply_has_no_cost(tmp_path: Path) -> None:
    store = _store(tmp_path)

    _run([_row()], FakeProvider([HOLD]), store)

    [saved] = store.list_recent(1)
    assert saved.cost_estimate is None
    assert saved.model == "fake"


def test_hit_inputs_from_ohlc_matches_the_scan() -> None:
    row = _base_row()

    inputs = hit_inputs_from_ohlc(OHLC, row, OPTIONS)

    assert inputs.state.zone.bottom == row.zone_low
    assert isinstance(inputs.ohlc, pd.DataFrame)


def test_hit_inputs_from_ohlc_tolerates_float_noise() -> None:
    row = replace(_base_row(), zone_low=_base_row().zone_low + 1e-12)

    assert hit_inputs_from_ohlc(OHLC, row, OPTIONS).state.zone.bottom == _base_row().zone_low


def test_hit_inputs_from_ohlc_rejects_unknown_zone() -> None:
    row = replace(_base_row(), zone_low=0.5)

    with pytest.raises(ValueError, match="zone"):
        hit_inputs_from_ohlc(OHLC, row, OPTIONS)
