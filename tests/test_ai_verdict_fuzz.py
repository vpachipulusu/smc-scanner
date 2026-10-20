"""Fuzz `parse_verdict`: whatever the model sends, it never raises and the result is safe."""

import json
import math
import random
import unicodedata
from typing import Any

import pytest

from smc_scanner.ai.verdict import (
    MAX_REASON_CHARS,
    MAX_REASONS,
    MAX_REPLY_CHARS,
    MAX_RISK_REWARD,
    MAX_SUMMARY_CHARS,
    MAX_TARGETS,
    MIN_RISK_REWARD,
    AiVerdict,
    HitFacts,
    parse_verdict,
)

BULL = HitFacts(direction=1, price=100.0, zone_low=98.0, zone_high=100.5, atr=2.0)
BEAR = HitFacts(direction=-1, price=100.0, zone_low=99.5, zone_high=102.0, atr=2.0)
SEEDS = range(8)
ROUNDS_PER_SEED = 150
MIN_TRADE_SHARE = 0.03  # seeded run yields ~6% trades

BIDI = "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"
ZERO_WIDTH = "​‌‍⁠﻿­"
CONTROLS = "\x00\x01\x07\x08\x0b\x0c\x1b\x7f\x85\x9f"
HOSTILE_TEXTS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[click me](javascript:alert(1))",
    "[a](https://evil.example/?q=1) **bold** `code` ```fence```",
    "&lt;b&gt; &amp; <b>",
    f"safe{BIDI}text",
    f"zero{ZERO_WIDTH}width",
    f"ctrl{CONTROLS}chars",
    "line\nbreak\r\nand\ttab sep para",
    "é" * 50 + "\U0001f600" * 50,
    "퟿\U0010ffff",
    "x" * 5000,
    "   ",
    "",
]
WEIRD_NUMBERS: list[Any] = [
    0,
    -1,
    True,
    False,
    None,
    "100",
    "NaN",
    [],
    {},
    1e308,
    -1e308,
    1e-320,
    10**400,
    -(10**400),
    2**63,
    float("nan"),
    float("inf"),
    float("-inf"),
]


def _valid(action: str = "BUY") -> dict[str, Any]:
    if action == "SELL":
        return {
            "action": "SELL",
            "confidence": 70,
            "quality": "B",
            "entry": 100.0,
            "stop": 103.0,
            "targets": [94.0, 90.0],
            "invalidation": 103.5,
            "reasons": ["bearish OB", "trend down"],
            "summary": "Short from the bearish order block.",
        }
    return {
        "action": "BUY",
        "confidence": 80,
        "quality": "A",
        "entry": 100.0,
        "stop": 97.0,
        "targets": [106.0, 110.0],
        "invalidation": 96.5,
        "reasons": ["bullish OB tapped", "trend up"],
        "summary": "Long from the bullish order block.",
    }


def _has_forbidden_char(text: str) -> bool:
    return any(unicodedata.category(ch) in {"Cc", "Cf"} for ch in text)


def _assert_safe_text(verdict: AiVerdict) -> None:
    assert len(verdict.summary) <= MAX_SUMMARY_CHARS
    assert not _has_forbidden_char(verdict.summary)
    assert len(verdict.reasons) <= MAX_REASONS
    for reason in verdict.reasons:
        assert reason
        assert len(reason) <= MAX_REASON_CHARS
        assert not _has_forbidden_char(reason)
    if verdict.downgrade_reason is not None:
        assert len(verdict.downgrade_reason) <= MAX_REASON_CHARS
        assert not _has_forbidden_char(verdict.downgrade_reason)


def _assert_trade_levels(verdict: AiVerdict, facts: HitFacts) -> None:
    assert (facts.direction == 1) == (verdict.action == "BUY")
    sign = 1 if verdict.action == "BUY" else -1
    assert verdict.entry is not None
    assert verdict.stop is not None
    assert verdict.risk_reward is not None
    prices = [verdict.entry, verdict.stop, *verdict.targets]
    if verdict.invalidation is not None:
        prices.append(verdict.invalidation)
    assert all(math.isfinite(p) and p > 0 for p in prices)
    assert sign * (verdict.entry - verdict.stop) > 0
    offsets = [sign * (t - verdict.entry) for t in verdict.targets]
    assert 1 <= len(offsets) <= MAX_TARGETS
    assert all(o > 0 for o in offsets)
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == len(offsets)
    if verdict.invalidation is not None:
        assert sign * (verdict.entry - verdict.invalidation) > 0
    assert MIN_RISK_REWARD <= verdict.risk_reward <= MAX_RISK_REWARD
    expected = offsets[0] / abs(verdict.entry - verdict.stop)
    assert verdict.risk_reward == pytest.approx(expected)


def assert_safe(raw: object, facts: HitFacts) -> AiVerdict:
    """Parse and check every invariant; returns the verdict for case-specific asserts."""
    verdict = parse_verdict(raw, facts)  # type: ignore[arg-type]
    assert isinstance(verdict, AiVerdict)
    _assert_safe_text(verdict)
    assert verdict.downgraded == (verdict.downgrade_reason is not None)
    if verdict.downgraded:
        assert verdict.action == "HOLD"
        assert verdict.downgrade_reason
    if verdict.action == "HOLD":
        assert verdict.entry is None
        assert verdict.stop is None
        assert verdict.risk_reward is None
        assert verdict.targets == ()
    else:
        _assert_trade_levels(verdict, facts)
    assert AiVerdict.model_validate_json(verdict.model_dump_json()) == verdict
    return verdict


def _assert_downgraded(raw: object, facts: HitFacts = BULL) -> AiVerdict:
    verdict = assert_safe(raw, facts)
    assert verdict.action == "HOLD"
    assert verdict.downgraded
    return verdict


# --- structural garbage -------------------------------------------------------------------

MALFORMED_REPLIES: list[Any] = [
    "",
    "   \n\t",
    None,
    123,
    b'{"action": "HOLD"}',
    ["HOLD"],
    "not json at all",
    "{",
    "}",
    '{"action": "BUY",',
    '{"action": "BUY", "confidence": 8',
    '{"action": "BUY" "confidence": 80}',
    "{'action': 'HOLD', 'confidence': 1}",
    '{"action": "HOLD", "confidence": 1}}',
    '{"action": "HOLD", "confidence": 1} trailing',
    '{"action": "HOLD", "confidence": NaN}',
    '{"action": "HOLD", "confidence": Infinity}',
    "[]",
    "[1, 2, 3]",
    "null",
    "true",
    "42",
    '"HOLD"',
    "{}",
    '{"action": null}',
    '{"action": "hold", "confidence": 5}',
    '{"action": "BUY ", "confidence": 5}',
    '{"action": ["BUY"], "confidence": 5}',
    "```json\n```",
    "```json\n{broken\n```",
    "```\n```\n```",
    "\x00" + json.dumps(_valid()),
]


@pytest.mark.parametrize("raw", MALFORMED_REPLIES, ids=repr)
def test_malformed_replies_downgrade_to_hold(raw: object) -> None:
    _assert_downgraded(raw)


def test_every_truncation_of_a_valid_reply_is_safe() -> None:
    text = json.dumps(_valid())
    for cut in range(len(text)):
        verdict = assert_safe(text[:cut], BULL)
        assert verdict.downgraded, cut
    assert not assert_safe(text, BULL).downgraded


@pytest.mark.parametrize("depth", [1, 50, 500, 5_000, 100_000])
@pytest.mark.parametrize("shape", ["array", "object"])
def test_deeply_nested_json_is_downgraded(depth: int, shape: str) -> None:
    opener, closer = ("[", "]") if shape == "array" else ('{"a":', "}")
    raw = opener * depth + ("" if shape == "array" else "1") + closer * depth
    _assert_downgraded(raw)


def test_deep_nesting_inside_a_valid_field_is_downgraded() -> None:
    nested = "[" * 3000 + "]" * 3000
    raw = '{"action": "HOLD", "confidence": 5, "reasons": ' + nested + "}"
    _assert_downgraded(raw)


@pytest.mark.parametrize("size", [MAX_REPLY_CHARS + 1, MAX_REPLY_CHARS * 5, 2_000_000])
def test_oversized_replies_are_rejected(size: int) -> None:
    padded = json.dumps(_valid())[:-1] + " " * size + "}"
    verdict = _assert_downgraded(padded)
    assert "too large" in (verdict.downgrade_reason or "")


def test_reply_at_the_size_limit_is_still_parsed() -> None:
    body = json.dumps(_valid())
    raw = body[:-1] + " " * (MAX_REPLY_CHARS - len(body)) + "}"
    assert len(raw) == MAX_REPLY_CHARS

    assert not assert_safe(raw, BULL).downgraded


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```JSON\n{}\n```", "```\n{}\n```"])
def test_fenced_replies_are_unwrapped(fence: str) -> None:
    raw = fence.replace("{}", json.dumps(_valid()))

    assert not assert_safe(raw, BULL).downgraded


# --- hostile text ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", HOSTILE_TEXTS, ids=repr)
def test_hostile_text_is_cleaned_in_summary_and_reasons(hostile: str) -> None:
    reply = _valid() | {"summary": hostile, "reasons": [hostile, "ok", hostile[:200]]}

    verdict = assert_safe(json.dumps(reply), BULL)

    assert verdict.action in {"BUY", "HOLD"}


@pytest.mark.parametrize("hostile", HOSTILE_TEXTS, ids=repr)
def test_hostile_text_survives_ascii_escaped_and_raw_json(hostile: str) -> None:
    reply = _valid("SELL") | {"summary": hostile, "reasons": [hostile]}
    for ensure_ascii in (True, False):
        assert_safe(json.dumps(reply, ensure_ascii=ensure_ascii), BEAR)


def test_markup_is_kept_verbatim_for_the_renderer_to_escape() -> None:
    reply = _valid() | {"summary": "<script>alert(1)</script>"}

    verdict = assert_safe(json.dumps(reply), BULL)

    assert verdict.summary == "<script>alert(1)</script>"


def test_bidi_zero_width_and_control_chars_are_stripped() -> None:
    reply = _valid() | {
        "summary": f"a{BIDI}b{ZERO_WIDTH}c{CONTROLS}d\ne",
        "reasons": [f"r{BIDI}{ZERO_WIDTH}{CONTROLS}", f"{BIDI}", "keep"],
    }

    verdict = assert_safe(json.dumps(reply), BULL)

    assert verdict.summary == "abc d e"  #  is a line break: becomes a space
    assert verdict.reasons == ("r", "keep")


@pytest.mark.parametrize("count", [MAX_REASONS + 1, 50])
def test_too_many_reasons_are_downgraded(count: int) -> None:
    _assert_downgraded(json.dumps(_valid() | {"reasons": ["r"] * count}))


def test_overlong_reason_and_summary_are_downgraded() -> None:
    _assert_downgraded(json.dumps(_valid() | {"reasons": ["x" * (MAX_REASON_CHARS + 1)]}))
    _assert_downgraded(json.dumps(_valid() | {"summary": "x" * (MAX_SUMMARY_CHARS + 1)}))


@pytest.mark.parametrize(
    ("field", "value"),
    [("summary", 5), ("summary", None), ("reasons", "text"), ("reasons", [1])],
)
def test_non_string_text_fields_are_downgraded(field: str, value: Any) -> None:
    _assert_downgraded(json.dumps(_valid() | {field: value}))


def test_long_hostile_action_keeps_downgrade_text_capped() -> None:
    raw = json.dumps({"action": "BUY" * 500 + "‮", "confidence": 1})

    verdict = _assert_downgraded(raw)

    assert len(verdict.summary) <= MAX_SUMMARY_CHARS


# --- numbers --------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["confidence", "entry", "stop", "invalidation"])
@pytest.mark.parametrize("value", WEIRD_NUMBERS, ids=repr)
def test_weird_scalar_numbers_never_escape(field: str, value: Any) -> None:
    assert_safe(json.dumps(_valid() | {field: value}, allow_nan=True), BULL)


@pytest.mark.parametrize("value", WEIRD_NUMBERS, ids=repr)
def test_weird_target_numbers_never_escape(value: Any) -> None:
    for targets in ([value], [106.0, value], [value, 110.0], [106.0, 110.0, 112.0, value]):
        assert_safe(json.dumps(_valid() | {"targets": targets}, allow_nan=True), BULL)


@pytest.mark.parametrize("flag", ["true", "false"])
@pytest.mark.parametrize("field", ["confidence", "entry", "stop", "invalidation"])
def test_bool_is_not_a_number(field: str, flag: str) -> None:
    raw = json.dumps(_valid() | {field: 0}).replace(f'"{field}": 0', f'"{field}": {flag}')

    verdict = assert_safe(raw, BULL)

    assert verdict.action == "HOLD"
    assert verdict.downgraded


def test_bool_target_is_downgraded() -> None:
    _assert_downgraded('{"action":"BUY","confidence":80,"entry":100,"stop":97,"targets":[true]}')


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
@pytest.mark.parametrize("field", ["confidence", "entry", "stop", "invalidation"])
def test_nan_and_infinity_tokens_are_downgraded(field: str, token: str) -> None:
    raw = json.dumps(_valid() | {field: 1}).replace(f'"{field}": 1', f'"{field}": {token}')

    assert assert_safe(raw, BULL).action == "HOLD"


def test_huge_integers_never_raise() -> None:
    big = "9" * 5000
    for field in ("confidence", "entry", "stop"):
        raw = json.dumps(_valid() | {field: 1}).replace(f'"{field}": 1', f'"{field}": {big}')
        assert_safe(raw, BULL)


def test_extreme_floats_cannot_overflow_risk_reward() -> None:
    reply = _valid() | {"entry": 1e308, "stop": 1e-308, "targets": [1.7e308]}
    assert_safe(json.dumps(reply), BULL)


@pytest.mark.parametrize("confidence", [-0.001, 100.001, -1e-12, 1e9])
def test_out_of_range_confidence_is_downgraded(confidence: float) -> None:
    _assert_downgraded(json.dumps(_valid() | {"confidence": confidence}))


# --- BUY/SELL geometry ----------------------------------------------------------------------

BAD_GEOMETRY_BUY: list[dict[str, Any]] = [
    {"stop": 101.0},
    {"stop": 100.0},
    {"targets": [99.0]},
    {"targets": [110.0, 106.0]},
    {"targets": [106.0, 106.0]},
    {"invalidation": 101.0},
    {"entry": 120.0, "stop": 117.0, "targets": [126.0]},
    {"stop": 99.99},
    {"stop": 80.0},
    {"targets": [200.0]},
    {"targets": [101.0]},
    {"targets": []},
    {"targets": [106.0, 107.0, 108.0, 109.0]},
    {"entry": None},
    {"stop": None},
]


@pytest.mark.parametrize("override", BAD_GEOMETRY_BUY, ids=repr)
def test_bad_buy_geometry_is_downgraded(override: dict[str, Any]) -> None:
    _assert_downgraded(json.dumps(_valid() | override), BULL)


@pytest.mark.parametrize("override", BAD_GEOMETRY_BUY, ids=repr)
def test_buy_geometry_on_a_bearish_hit_is_downgraded(override: dict[str, Any]) -> None:
    _assert_downgraded(json.dumps(_valid() | override), BEAR)


def test_direction_mismatch_is_downgraded_both_ways() -> None:
    _assert_downgraded(json.dumps(_valid("BUY")), BEAR)
    _assert_downgraded(json.dumps(_valid("SELL")), BULL)


def test_valid_replies_pass_for_matching_direction() -> None:
    assert assert_safe(json.dumps(_valid("BUY")), BULL).action == "BUY"
    assert assert_safe(json.dumps(_valid("SELL")), BEAR).action == "SELL"


def test_hold_with_extra_trade_levels_has_them_dropped() -> None:
    verdict = assert_safe(json.dumps(_valid() | {"action": "HOLD"}), BULL)

    assert verdict.action == "HOLD"
    assert not verdict.downgraded


def test_model_supplied_risk_reward_and_downgrade_flags_are_ignored() -> None:
    reply = _valid() | {"risk_reward": 999.0, "downgraded": True, "downgrade_reason": "x"}

    verdict = assert_safe(json.dumps(reply), BULL)

    assert verdict.risk_reward is not None
    assert verdict.risk_reward < MAX_RISK_REWARD
    assert not verdict.downgraded


# --- hit facts ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "facts",
    [
        HitFacts(direction=1, price=float("nan"), zone_low=98.0, zone_high=100.0, atr=2.0),
        HitFacts(direction=1, price=100.0, zone_low=98.0, zone_high=100.0, atr=0.0),
        HitFacts(direction=1, price=100.0, zone_low=98.0, zone_high=100.0, atr=float("inf")),
        HitFacts(direction=1, price=-1.0, zone_low=98.0, zone_high=100.0, atr=2.0),
        HitFacts(direction=1, price=100.0, zone_low=101.0, zone_high=100.0, atr=2.0),
        HitFacts(direction=1, price=100.0, zone_low=0.0, zone_high=100.0, atr=2.0),
        HitFacts(direction=0, price=100.0, zone_low=98.0, zone_high=100.0, atr=2.0),  # type: ignore[arg-type]
        HitFacts(direction=True, price=100.0, zone_low=98.0, zone_high=100.0, atr=2.0),  # type: ignore[arg-type]
    ],
)
def test_unusable_facts_downgrade_even_a_valid_reply(facts: HitFacts) -> None:
    _assert_downgraded(json.dumps(_valid()), facts)


# --- seeded random fuzz ---------------------------------------------------------------------


def _random_value(rng: random.Random) -> Any:
    kind = rng.randrange(6)
    if kind == 0:
        return rng.choice(WEIRD_NUMBERS)
    if kind == 1:
        return rng.choice(HOSTILE_TEXTS)
    if kind == 2:
        return rng.uniform(-1e4, 1e4)
    if kind == 3:
        return [_random_value(rng) for _ in range(rng.randrange(6))]
    if kind == 4:
        return {"k": _random_value(rng)} if rng.random() < 0.5 else {}
    return rng.randrange(-5, 300)


def _mutate(rng: random.Random, reply: dict[str, Any]) -> None:
    key = rng.choice([*reply, "extra", "risk_reward", "downgraded"])
    mutation = rng.randrange(4)
    current = reply.get(key)
    if mutation == 0:
        reply.pop(key, None)
    elif mutation == 1 and isinstance(current, int | float) and not isinstance(current, bool):
        reply[key] = current * rng.choice([0, -1, 0.5, 2, 1e6, 1e-6])
    else:
        reply[key] = _random_value(rng)


def _facts_for(rng: random.Random, raw: str) -> HitFacts:
    """Mostly the facts that match the reply's side, sometimes the opposite ones."""
    matching = BEAR if '"SELL"' in raw else BULL
    return matching if rng.random() < 0.85 else rng.choice([BULL, BEAR])


def _random_reply(rng: random.Random) -> str:
    action = rng.choice(["BUY", "SELL", "BUY", "SELL", "HOLD", "buy", "", "FLAT"])
    reply = _valid("SELL" if action == "SELL" else "BUY")
    reply["action"] = action
    for _ in range(rng.randrange(1, 5)):
        _mutate(rng, reply)
    text = json.dumps(reply, allow_nan=True, ensure_ascii=rng.random() < 0.5)
    roll = rng.random()
    if roll < 0.15:
        text = text[: rng.randrange(len(text))]
    elif roll < 0.25:
        text = f"```json\n{text}\n```"
    elif roll < 0.30:
        text = "".join(rng.choice([c, c, c, "\x00", "{", '"']) for c in text)
    return text


@pytest.mark.parametrize("seed", SEEDS)
def test_random_mutations_never_break_invariants(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(ROUNDS_PER_SEED):
        raw = _random_reply(rng)
        assert_safe(raw, _facts_for(rng, raw))


def _noise(rng: random.Random) -> str:
    ranges = [(0x20, 0x250), (0x2000, 0x2070), (0, 0x20), (0xE000, 0xE100), (0x1F300, 0x1F400)]
    return "".join(chr(rng.randrange(*rng.choice(ranges))) for _ in range(rng.randrange(1, 400)))


@pytest.mark.parametrize("seed", SEEDS)
def test_random_unicode_noise_never_breaks_invariants(seed: int) -> None:
    rng = random.Random(1000 + seed)
    for _ in range(ROUNDS_PER_SEED):
        noise = _noise(rng)
        reply = _valid() | {"summary": noise[:MAX_SUMMARY_CHARS], "reasons": [noise[:50]]}
        assert_safe(json.dumps(reply, ensure_ascii=rng.random() < 0.5), BULL)


@pytest.mark.parametrize("seed", SEEDS)
def test_random_garbage_text_is_downgraded(seed: int) -> None:
    rng = random.Random(2000 + seed)
    for _ in range(ROUNDS_PER_SEED):
        raw = "".join(chr(rng.randrange(0, 0x3000)) for _ in range(rng.randrange(0, 300)))
        assert assert_safe(raw, BULL).action == "HOLD"


# --- sanity: the fuzz is not vacuous ----------------------------------------------------------


@pytest.mark.parametrize(("action", "facts"), [("BUY", BULL), ("SELL", BEAR)], ids=["buy", "sell"])
def test_unmutated_valid_reply_yields_a_trade(action: str, facts: HitFacts) -> None:
    verdict = assert_safe(json.dumps(_valid(action)), facts)

    assert verdict.action == action
    assert not verdict.downgraded


def test_a_fair_share_of_random_mutations_still_parse_as_trades() -> None:
    trades = total = 0
    for seed in SEEDS:
        rng = random.Random(seed)
        for _ in range(ROUNDS_PER_SEED):
            raw = _random_reply(rng)
            verdict = assert_safe(raw, _facts_for(rng, raw))
            total += 1
            trades += verdict.action != "HOLD"
    assert trades / total >= MIN_TRADE_SHARE, (trades, total)
