"""Condition registry: listing, lookup, parameter validation and every built-in condition."""

from dataclasses import replace
from typing import Any

import pandas as pd
import pytest
from conftest import FLAT, frame
from mtf_support import SWING, zigzag

from smc_scanner.config import MAX_BARS, MAX_NEAR_ATR
from smc_scanner.models import (
    BEARISH,
    BULLISH,
    Bias,
    Direction,
    ScanRow,
    Status,
    Structure,
    Zone,
    ZoneContext,
    ZoneKind,
    ZoneState,
)
from smc_scanner.mtf import htf_allows, timeframe_view
from smc_scanner.strategy import ConditionRef
from smc_scanner.strategy.conditions import (
    Condition,
    ConditionError,
    ConditionParamError,
    UnknownConditionError,
    conditions,
    get,
    resolve,
)
from smc_scanner.structure import analyse_structure, confirmed_swings, last_break_of_structure
from smc_scanner.zones import detect_fvgs

OHLC = frame([FLAT] * 3 + [(100.0, 106.0, 103.0, 105.0)])  # latest low 103, high 106
LAST = len(OHLC) - 1

_BASE = Structure(
    atr=2.0,
    bias="range",
    ote_bullish=None,
    ote_bearish=None,
    trendline_bullish=None,
    trendline_bearish=None,
)


def _state(
    kind: ZoneKind = "FVG",
    direction: Direction = BULLISH,
    *,
    bottom: float = 101.0,
    top: float = 103.0,
    prior: int = 0,
    status: Status | None = "TOUCHING",
    dist: float = 0.0,
    formed: int = 1,
) -> ZoneState:
    zone = Zone(kind, direction, top=top, bottom=bottom, formed_index=formed, touch_start=3)
    return ZoneState(zone, prior_touches=prior, invalidated=False, status=status, distance_atr=dist)


def _ctx(
    state: ZoneState | None = None,
    *,
    others: tuple[ZoneState, ...] = (),
    htf: Bias | None = None,
    ohlc: pd.DataFrame = OHLC,
    **structure: Any,
) -> ZoneContext:
    zone_state = state or _state()
    return ZoneContext(
        state=zone_state,
        structure=replace(_BASE, **structure),
        valid=(zone_state, *others),
        ohlc=ohlc,
        last_index=len(ohlc) - 1,
        htf_bias=htf,
    )


def _check(key: str, ctx: ZoneContext, params: dict[str, Any] | None = None) -> bool:
    return get(key, params).evaluate(ctx)


# --- registry ---------------------------------------------------------------------------


def test_listing_is_ordered_and_complete() -> None:
    assert [info.key for info in conditions()] == [
        "aligned",
        "in_ote",
        "trendline_ok",
        "stacked",
        "fresh",
        "touching",
        "max_zone_age",
        "max_distance_atr",
        "zone_kind",
        "bias_is",
        "htf_aligned",
        "ob_swept_prior",
        "displacement_fvg",
        "bos_confirmed",
    ]


def test_listing_carries_labels_and_param_schemas() -> None:
    listed = {info.key: info for info in conditions()}

    assert all(info.label for info in listed.values())
    bars = listed["max_zone_age"].params_schema["properties"]["bars"]
    assert (bars["minimum"], bars["maximum"]) == (1, MAX_BARS)
    assert listed["max_zone_age"].params_schema["required"] == ["bars"]
    assert listed["aligned"].params_schema.get("properties", {}) == {}
    assert listed["zone_kind"].params_schema["properties"]["kind"]["enum"] == ["FVG", "OB"]
    within = listed["displacement_fvg"].params_schema["properties"]["within_bars"]
    assert (within["type"], within["minimum"], within["maximum"]) == ("integer", 1, 5)
    assert within["default"] == 3
    assert "required" not in listed["displacement_fvg"].params_schema


def test_listing_returns_fresh_schemas_each_call() -> None:
    first = conditions()[0].params_schema
    first["tampered"] = True

    assert "tampered" not in conditions()[0].params_schema


def test_get_returns_a_condition_bound_to_validated_params() -> None:
    condition = get("max_zone_age", {"bars": 20})

    assert isinstance(condition, Condition)
    assert (condition.key, condition.label) == ("max_zone_age", "Zone at most N bars old")
    assert condition.params.model_dump() == {"bars": 20}


def test_resolve_reads_a_condition_ref() -> None:
    condition = resolve(ConditionRef(key="zone_kind", params={"kind": "OB"}))

    assert condition.key == "zone_kind"
    assert condition.params.model_dump() == {"kind": "OB"}


def test_unknown_key_raises_a_typed_error() -> None:
    with pytest.raises(UnknownConditionError, match="unknown condition: 'nope'") as caught:
        get("nope")

    assert caught.value.key == "nope"
    assert isinstance(caught.value, ConditionError)


def test_unknown_key_message_never_echoes_malformed_input() -> None:
    with pytest.raises(UnknownConditionError) as caught:
        get("<script>alert(1)</script>")

    assert "script" not in str(caught.value)
    assert caught.value.key == ""  # the attribute is as safe to log as the message


def test_unknown_param_names_are_not_echoed_when_malformed() -> None:
    with pytest.raises(ConditionParamError) as caught:
        get("aligned", {"<script>": 1})

    assert "script" not in str(caught.value)
    assert "(malformed name)" in str(caught.value)


@pytest.mark.parametrize(
    ("key", "params"),
    [
        ("aligned", {"extra": 1}),  # no params allowed
        ("max_zone_age", {}),  # bars is required
        ("max_zone_age", {"bars": 20, "other": 1}),  # unknown name
        ("max_zone_age", {"bars": True}),  # bool is not an int
        ("max_zone_age", {"bars": "20"}),  # no string coercion
        ("max_zone_age", {"bars": 20.0}),  # no float truncation
        ("max_zone_age", {"bars": 0}),
        ("max_zone_age", {"bars": MAX_BARS + 1}),
        ("max_distance_atr", {"atr": True}),
        ("max_distance_atr", {"atr": "0.5"}),
        ("max_distance_atr", {"atr": -0.1}),
        ("max_distance_atr", {"atr": MAX_NEAR_ATR + 0.1}),
        ("max_distance_atr", {"atr": float("nan")}),
        ("zone_kind", {"kind": "BOS"}),
        ("zone_kind", {}),
        ("bias_is", {"bias": "up"}),
        ("bias_is", {"bias": 1}),
        ("ob_swept_prior", {"bars": 1}),
        ("bos_confirmed", {"direction": "bullish"}),
        ("displacement_fvg", {"within_bars": 0}),
        ("displacement_fvg", {"within_bars": 6}),
        ("displacement_fvg", {"within_bars": 3.0}),  # no float truncation
        ("displacement_fvg", {"within_bars": "3"}),  # no string coercion
        ("displacement_fvg", {"within_bars": True}),  # bool is not an int
        ("displacement_fvg", {"within_bars": 3, "other": 1}),
    ],
)
def test_bad_params_raise_a_typed_error(key: str, params: dict[str, Any]) -> None:
    with pytest.raises(ConditionParamError) as caught:
        get(key, params)

    assert caught.value.key == key
    assert isinstance(caught.value, ConditionError)


def test_param_error_message_never_echoes_the_value() -> None:
    with pytest.raises(ConditionParamError) as caught:
        get("zone_kind", {"kind": "EVILVALUE"})

    message = str(caught.value)
    assert "EVILVALUE" not in message
    assert "zone_kind" in message and "kind" in message


def test_float_param_accepts_an_int() -> None:
    condition = get("max_distance_atr", {"atr": 1})

    assert condition.params.model_dump() == {"atr": 1.0}
    assert isinstance(condition.params.model_dump()["atr"], float)


def test_condition_params_are_frozen() -> None:
    condition = get("max_zone_age", {"bars": 5})

    with pytest.raises(ValueError):
        condition.params.bars = 6  # type: ignore[attr-defined]


def test_errors_are_value_errors_for_callers_that_validate() -> None:
    assert issubclass(UnknownConditionError, ValueError)
    assert issubclass(ConditionParamError, ValueError)


# --- built-in conditions ----------------------------------------------------------------


def test_aligned_follows_the_trend_and_never_a_range() -> None:
    assert _check("aligned", _ctx(bias="bullish"))
    assert not _check("aligned", _ctx(bias="bearish"))
    assert not _check("aligned", _ctx(bias="range"))


def test_in_ote_needs_an_overlapping_band() -> None:
    assert _check("in_ote", _ctx(ote_bullish=(102.0, 104.0)))
    assert not _check("in_ote", _ctx(ote_bullish=(104.0, 105.0)))
    assert not _check("in_ote", _ctx())


def test_trendline_ok_needs_the_latest_low_above_the_line() -> None:
    assert _check("trendline_ok", _ctx(trendline_bullish=102.5))
    assert not _check("trendline_ok", _ctx(trendline_bullish=103.5))
    assert not _check("trendline_ok", _ctx())


def test_stacked_needs_an_overlapping_opposite_kind_same_direction() -> None:
    ob = _state("OB", BULLISH, bottom=100.0, top=102.0)
    bear_ob = _state("OB", BEARISH, bottom=100.0, top=102.0)

    assert _check("stacked", _ctx(others=(ob,)))
    assert not _check("stacked", _ctx(others=(bear_ob,)))
    assert not _check("stacked", _ctx())


def test_fresh_means_no_prior_touches() -> None:
    assert _check("fresh", _ctx(_state(prior=0)))
    assert not _check("fresh", _ctx(_state(prior=2)))


def test_touching_means_touching_status() -> None:
    assert _check("touching", _ctx(_state(status="TOUCHING")))
    assert not _check("touching", _ctx(_state(status="NEAR")))


def test_max_zone_age_counts_bars_since_formation() -> None:
    ctx = _ctx(_state(formed=1))  # LAST is 3: two bars old

    assert _check("max_zone_age", ctx, {"bars": 2})
    assert not _check("max_zone_age", ctx, {"bars": 1})


def test_max_distance_atr_is_inclusive() -> None:
    ctx = _ctx(_state(status="NEAR", dist=0.3))

    assert _check("max_distance_atr", ctx, {"atr": 0.3})
    assert not _check("max_distance_atr", ctx, {"atr": 0.2})


def test_zone_kind_matches_the_kind() -> None:
    assert _check("zone_kind", _ctx(_state("OB")), {"kind": "OB"})
    assert not _check("zone_kind", _ctx(_state("FVG")), {"kind": "OB"})


def test_bias_is_matches_the_structure_bias() -> None:
    assert _check("bias_is", _ctx(bias="range"), {"bias": "range"})
    assert not _check("bias_is", _ctx(bias="bullish"), {"bias": "bearish"})


def _row(direction: Direction) -> ScanRow:
    side = "bull" if direction == BULLISH else "bear"
    return ScanRow(
        instrument="X",
        status="TOUCHING",
        zone=f"{side} FVG",
        zone_low=1.0,
        zone_high=2.0,
        price=1.5,
        dist_atr=0.0,
        bias="range",
        in_ote=False,
        trendline_ok=False,
        ob_fvg=False,
        score=0,
        zone_age=1,
        prior_touches=0,
        bar_time="t",
    )


@pytest.mark.parametrize("direction", [BULLISH, BEARISH])
@pytest.mark.parametrize("htf", [None, "bullish", "bearish", "range"])
def test_htf_aligned_mirrors_htf_allows(direction: Direction, htf: Bias | None) -> None:
    ctx = _ctx(_state(direction=direction), htf=htf)

    assert _check("htf_aligned", ctx) is htf_allows(_row(direction), htf)


def test_htf_aligned_passes_an_unknown_bias_and_blocks_a_range() -> None:
    assert _check("htf_aligned", _ctx(htf=None))
    assert _check("htf_aligned", _ctx(htf="bullish"))
    assert not _check("htf_aligned", _ctx(htf="range"))


# --- valid order block: sweep, displacement FVG, break of structure ------------------------

BULL_SWEEP = frame([FLAT, (100.0, 101.0, 98.0, 100.5), FLAT])  # low 98 < 99; high 101 == 101
BEAR_SWEEP = frame([FLAT, (100.0, 102.0, 99.5, 99.8), FLAT])  # high 102 > 101; low 99.5 > 99
EQUAL_LOW = frame([FLAT, (100.0, 100.5, 99.0, 99.5), FLAT])  # low 99 == 99: not a sweep


@pytest.mark.parametrize(
    ("ohlc", "direction", "swept"),
    [
        (BULL_SWEEP, BULLISH, True),
        (BULL_SWEEP, BEARISH, False),  # an equal high is not a sweep
        (BEAR_SWEEP, BEARISH, True),
        (BEAR_SWEEP, BULLISH, False),
        (EQUAL_LOW, BULLISH, False),
    ],
)
def test_ob_swept_prior_needs_the_block_to_take_the_prior_extreme(
    ohlc: pd.DataFrame, direction: Direction, swept: bool
) -> None:
    ctx = _ctx(_state("OB", direction, formed=1), ohlc=ohlc)

    assert _check("ob_swept_prior", ctx) is swept


@pytest.mark.parametrize("direction", [BULLISH, BEARISH])
def test_ob_swept_prior_is_false_without_a_prior_candle(direction: Direction) -> None:
    ctx = _ctx(_state("OB", direction, formed=0), ohlc=BULL_SWEEP)

    assert not _check("ob_swept_prior", ctx)


def test_ob_swept_prior_reads_the_middle_candle_of_an_fvg() -> None:
    assert _check("ob_swept_prior", _ctx(_state("FVG", BULLISH, formed=1), ohlc=BULL_SWEEP))


BLOCK = (100.0, 100.5, 98.0, 98.5)  # bullish OB candle: 98-100.5
BLOCK_STATE = _state("OB", BULLISH, bottom=98.0, top=100.5, formed=1)
IMPULSE = (98.5, 104.0, 98.4, 103.5)
AWAY = [(104.5, 105.5, 103.0, 105.0), (105.0, 106.0, 104.0, 105.5)]
# The FVG's first candle is the block: its middle candle is formed + 1, gap 100.5-101.
FVG_NEXT = frame([FLAT, BLOCK, IMPULSE, (103.5, 105.0, 101.0, 104.5), *AWAY])
# Three inside candles, then the impulse: the FVG's middle candle is formed + 4.
INSIDE = [(98.5, 100.0, 98.2, 99.5), (99.5, 100.2, 98.6, 99.0), (99.0, 100.0, 98.5, 99.8)]
FVG_LATE = frame(
    [FLAT, BLOCK, *INSIDE, (99.8, 104.0, 99.7, 103.5), (103.5, 105.0, 101.0, 104.5), *AWAY]
)
# The third candle's wick (100.2) re-enters the block (top 100.5): no gap, so no FVG.
NO_GAP = frame([FLAT, BLOCK, IMPULSE, (103.5, 105.0, 100.2, 104.5), *AWAY])


def _fvg_states(ohlc: pd.DataFrame) -> tuple[ZoneState, ...]:
    return tuple(
        ZoneState(zone, prior_touches=0, invalidated=False, status=None, distance_atr=1.0)
        for zone in detect_fvgs(ohlc)
    )


def _displacement(ohlc: pd.DataFrame, params: dict[str, Any] | None = None) -> bool:
    ctx = _ctx(BLOCK_STATE, others=_fvg_states(ohlc), ohlc=ohlc)
    return _check("displacement_fvg", ctx, params)


def test_the_displacement_frames_hold_the_intended_fvgs() -> None:
    assert [zone.formed_index for zone in detect_fvgs(FVG_NEXT)] == [2]
    assert [zone.formed_index for zone in detect_fvgs(FVG_LATE)] == [5]
    assert detect_fvgs(NO_GAP) == []


def test_displacement_fvg_right_after_the_block_passes() -> None:
    assert _displacement(FVG_NEXT)
    assert _displacement(FVG_NEXT, {"within_bars": 1})


def test_displacement_fvg_four_candles_later_needs_a_wider_window() -> None:
    assert not _displacement(FVG_LATE)  # default 3
    assert not _displacement(FVG_LATE, {"within_bars": 3})
    assert _displacement(FVG_LATE, {"within_bars": 4})
    assert _displacement(FVG_LATE, {"within_bars": 5})


def test_displacement_fvg_fails_when_the_third_candle_re_enters_the_block() -> None:
    assert not _displacement(NO_GAP, {"within_bars": 5})


def test_displacement_fvg_needs_a_later_fvg_of_the_same_direction() -> None:
    bear_fvg = _state("FVG", BEARISH, formed=2)
    ob_after = _state("OB", BULLISH, formed=2)
    fvg_on_block = _state("FVG", BULLISH, formed=1)

    for other in (bear_fvg, ob_after, fvg_on_block):
        assert not _check("displacement_fvg", _ctx(BLOCK_STATE, others=(other,)))
    assert _check("displacement_fvg", _ctx(BLOCK_STATE, others=(_state("FVG", formed=2),)))


def test_displacement_fvg_defaults_to_three_bars() -> None:
    assert get("displacement_fvg").params.model_dump() == {"within_bars": 3}


@pytest.mark.parametrize(
    ("direction", "last_bos", "confirmed"),
    [
        (BULLISH, "bullish", True),
        (BULLISH, "bearish", False),
        (BULLISH, None, False),
        (BEARISH, "bearish", True),
        (BEARISH, "bullish", False),
        (BEARISH, None, False),
    ],
)
def test_bos_confirmed_needs_the_last_break_in_the_zone_direction(
    direction: Direction, last_bos: str | None, confirmed: bool
) -> None:
    ctx = _ctx(_state("OB", direction), last_bos=last_bos)

    assert _check("bos_confirmed", ctx) is confirmed


@pytest.mark.parametrize(("drift", "expected"), [(1, "bullish"), (-1, "bearish")])
def test_structure_carries_the_last_break_of_the_scan_frame(drift: int, expected: str) -> None:
    ohlc = zigzag(drift)
    swings = confirmed_swings(ohlc, SWING)
    structure = analyse_structure(ohlc, swings, with_bos=True)
    view = timeframe_view(ohlc, "1h", SWING)  # mtf reports the same break

    assert structure.last_bos == expected
    assert analyse_structure(ohlc, swings).last_bos is None  # only found when asked for
    found = last_break_of_structure(ohlc, swings)
    assert view.last_bos is not None and found is not None
    assert (view.last_bos.direction, view.last_bos.level) == (expected, found.level)
    assert view.last_bos.time == pd.Timestamp(ohlc["time"].iloc[found.index]).isoformat()


def test_structure_has_no_break_without_one() -> None:
    flat = frame([FLAT] * 20)

    assert analyse_structure(flat, confirmed_swings(flat, SWING), with_bos=True).last_bos is None
    assert analyse_structure(flat, [], with_bos=True).last_bos is None
