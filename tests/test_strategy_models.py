"""Strategy models: bounds, allowlists, cross-field rules and the ScanOptions mapping."""

import json
import math
from typing import Any

import pytest
from pydantic import ValidationError

from smc_scanner.config import MAX_NEAR_ATR, MAX_SWING_LENGTH
from smc_scanner.scanner import ScanOptions
from smc_scanner.strategy import (
    CONDITION_KEY_PATTERN,
    DEFAULT_STRATEGY_SLUG,
    MAX_CONDITIONS,
    MAX_STRATEGY_DESCRIPTION_CHARS,
    MAX_STRATEGY_NAME_CHARS,
    SLUG_PATTERN,
    ConditionRef,
    Strategy,
)


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "ob-pullback",
        "name": "OB pullback",
        "description": "Order blocks, aligned with bias.",
        "zone_kinds": ("OB",),
        "swing_length": 10,
        "near_atr": 0.5,
        "require": (ConditionRef(key="fresh"),),
        "score": (ConditionRef(key="ote"), ConditionRef(key="trendline")),
        "min_score": 1,
        "statuses": ("TOUCHING", "NEAR"),
    }
    return {**base, **overrides}


def _strategy(**overrides: Any) -> Strategy:
    return Strategy(**_fields(**overrides))


def test_valid_strategy_has_the_defaults_for_the_optional_fields() -> None:
    strategy = _strategy()

    assert strategy.slug == "ob-pullback"
    assert strategy.mtf is False
    assert strategy.require_htf_aligned is False
    assert strategy.builtin is False


def test_condition_ref_params_default_to_an_empty_dict_per_instance() -> None:
    first = ConditionRef(key="fresh")
    second = ConditionRef(key="fresh")

    assert first.params == {}
    assert first.params is not second.params


def test_default_slug_matches_the_slug_pattern() -> None:
    assert SLUG_PATTERN.fullmatch(DEFAULT_STRATEGY_SLUG)
    assert _strategy(slug=DEFAULT_STRATEGY_SLUG).slug == DEFAULT_STRATEGY_SLUG


def test_json_round_trip_through_model_dump_and_validate() -> None:
    params: dict[str, int | float | str | bool] = {"ratio": 2.5, "tag": "x", "on": True, "n": 3}
    strategy = _strategy(
        mtf=True, require_htf_aligned=True, require=(ConditionRef(key="min_rr", params=params),)
    )

    from_python = Strategy.model_validate(strategy.model_dump())
    from_json = Strategy.model_validate(strategy.model_dump(mode="json"))
    from_text = Strategy.model_validate_json(strategy.model_dump_json())

    assert from_python == strategy
    assert from_json == strategy
    assert from_text == strategy


def test_params_keep_their_types_through_json() -> None:
    ref = ConditionRef(key="k", params={"i": 1, "f": 1.5, "s": "a", "b": True})

    restored = ConditionRef.model_validate_json(ref.model_dump_json())

    assert [type(v) for v in restored.params.values()] == [int, float, str, bool]


@pytest.mark.parametrize("key", ["fresh", "a", "ote_2", "a" * 32])
def test_condition_key_accepts_the_allowed_shapes(key: str) -> None:
    assert ConditionRef(key=key).key == key


@pytest.mark.parametrize(
    "key", ["", "Fresh", "1fresh", "_fresh", "fresh-x", "fresh x", "a" * 33, "fresh\n", "frésh"]
)
def test_condition_key_rejects_bad_shapes(key: str) -> None:
    with pytest.raises(ValidationError, match="key"):
        ConditionRef(key=key)


def test_condition_ref_allows_eight_params_and_rejects_nine() -> None:
    ConditionRef(key="k", params={f"p{i}": i for i in range(8)})

    with pytest.raises(ValidationError, match="params"):
        ConditionRef(key="k", params={f"p{i}": i for i in range(9)})


def test_condition_param_string_value_is_capped_at_32_chars() -> None:
    ConditionRef(key="k", params={"s": "x" * 32})

    with pytest.raises(ValidationError, match="32"):
        ConditionRef(key="k", params={"s": "x" * 33})


@pytest.mark.parametrize("name", ["", "Bad", "1p", "p-1", "p" * 33, "p q"])
def test_condition_param_names_follow_the_key_shape(name: str) -> None:
    with pytest.raises(ValidationError, match="params"):
        ConditionRef(key="k", params={name: 1})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_condition_param_floats_must_be_finite(value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        ConditionRef(key="k", params={"x": value})


@pytest.mark.parametrize("value", [10**400, 10**9 + 1, -(10**9) - 1, 1e308, -1.5e9])
def test_condition_param_numbers_are_bounded_in_magnitude(value: float) -> None:
    with pytest.raises(ValidationError, match="within"):
        ConditionRef(key="k", params={"x": value})


def test_condition_param_numbers_at_the_magnitude_bound_are_accepted() -> None:
    ref = ConditionRef(key="k", params={"i": 10**9, "f": -1e9})

    assert ref.params == {"i": 10**9, "f": -1e9}


@pytest.mark.parametrize("value", ["a b", "x\n", "\x00", "<b>", "a;b", "‮", "é"])
def test_condition_param_strings_are_allowlisted(value: str) -> None:
    with pytest.raises(ValidationError, match="may only contain"):
        ConditionRef(key="k", params={"s": value})


@pytest.mark.parametrize("value", ["", "h1", "close.mid", "a_b-c"])
def test_condition_param_strings_accept_the_allowlist(value: str) -> None:
    assert ConditionRef(key="k", params={"s": value}).params["s"] == value


@pytest.mark.parametrize("value", [None, [1], {"a": 1}])
def test_condition_param_rejects_null_and_nested_values(value: Any) -> None:
    with pytest.raises(ValidationError):
        ConditionRef.model_validate({"key": "k", "params": {"x": value}})


def test_condition_param_numeric_strings_stay_strings_through_json() -> None:
    ref = ConditionRef.model_validate_json('{"key": "k", "params": {"s": "1", "f": 1.0}}')

    assert ref.params == {"s": "1", "f": 1.0}
    assert type(ref.params["s"]) is str
    assert type(ref.params["f"]) is float


def test_condition_ref_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ConditionRef(key="k", weight=2)  # type: ignore[call-arg]


def test_condition_ref_is_frozen() -> None:
    ref = ConditionRef(key="fresh")

    with pytest.raises(ValidationError, match="frozen"):
        ref.key = "other"


@pytest.mark.parametrize("slug", ["a", "smc-default", "0abc", "a" * 32])
def test_slug_accepts_the_allowed_shapes(slug: str) -> None:
    assert _strategy(slug=slug).slug == slug


@pytest.mark.parametrize(
    "slug", ["", "-abc", "Abc", "a_b", "a b", "a" * 33, "abc\n", "../x", "ab/c", "ünï"]
)
def test_slug_rejects_bad_shapes(slug: str) -> None:
    with pytest.raises(ValidationError, match="slug"):
        _strategy(slug=slug)


def test_patterns_do_not_match_a_trailing_newline() -> None:
    assert SLUG_PATTERN.match("abc\n") is None
    assert CONDITION_KEY_PATTERN.match("abc\n") is None


def test_name_is_stripped_before_it_is_checked() -> None:
    assert _strategy(name="  Trend pullback \n").name == "Trend pullback"


def test_name_length_bounds() -> None:
    assert _strategy(name="n" * MAX_STRATEGY_NAME_CHARS).name == "n" * MAX_STRATEGY_NAME_CHARS

    with pytest.raises(ValidationError, match="name"):
        _strategy(name="n" * (MAX_STRATEGY_NAME_CHARS + 1))
    with pytest.raises(ValidationError, match="name"):
        _strategy(name="   ")


def test_name_accepts_the_full_allowlist() -> None:
    name = "Ab 09 .,%()/&'-"

    assert _strategy(name=name).name == name


@pytest.mark.parametrize("name", ["<b>x</b>", "a;b", "a\nb", "a\tb", "a_b", "é", "a`b", "a\x00b"])
def test_name_rejects_characters_outside_the_allowlist(name: str) -> None:
    with pytest.raises(ValidationError, match="name"):
        _strategy(name=name)


@pytest.mark.parametrize("name", ["...", "'''---", "( )"])
def test_name_needs_at_least_one_letter_or_digit(name: str) -> None:
    with pytest.raises(ValidationError, match="letter or digit"):
        _strategy(name=name)


def test_stripped_name_round_trips_unchanged() -> None:
    strategy = _strategy(name="  Trend  ")

    assert Strategy.model_validate_json(strategy.model_dump_json()).name == "Trend"


def test_description_may_be_empty_and_is_stripped() -> None:
    assert _strategy(description="").description == ""
    assert _strategy(description="  hi  ").description == "hi"


def test_description_length_bounds() -> None:
    text = "d" * MAX_STRATEGY_DESCRIPTION_CHARS
    assert _strategy(description=text).description == text

    with pytest.raises(ValidationError, match="description"):
        _strategy(description=text + "d")


@pytest.mark.parametrize("text", ["ignore previous; do x", "line\nbreak", "<script>", "{x}", "é"])
def test_description_rejects_characters_outside_the_allowlist(text: str) -> None:
    with pytest.raises(ValidationError, match="description"):
        _strategy(description=text)


@pytest.mark.parametrize("kinds", [("FVG",), ("OB",), ("FVG", "OB"), ("OB", "FVG")])
def test_zone_kinds_accepts_any_non_empty_subset(kinds: tuple[str, ...]) -> None:
    assert _strategy(zone_kinds=kinds).zone_kinds == kinds


@pytest.mark.parametrize("kinds", [(), ("BOS",), ("fvg",), ("OB", "OB"), ("FVG", "OB", "FVG")])
def test_zone_kinds_rejects_empty_unknown_and_duplicates(kinds: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="zone_kinds"):
        _strategy(zone_kinds=kinds)


@pytest.mark.parametrize("statuses", [("TOUCHING",), ("NEAR",), ("TOUCHING", "NEAR")])
def test_statuses_accepts_any_non_empty_subset(statuses: tuple[str, ...]) -> None:
    assert _strategy(statuses=statuses).statuses == statuses


@pytest.mark.parametrize("statuses", [(), ("FAR",), ("near",), ("NEAR", "NEAR")])
def test_statuses_rejects_empty_unknown_and_duplicates(statuses: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="statuses"):
        _strategy(statuses=statuses)


@pytest.mark.parametrize("swing", [1, 10, MAX_SWING_LENGTH])
def test_swing_length_accepts_the_bounds(swing: int) -> None:
    assert _strategy(swing_length=swing).swing_length == swing


@pytest.mark.parametrize("swing", [0, -1, MAX_SWING_LENGTH + 1, 2.5, "5", True])
def test_swing_length_rejects_out_of_range_and_non_integers(swing: Any) -> None:
    with pytest.raises(ValidationError, match="swing_length"):
        _strategy(swing_length=swing)


@pytest.mark.parametrize("near", [0, 0.0, 0.5, MAX_NEAR_ATR])
def test_near_atr_accepts_the_bounds(near: float) -> None:
    assert _strategy(near_atr=near).near_atr == near


@pytest.mark.parametrize(
    "near", [-0.01, MAX_NEAR_ATR + 0.01, math.nan, math.inf, -math.inf, "1", True]
)
def test_near_atr_rejects_out_of_range_and_non_finite(near: Any) -> None:
    with pytest.raises(ValidationError, match="near_atr"):
        _strategy(near_atr=near)


def test_oversized_enum_lists_are_rejected_by_length() -> None:
    with pytest.raises(ValidationError, match="zone_kinds"):
        _strategy(zone_kinds=("OB",) * 10_000)
    with pytest.raises(ValidationError, match="statuses"):
        _strategy(statuses=("NEAR",) * 10_000)


@pytest.mark.parametrize(
    ("field", "value"),
    [("swing_length", 10.0), ("swing_length", "10"), ("near_atr", "1"), ("min_score", True)],
)
def test_scalar_fields_are_strict_in_json_mode(field: str, value: Any) -> None:
    payload = _strategy().model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        Strategy.model_validate_json(json.dumps(payload))


def test_strategy_without_any_conditions_is_valid() -> None:
    strategy = _strategy(require=(), score=(), min_score=0)

    assert strategy.condition_keys() == ()
    assert strategy.to_scan_options().all_touches is True


def test_condition_lists_are_capped_at_twelve_each() -> None:
    twelve = tuple(ConditionRef(key=f"c{i}") for i in range(MAX_CONDITIONS))
    others = tuple(ConditionRef(key=f"d{i}") for i in range(MAX_CONDITIONS))

    strategy = _strategy(require=twelve, score=others, min_score=0)
    assert len(strategy.condition_keys()) == 2 * MAX_CONDITIONS

    with pytest.raises(ValidationError, match="require"):
        _strategy(require=(*twelve, ConditionRef(key="extra")))
    with pytest.raises(ValidationError, match="score"):
        _strategy(score=(*others, ConditionRef(key="extra")), min_score=0)


def test_duplicate_key_within_require_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate condition key: fresh"):
        _strategy(require=(ConditionRef(key="fresh"), ConditionRef(key="fresh")))


def test_duplicate_key_across_require_and_score_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate condition key: ote"):
        _strategy(require=(ConditionRef(key="ote"),), score=(ConditionRef(key="ote"),))


def test_min_score_is_bounded_by_the_score_list() -> None:
    assert _strategy(min_score=0).min_score == 0
    assert _strategy(min_score=2).min_score == 2

    with pytest.raises(ValidationError, match="min_score"):
        _strategy(min_score=3)
    with pytest.raises(ValidationError, match="min_score"):
        _strategy(min_score=-1)


def test_min_score_must_be_zero_without_score_conditions() -> None:
    assert _strategy(score=(), min_score=0).min_score == 0

    with pytest.raises(ValidationError, match="min_score"):
        _strategy(score=(), min_score=1)


def test_require_htf_aligned_needs_mtf() -> None:
    assert _strategy(mtf=True, require_htf_aligned=True).require_htf_aligned is True

    with pytest.raises(ValidationError, match="require_htf_aligned requires mtf"):
        _strategy(mtf=False, require_htf_aligned=True)


def test_mtf_alone_is_valid() -> None:
    strategy = _strategy(mtf=True)

    assert strategy.mtf is True
    assert strategy.require_htf_aligned is False


def test_condition_keys_lists_require_then_score_in_order() -> None:
    strategy = _strategy(
        require=(ConditionRef(key="b"), ConditionRef(key="a")),
        score=(ConditionRef(key="d"), ConditionRef(key="c")),
    )

    assert strategy.condition_keys() == ("b", "a", "d", "c")


def test_to_scan_options_without_fresh_collects_all_touches() -> None:
    strategy = _strategy(swing_length=7, near_atr=1.25, require=(ConditionRef(key="bias"),))

    options = strategy.to_scan_options()

    assert options == ScanOptions(swing_length=7, near_atr=1.25, all_touches=True)


def test_to_scan_options_with_fresh_required_keeps_only_first_touches() -> None:
    options = _strategy(require=(ConditionRef(key="fresh"),)).to_scan_options()

    assert options.all_touches is False


def test_fresh_as_a_scoring_condition_does_not_restrict_touches() -> None:
    strategy = _strategy(require=(), score=(ConditionRef(key="fresh"),), min_score=0)

    assert strategy.to_scan_options().all_touches is True


def test_strategy_is_frozen() -> None:
    strategy = _strategy()

    with pytest.raises(ValidationError, match="frozen"):
        strategy.slug = "other"


def test_strategy_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        _strategy(owner="me")


def test_strategy_rejects_missing_required_fields() -> None:
    fields = _fields()
    del fields["slug"]

    with pytest.raises(ValidationError, match="slug"):
        Strategy(**fields)


def test_builtin_flag_round_trips() -> None:
    strategy = _strategy(builtin=True)

    assert Strategy.model_validate(strategy.model_dump()).builtin is True
