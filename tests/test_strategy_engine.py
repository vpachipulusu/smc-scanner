"""Strategy engine: golden equivalence with the pre-strategy scanner, filters, scoring, MTF."""

import csv
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from conftest import FVG_SETUP, FVG_TOP, with_warmup
from mtf_support import HIT_FRAME, SWING, TfLoader, zigzag

from smc_scanner.config import DEFAULT_DEMO_SYMBOLS, MIN_BARS, TIMEFRAMES
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.models import BULLISH, Bias, ScanRow, ZoneContext
from smc_scanner.report import COLUMNS, write_csv
from smc_scanner.scanner import (
    ScanOptions,
    context_row,
    latest_bar,
    scan_instrument,
    scan_watchlist,
    sort_rows,
    zone_contexts,
)
from smc_scanner.scoring import score_zone
from smc_scanner.strategy import DEFAULT_STRATEGY_SLUG, Strategy
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES
from smc_scanner.strategy.conditions import UnknownConditionError
from smc_scanner.strategy.engine import (
    apply_strategy,
    run_scan_with_strategy,
    scan_instrument_with_strategy,
    scan_watchlist_with_strategy,
)
from smc_scanner.structure import (
    analyse_structure,
    atr,
    confirmed_swing_frame,
    confirmed_swings,
)
from smc_scanner.zones import evaluate_zones, select_hits

SMC_DEFAULT = BUILTIN_STRATEGIES[DEFAULT_STRATEGY_SLUG]
_IGNORED = {"strategy", "conditions"}


def _legacy_scan_instrument(symbol: str, ohlc: pd.DataFrame, options: ScanOptions) -> list[ScanRow]:
    """``scanner.scan_instrument`` exactly as it was before TRAD-35, kept as the golden oracle."""
    if len(ohlc) < MIN_BARS:
        raise ValueError(f"{symbol}: need at least {MIN_BARS} candles, got {len(ohlc)}")
    swings = confirmed_swings(ohlc, options.swing_length)
    structure = analyse_structure(ohlc, swings)
    valid = evaluate_zones(
        ohlc, confirmed_swing_frame(ohlc, swings), structure.atr, options.near_atr
    )
    last_index = len(ohlc) - 1
    close = float(ohlc["close"].iloc[last_index])
    bar_time = str(ohlc["time"].iloc[last_index])
    rows: list[ScanRow] = []
    for state in select_hits(valid, options.all_touches):
        if state.status is None:
            continue
        confluence = score_zone(state, structure, valid, ohlc)
        side = "bull" if state.zone.direction == BULLISH else "bear"
        rows.append(
            ScanRow(
                instrument=symbol,
                status=state.status,
                zone=f"{side} {state.zone.kind}",
                zone_low=state.zone.bottom,
                zone_high=state.zone.top,
                price=close,
                dist_atr=state.distance_atr,
                bias=structure.bias,
                in_ote=confluence.in_ote,
                trendline_ok=confluence.trendline_ok,
                ob_fvg=confluence.stacked,
                score=confluence.score,
                zone_age=last_index - state.zone.formed_index,
                prior_touches=state.prior_touches,
                bar_time=bar_time,
            )
        )
    return rows


def _core(rows: list[ScanRow]) -> list[dict[str, Any]]:
    return [{k: v for k, v in asdict(row).items() if k not in _IGNORED} for row in rows]


def _strategy(**overrides: Any) -> Strategy:
    return Strategy.model_validate({**SMC_DEFAULT.model_dump(), "builtin": False, **overrides})


def _near_tested_frame() -> pd.DataFrame:
    """A previously tested bullish FVG with the latest close 0.4 ATR above it: NEAR, 1 touch."""
    tested = list(FVG_SETUP)
    tested[4] = (107.0, 108.0, 102.8, 105.0)
    probe = with_warmup([*tested, (105.0, 105.5, 104.5, 105.0)])
    close = FVG_TOP + 0.4 * atr(probe)
    return with_warmup([*tested, (close + 0.2, close + 0.5, close - 0.1, close)])


# --- golden: smc-default reproduces the pre-change scanner --------------------------------


_DEMO_CASES = [(tf, symbol) for tf in TIMEFRAMES for symbol in DEFAULT_DEMO_SYMBOLS]


@pytest.fixture(scope="module")
def demo_frames() -> dict[tuple[str, str], pd.DataFrame]:
    loader = DemoLoader()
    return {(tf, symbol): loader.load(symbol, tf, 500) for tf, symbol in _DEMO_CASES}


@pytest.mark.parametrize("all_touches", [False, True])
def test_smc_default_matches_the_legacy_scanner_on_demo_data(
    demo_frames: dict[tuple[str, str], pd.DataFrame], all_touches: bool
) -> None:
    options = ScanOptions(all_touches=all_touches)
    expected_all: list[ScanRow] = []
    actual_all: list[ScanRow] = []
    for (_tf, symbol), ohlc in demo_frames.items():
        expected = _legacy_scan_instrument(symbol, ohlc, options)
        actual = scan_instrument_with_strategy(symbol, ohlc, options=options)
        assert _core(actual) == _core(expected), symbol
        assert _core(scan_instrument(symbol, ohlc, options)) == _core(expected), symbol
        expected_all.extend(expected)
        actual_all.extend(actual)
    assert _core(sort_rows(actual_all)) == _core(sort_rows(expected_all))
    assert {row.status for row in expected_all} == {"TOUCHING", "NEAR"}
    assert any(row.prior_touches > 0 for row in expected_all) is all_touches


def test_smc_default_own_options_collect_all_touches(
    demo_frames: dict[tuple[str, str], pd.DataFrame],
) -> None:
    options = ScanOptions(all_touches=True)
    for (_tf, symbol), ohlc in demo_frames.items():
        expected = _legacy_scan_instrument(symbol, ohlc, options)
        assert _core(scan_instrument_with_strategy(symbol, ohlc)) == _core(expected), symbol


@pytest.mark.parametrize("all_touches", [False, True])
def test_smc_default_matches_the_legacy_scanner_on_synthetic_frames(
    fvg_touching: pd.DataFrame,
    fvg_tested_before: pd.DataFrame,
    ob_touching: pd.DataFrame,
    all_touches: bool,
) -> None:
    options = ScanOptions(swing_length=SWING, all_touches=all_touches)
    frames = [fvg_touching, fvg_tested_before, ob_touching, _near_tested_frame()]
    statuses = set()
    for ohlc in frames:
        expected = _legacy_scan_instrument("SYN", ohlc, options)
        actual = scan_instrument_with_strategy("SYN", ohlc, SMC_DEFAULT, options=options)
        assert _core(actual) == _core(expected)
        statuses |= {(row.status, row.prior_touches > 0) for row in expected}
    if all_touches:
        assert {("TOUCHING", True), ("NEAR", True)} <= statuses


def test_smc_default_rows_carry_the_slug_and_every_condition(fvg_touching: pd.DataFrame) -> None:
    rows = scan_instrument_with_strategy("SYN", fvg_touching, options=ScanOptions(swing_length=2))

    assert len(rows) == 1
    assert rows[0].strategy == DEFAULT_STRATEGY_SLUG
    assert set(rows[0].conditions) == {"aligned", "in_ote", "trendline_ok", "stacked"}
    assert rows[0].score == sum(rows[0].conditions.values())


_ROW_VALUES: dict[str, Any] = {
    "instrument": "X",
    "status": "NEAR",
    "zone": "bull FVG",
    "zone_low": 1.0,
    "zone_high": 2.0,
    "price": 2.5,
    "dist_atr": 0.2,
    "bias": "range",
    "in_ote": False,
    "trendline_ok": False,
    "ob_fvg": False,
    "score": 0,
    "zone_age": 3,
    "prior_touches": 0,
    "bar_time": "t",
}


def test_scan_row_defaults_keep_old_constructors_working() -> None:
    fields_by_name = {field.name: field for field in fields(ScanRow)}

    assert fields_by_name["strategy"].default == DEFAULT_STRATEGY_SLUG
    row = ScanRow(**_ROW_VALUES)
    assert row.strategy == DEFAULT_STRATEGY_SLUG
    assert row.conditions == {}
    assert hash(row) == hash(ScanRow(**_ROW_VALUES))  # conditions stay out of the hash


# --- fresh, filters and scoring --------------------------------------------------------


def test_requiring_fresh_drops_repeat_touches(fvg_tested_before: pd.DataFrame) -> None:
    fresh = _strategy(swing_length=SWING, require=[{"key": "fresh"}])
    loose = _strategy(swing_length=SWING)

    assert fresh.to_scan_options().all_touches is False
    assert scan_instrument_with_strategy("SYN", fvg_tested_before, fresh) == []
    rows = scan_instrument_with_strategy("SYN", fvg_tested_before, loose)
    assert [row.prior_touches for row in rows] == [1]


def test_fresh_still_applies_when_options_collect_all_touches(
    fvg_tested_before: pd.DataFrame,
) -> None:
    fresh = _strategy(swing_length=SWING, require=[{"key": "fresh"}])
    options = ScanOptions(swing_length=SWING, all_touches=True)

    assert scan_instrument_with_strategy("SYN", fvg_tested_before, fresh, options=options) == []


def test_zone_kinds_filter(fvg_touching: pd.DataFrame) -> None:
    ob_only = _strategy(swing_length=SWING, zone_kinds=["OB"])

    assert scan_instrument_with_strategy("SYN", fvg_touching, ob_only) == []


def test_statuses_filter(fvg_touching: pd.DataFrame) -> None:
    near_only = _strategy(swing_length=SWING, statuses=["NEAR"])

    assert scan_instrument_with_strategy("SYN", fvg_touching, near_only) == []


def test_failing_requirement_drops_the_zone(fvg_touching: pd.DataFrame) -> None:
    needs_ob = _strategy(
        swing_length=SWING, require=[{"key": "zone_kind", "params": {"kind": "OB"}}]
    )
    needs_fvg = _strategy(
        swing_length=SWING, require=[{"key": "zone_kind", "params": {"kind": "FVG"}}]
    )

    assert scan_instrument_with_strategy("SYN", fvg_touching, needs_ob) == []
    rows = scan_instrument_with_strategy("SYN", fvg_touching, needs_fvg)
    assert rows[0].conditions["zone_kind"] is True


def test_score_counts_passing_score_conditions_and_min_score_filters(
    fvg_touching: pd.DataFrame,
) -> None:
    score = [{"key": "touching"}, {"key": "fresh"}, {"key": "aligned"}]  # 2 of 3 pass here
    two = _strategy(swing_length=SWING, score=score, min_score=2)
    three = _strategy(swing_length=SWING, score=score, min_score=3)

    rows = scan_instrument_with_strategy("SYN", fvg_touching, two)
    assert [row.score for row in rows] == [2]
    assert rows[0].conditions == {"touching": True, "fresh": True, "aligned": False}
    assert rows[0].strategy == two.slug
    assert scan_instrument_with_strategy("SYN", fvg_touching, three) == []


def test_apply_strategy_is_pure_over_contexts(fvg_touching: pd.DataFrame) -> None:
    contexts = zone_contexts("SYN", fvg_touching, ScanOptions(swing_length=SWING))
    price, bar_time = latest_bar(fvg_touching)

    first = apply_strategy(contexts, SMC_DEFAULT, symbol="SYN", price=price, bar_time=bar_time)
    second = apply_strategy(contexts, SMC_DEFAULT, symbol="SYN", price=price, bar_time=bar_time)

    assert first == second
    assert first[0].price == price and first[0].bar_time == bar_time


def test_unknown_condition_in_a_strategy_raises(fvg_touching: pd.DataFrame) -> None:
    broken = _strategy(swing_length=SWING, require=[{"key": "no_such_condition"}])

    with pytest.raises(UnknownConditionError):
        scan_instrument_with_strategy("SYN", fvg_touching, broken)


@pytest.mark.parametrize("bars", [0, MIN_BARS - 1])
def test_short_frames_raise_the_candle_count_error(bars: int, fvg_touching: pd.DataFrame) -> None:
    short = fvg_touching.iloc[:bars]

    with pytest.raises(ValueError, match="need at least"):
        scan_instrument("SYN", short, ScanOptions())
    with pytest.raises(ValueError, match="need at least"):
        scan_instrument_with_strategy("SYN", short)


def test_context_row_rejects_a_zone_without_status(fvg_touching: pd.DataFrame) -> None:
    ctx = zone_contexts("SYN", fvg_touching, ScanOptions(swing_length=SWING))[0]
    stale = ZoneContext(
        state=type(ctx.state)(ctx.state.zone, 0, False, None, 1.0),
        structure=ctx.structure,
        valid=ctx.valid,
        ohlc=ctx.ohlc,
        last_index=ctx.last_index,
        htf_bias=None,
    )

    with pytest.raises(ValueError, match="no status"):
        context_row(stale, symbol="SYN", price=1.0, bar_time="t")


def test_zone_contexts_carry_the_htf_bias(fvg_touching: pd.DataFrame) -> None:
    contexts = zone_contexts("SYN", fvg_touching, ScanOptions(swing_length=SWING), "bearish")

    assert contexts and all(ctx.htf_bias == "bearish" for ctx in contexts)
    assert all(ctx.last_index == len(fvg_touching) - 1 for ctx in contexts)


def test_htf_aligned_condition_uses_the_given_bias(fvg_touching: pd.DataFrame) -> None:
    strategy = _strategy(swing_length=SWING, require=[{"key": "htf_aligned"}], mtf=True)

    assert scan_instrument_with_strategy("SYN", fvg_touching, strategy, htf_bias="bearish") == []
    assert scan_instrument_with_strategy("SYN", fvg_touching, strategy, htf_bias="bullish")
    assert scan_instrument_with_strategy("SYN", fvg_touching, strategy)  # unknown passes


# --- watchlist, MTF and loaders --------------------------------------------------------


def _loader(htf: pd.DataFrame | None = None) -> TfLoader:
    frames = {("EURUSD", "1h"): HIT_FRAME, ("EURUSD", "30m"): zigzag(1)}
    if htf is not None:
        frames[("EURUSD", "4h")] = htf
    return TfLoader(frames)


SWING_DEFAULT = _strategy(swing_length=SWING)


@pytest.mark.parametrize("htf_drift", [1, -1, 0], ids=["agree", "oppose", "range"])
def test_require_htf_aligned_semantics_are_unchanged(htf_drift: int) -> None:
    options = ScanOptions(swing_length=SWING)
    legacy = scan_watchlist(
        _loader(zigzag(htf_drift)),
        ["EURUSD"],
        "1h",
        100,
        options,
        mtf=True,
        require_htf_aligned=True,
    )
    result = scan_watchlist_with_strategy(
        _loader(zigzag(htf_drift)),
        ["EURUSD"],
        "1h",
        100,
        SWING_DEFAULT,
        mtf=True,
        require_htf_aligned=True,
    )

    assert _core(list(result.rows)) == _core(list(legacy.rows))
    assert result.htf_bias == legacy.htf_bias


@pytest.mark.parametrize(("htf_drift", "kept"), [(1, True), (-1, False), (0, False)])
def test_strategy_require_htf_aligned_turns_on_mtf(htf_drift: int, kept: bool) -> None:
    strategy = _strategy(swing_length=SWING, mtf=True, require_htf_aligned=True)

    result = scan_watchlist_with_strategy(
        _loader(zigzag(htf_drift)), ["EURUSD"], "1h", 100, strategy
    )

    assert bool(result.rows) is kept
    assert "EURUSD" in result.htf_bias


@pytest.mark.parametrize(("htf_drift", "kept"), [(1, True), (-1, False), (0, False)])
def test_htf_aligned_condition_reads_the_loaded_htf(htf_drift: int, kept: bool) -> None:
    strategy = _strategy(swing_length=SWING, mtf=True, require=[{"key": "htf_aligned"}])

    result = scan_watchlist_with_strategy(
        _loader(zigzag(htf_drift)), ["EURUSD"], "1h", 100, strategy
    )

    assert bool(result.rows) is kept


def test_htf_is_loaded_once_per_symbol() -> None:
    loader = _loader(zigzag(1))
    strategy = _strategy(swing_length=SWING, mtf=True, require=[{"key": "htf_aligned"}])

    scan_watchlist_with_strategy(loader, ["EURUSD"], "1h", 100, strategy)

    assert loader.calls.count(("EURUSD", "4h")) == 1


def test_symbols_without_candidate_zones_do_not_load_the_htf() -> None:
    loader = TfLoader({("EURUSD", "1h"): HIT_FRAME.iloc[:16]})
    strategy = _strategy(swing_length=SWING, mtf=True, require=[{"key": "htf_aligned"}])

    result = scan_watchlist_with_strategy(loader, ["EURUSD"], "1h", 100, strategy)

    assert result.rows == ()
    assert loader.calls == [("EURUSD", "1h")]


def test_htf_aligned_condition_turns_on_mtf_by_itself() -> None:
    loader = _loader(zigzag(-1))
    strategy = _strategy(swing_length=SWING, require=[{"key": "htf_aligned"}])  # mtf off

    result = scan_watchlist_with_strategy(loader, ["EURUSD"], "1h", 100, strategy)

    assert result.rows == ()  # filtered, not silently passed
    assert ("EURUSD", "4h") in loader.calls


def test_without_an_htf_condition_the_htf_loads_only_for_hits() -> None:
    loader = _loader(zigzag(1))
    ob_only = _strategy(swing_length=SWING, mtf=True, zone_kinds=["OB"])  # the hit is an FVG

    result = scan_watchlist_with_strategy(loader, ["EURUSD"], "1h", 100, ob_only)

    assert result.rows == ()
    assert loader.calls == [("EURUSD", "1h")]


def test_without_mtf_the_htf_lookup_is_unknown_and_loads_nothing() -> None:
    seen: list[Bias | None] = []
    loader = _loader(zigzag(1))

    def producer(symbol: str, ohlc: pd.DataFrame, htf: Any) -> list[ScanRow]:
        seen.append(htf())
        return []

    scan_watchlist(loader, ["EURUSD"], "1h", 100, ScanOptions(), row_producer=producer)

    assert seen == [None]
    assert loader.calls == [("EURUSD", "1h")]


def test_a_failing_row_producer_is_recorded_as_a_failure() -> None:
    def producer(symbol: str, ohlc: pd.DataFrame, htf: Any) -> list[ScanRow]:
        raise RuntimeError("boom")

    result = scan_watchlist(
        _loader(), ["EURUSD"], "1h", 100, ScanOptions(swing_length=SWING), row_producer=producer
    )

    assert [failure.error for failure in result.failures] == ["RuntimeError: boom"]
    assert result.scanned == 0


def test_watchlist_rows_are_sorted_and_failures_recorded() -> None:
    loader = _loader()

    result = scan_watchlist_with_strategy(loader, ["BAD", "EURUSD"], "1h", 100, SWING_DEFAULT)

    assert [row.instrument for row in result.rows] == ["EURUSD"]
    assert [failure.symbol for failure in result.failures] == ["BAD"]
    assert result.rows[0].strategy == SWING_DEFAULT.slug


def test_run_scan_with_strategy_closes_the_loader() -> None:
    loader = _loader()

    result = run_scan_with_strategy(loader, ["EURUSD"], "1h", 100, SWING_DEFAULT)

    assert loader.closed
    assert len(result.rows) == 1


def test_bad_strategy_fails_before_loading_and_still_closes() -> None:
    loader = _loader()
    broken = _strategy(swing_length=SWING, score=[{"key": "no_such_condition"}])

    with pytest.raises(UnknownConditionError):
        run_scan_with_strategy(loader, ["EURUSD"], "1h", 100, broken)

    assert loader.calls == []
    assert loader.closed


def test_run_scan_with_strategy_defaults_to_smc_default() -> None:
    result = run_scan_with_strategy(
        DemoLoader(), ["EURUSD"], "1h", 500, options=ScanOptions(all_touches=True)
    )
    legacy = _legacy_scan_instrument(
        "EURUSD", DemoLoader().load("EURUSD", "1h", 500), ScanOptions(all_touches=True)
    )

    assert _core(list(result.rows)) == _core(sort_rows(legacy))


def test_scan_watchlist_uses_an_injected_row_producer() -> None:
    seen: list[tuple[str, Bias | None]] = []
    loader = _loader(zigzag(-1))

    def producer(symbol: str, ohlc: pd.DataFrame, htf: Any) -> list[ScanRow]:
        seen.append((symbol, htf()))
        seen.append((symbol, htf()))  # memoised: the HTF loads once
        return []

    options = ScanOptions(swing_length=SWING)
    scan_watchlist(loader, ["EURUSD"], "1h", 100, options, mtf=True, row_producer=producer)

    assert seen == [("EURUSD", "bearish"), ("EURUSD", "bearish")]
    assert loader.calls.count(("EURUSD", "4h")) == 1


def test_ltf_prefetch_uses_the_strategy_score() -> None:
    loader = _loader(zigzag(1))
    strategy = _strategy(swing_length=SWING, mtf=True)

    scan_watchlist_with_strategy(loader, ["EURUSD"], "1h", 100, strategy, ltf_min_score=0)

    assert ("EURUSD", "30m") in loader.calls


# --- report ------------------------------------------------------------------------------


def test_csv_keeps_its_columns_for_strategy_rows(
    tmp_path: Path, fvg_touching: pd.DataFrame
) -> None:
    rows = scan_instrument_with_strategy("SYN", fvg_touching, SWING_DEFAULT)
    out = write_csv(rows, tmp_path / "scan.csv")

    with out.open(newline="") as handle:
        written = list(csv.DictReader(handle))
    assert tuple(written[0].keys()) == COLUMNS
    assert not _IGNORED & set(COLUMNS)


def test_csv_neutralises_formula_prefixes_in_scan_cells(tmp_path: Path) -> None:
    out = write_csv([ScanRow(**{**_ROW_VALUES, "instrument": "@SUM"})], tmp_path / "scan.csv")

    with out.open(newline="") as handle:
        written = list(csv.DictReader(handle))
    assert written[0]["instrument"] == "'@SUM"
    assert written[0]["zone"] == "bull FVG"
