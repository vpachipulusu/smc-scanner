"""Condition registry: listing, lookup, parameter validation and every built-in condition."""

from dataclasses import replace
from typing import Any

import pytest
from conftest import FLAT, frame

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
from smc_scanner.mtf import htf_allows
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
    **structure: Any,
) -> ZoneContext:
    zone_state = state or _state()
    return ZoneContext(
        state=zone_state,
        structure=replace(_BASE, **structure),
        valid=(zone_state, *others),
        ohlc=OHLC,
        last_index=LAST,
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
    ]


def test_listing_carries_labels_and_param_schemas() -> None:
    listed = {info.key: info for info in conditions()}

    assert all(info.label for info in listed.values())
    bars = listed["max_zone_age"].params_schema["properties"]["bars"]
    assert (bars["minimum"], bars["maximum"]) == (1, MAX_BARS)
    assert listed["max_zone_age"].params_schema["required"] == ["bars"]
    assert listed["aligned"].params_schema.get("properties", {}) == {}
    assert listed["zone_kind"].params_schema["properties"]["kind"]["enum"] == ["FVG", "OB"]


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
