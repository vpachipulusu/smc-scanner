"""AI verdict parsing and sanity checks: untrusted model output never crashes, only downgrades."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from smc_scanner.ai import prompt
from smc_scanner.ai.verdict import (
    MAX_REASON_CHARS,
    MAX_REASONS,
    MAX_REPLY_CHARS,
    MAX_SUMMARY_CHARS,
    AiVerdict,
    HitFacts,
    parse_verdict,
)

BULL = HitFacts(direction=1, price=100.0, zone_low=98.0, zone_high=100.5, atr=2.0)
BEAR = HitFacts(direction=-1, price=100.0, zone_low=99.5, zone_high=102.0, atr=2.0)


def _buy(**overrides: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {
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
    return {**reply, **overrides}


def _sell(**overrides: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "action": "SELL",
        "confidence": 70,
        "quality": "B",
        "entry": 100.0,
        "stop": 103.0,
        "targets": [94.0],
        "invalidation": None,
        "reasons": ["bearish FVG"],
        "summary": "Short from the bearish gap.",
    }
    return {**reply, **overrides}


def _assert_hold(verdict: AiVerdict, reason: str) -> None:
    assert verdict.action == "HOLD"
    assert verdict.downgraded is True
    assert verdict.downgrade_reason == reason
    assert verdict.confidence == 0
    assert verdict.risk_reward is None
    assert verdict.targets == ()
    assert verdict.entry is None
    assert verdict.stop is None
    assert verdict.invalidation is None


def _assert_schema_hold(verdict: AiVerdict, field: str) -> None:
    assert verdict.action == "HOLD"
    assert verdict.downgraded is True
    assert verdict.downgrade_reason is not None
    assert verdict.downgrade_reason.startswith(f"schema violation in {field}:")


def test_valid_buy_parses_and_computes_risk_reward() -> None:
    verdict = parse_verdict(json.dumps(_buy()), BULL)

    assert verdict.action == "BUY"
    assert verdict.downgraded is False
    assert verdict.downgrade_reason is None
    assert verdict.entry == 100.0
    assert verdict.stop == 97.0
    assert verdict.targets == (106.0, 110.0)
    assert verdict.risk_reward == pytest.approx(2.0)
    assert verdict.quality == "A"
    assert verdict.invalidation == 96.5
    assert verdict.reasons == ("bullish OB tapped", "trend up")
    assert verdict.schema_version == 1


def test_valid_sell_parses_and_computes_risk_reward() -> None:
    verdict = parse_verdict(json.dumps(_sell()), BEAR)

    assert verdict.action == "SELL"
    assert verdict.downgraded is False
    assert verdict.risk_reward == pytest.approx(2.0)


def test_risk_reward_from_model_is_ignored() -> None:
    verdict = parse_verdict(json.dumps(_buy(risk_reward=99, riskReward=99)), BULL)

    assert verdict.risk_reward == pytest.approx(2.0)


def test_unknown_fields_are_ignored() -> None:
    verdict = parse_verdict(json.dumps(_buy(extra="x", nested={"a": 1})), BULL)

    assert verdict.action == "BUY"
    assert verdict.downgraded is False


def test_hold_reply_is_not_a_downgrade() -> None:
    reply = {"action": "HOLD", "confidence": 30, "reasons": ["weak"], "summary": "Wait."}
    verdict = parse_verdict(json.dumps(reply), BULL)

    assert verdict.action == "HOLD"
    assert verdict.downgraded is False
    assert verdict.confidence == 30
    assert verdict.risk_reward is None


def test_hold_reply_with_garbage_levels_carries_no_levels() -> None:
    reply = {
        "action": "HOLD",
        "confidence": 30,
        "entry": float("nan"),
        "stop": -5.0,
        "targets": [float("inf"), -1.0],
        "invalidation": 0.0,
    }
    verdict = parse_verdict(json.dumps(reply), BULL)

    assert verdict.action == "HOLD"
    assert verdict.downgraded is False
    assert (verdict.entry, verdict.stop, verdict.invalidation) == (None, None, None)
    assert verdict.targets == ()
    assert verdict.risk_reward is None


@pytest.mark.parametrize(
    "template",
    ["```json\nBODY\n```", "```\nBODY\n```", "  ```JSON\nBODY\n```  \n"],
)
def test_markdown_fences_are_stripped(template: str) -> None:
    verdict = parse_verdict(template.replace("BODY", json.dumps(_buy())), BULL)

    assert verdict.action == "BUY"
    assert verdict.downgraded is False


def test_json_surrounded_by_prose_is_not_accepted() -> None:
    verdict = parse_verdict("Sure! " + json.dumps(_buy()), BULL)

    _assert_hold(verdict, "reply is not valid JSON")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        pytest.param("", "empty or non-text reply", id="empty"),
        pytest.param("   \n ", "empty or non-text reply", id="whitespace"),
        pytest.param("{not json", "reply is not valid JSON", id="malformed"),
        pytest.param("[1, 2]", "reply is not a JSON object", id="array-not-object"),
        pytest.param("null", "reply is not a JSON object", id="null"),
        pytest.param('"BUY"', "reply is not a JSON object", id="string"),
        pytest.param(
            "x" * (MAX_REPLY_CHARS + 1), f"reply too large (>{MAX_REPLY_CHARS} chars)", id="huge"
        ),
        pytest.param("{" * 50_000, f"reply too large (>{MAX_REPLY_CHARS} chars)", id="nested-huge"),
        pytest.param("[" * 5_000, "reply is not valid JSON", id="deeply-nested"),
    ],
)
def test_unparseable_replies_downgrade(raw: str, reason: str) -> None:
    _assert_hold(parse_verdict(raw, BULL), reason)


def test_non_string_reply_downgrades_without_raising() -> None:
    _assert_hold(parse_verdict(None, BULL), "empty or non-text reply")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("facts", "reply", "reason"),
    [
        pytest.param(BULL, _buy(stop=100.0), "stop on the wrong side of entry", id="buy-stop-eq"),
        pytest.param(BULL, _buy(stop=101.0), "stop on the wrong side of entry", id="buy-stop-up"),
        pytest.param(BEAR, _sell(stop=100.0), "stop on the wrong side of entry", id="sell-stop-eq"),
        pytest.param(BEAR, _sell(stop=99.0), "stop on the wrong side of entry", id="sell-stop-dn"),
        pytest.param(
            BULL, _buy(targets=[99.0]), "target on the wrong side of entry", id="buy-target-below"
        ),
        pytest.param(
            BULL,
            _buy(targets=[106.0, 99.0]),
            "target on the wrong side of entry",
            id="buy-second-target-wrong",
        ),
        pytest.param(
            BEAR, _sell(targets=[101.0]), "target on the wrong side of entry", id="sell-target-up"
        ),
        pytest.param(
            BULL, _buy(targets=[110.0, 106.0]), "targets not ordered nearest-first", id="unordered"
        ),
        pytest.param(
            BULL, _buy(targets=[106.0, 106.0]), "targets not ordered nearest-first", id="duplicate"
        ),
        pytest.param(BULL, _buy(targets=[]), "needs at least one target", id="buy-no-targets"),
        pytest.param(BULL, _buy(entry=None), "missing entry", id="buy-missing-entry"),
        pytest.param(BULL, _buy(stop=None), "missing stop", id="buy-missing-stop"),
        pytest.param(
            BULL,
            _buy(entry=-5.0, stop=-6.0, targets=[-1.0]),
            "non-finite or non-positive price in entry",
            id="negative",
        ),
        pytest.param(
            BULL, _buy(stop=0.0), "non-finite or non-positive price in stop", id="zero-stop"
        ),
        pytest.param(
            BULL,
            _buy(invalidation=-1.0),
            "non-finite or non-positive price in invalidation",
            id="negative-invalidation",
        ),
        pytest.param(
            BULL,
            _buy(entry=float("nan")),
            "non-finite or non-positive price in entry",
            id="nan-entry",
        ),
        pytest.param(
            BULL,
            _buy(targets=[float("inf")]),
            "non-finite or non-positive price in target 1",
            id="inf-target",
        ),
        pytest.param(
            BULL,
            _buy(stop=float("-inf")),
            "non-finite or non-positive price in stop",
            id="neg-inf-stop",
        ),
        pytest.param(
            BULL, _buy(invalidation=101.0), "invalidation on the wrong side of entry", id="inv-buy"
        ),
        pytest.param(
            BEAR, _sell(invalidation=99.0), "invalidation on the wrong side of entry", id="inv-sell"
        ),
        pytest.param(BULL, _buy(stop=99.9), "stop distance outside 0.1-5.0 ATR", id="stop-tight"),
        pytest.param(BULL, _buy(stop=85.0), "stop distance outside 0.1-5.0 ATR", id="stop-wide"),
        pytest.param(
            BULL, _buy(targets=[140.0]), "target distance above 15.0 ATR", id="target-too-far"
        ),
        pytest.param(
            BULL, _buy(targets=[101.0]), "risk/reward outside 1.0-20.0", id="risk-reward-low"
        ),
        pytest.param(
            BULL,
            _buy(stop=99.5, targets=[111.0], invalidation=None),
            "risk/reward outside 1.0-20.0",
            id="risk-reward-high",
        ),
        pytest.param(
            BULL,
            _buy(entry=104.0),
            "entry more than 1.5 ATR from the zone",
            id="entry-too-far-above-zone",
        ),
        pytest.param(
            BULL,
            _buy(entry=90.0, stop=89.0, targets=[95.0], invalidation=None),
            "entry more than 1.5 ATR from the zone",
            id="entry-far-below",
        ),
        pytest.param(
            BEAR,
            _sell(entry=105.5, stop=106.0, targets=[90.0]),
            "entry more than 1.5 ATR from the zone",
            id="sell-entry-far",
        ),
        pytest.param(BULL, _buy(confidence=101), "confidence outside 0-100", id="conf-over"),
        pytest.param(BULL, _buy(confidence=-1), "confidence outside 0-100", id="conf-under"),
        pytest.param(
            BULL, _buy(confidence=float("nan")), "confidence outside 0-100", id="conf-nan"
        ),
        pytest.param(BULL, _sell(), "SELL contradicts hit direction 1", id="sell-on-bullish"),
        pytest.param(BEAR, _buy(), "BUY contradicts hit direction -1", id="buy-on-bearish"),
    ],
)
def test_bad_replies_downgrade_to_hold(facts: HitFacts, reply: dict[str, Any], reason: str) -> None:
    raw = json.dumps(reply)  # emits NaN/Infinity tokens, which json.loads accepts
    _assert_hold(parse_verdict(raw, facts), reason)


@pytest.mark.parametrize(
    ("reply", "field"),
    [
        pytest.param(_buy(action="LONG"), "action", id="unknown-action"),
        pytest.param(_buy(action=None), "action", id="null-action"),
        pytest.param({"confidence": 50}, "action", id="missing-action"),
        pytest.param(_buy(quality="Z"), "quality", id="unknown-quality"),
        pytest.param(_buy(confidence="high"), "confidence", id="confidence-string"),
        pytest.param(_buy(confidence=True), "confidence", id="confidence-bool"),
        pytest.param(_buy(confidence=10**400), "confidence", id="confidence-huge-int"),
        pytest.param(_buy(entry="100"), "entry", id="entry-string"),
        pytest.param(_buy(entry=True), "entry", id="entry-bool"),
        pytest.param(_buy(stop=False), "stop", id="stop-bool"),
        pytest.param(_buy(targets=[True]), "targets.0", id="target-bool"),
        pytest.param(_buy(targets=[10**400]), "targets.0", id="target-huge-int"),
        pytest.param(_buy(targets=[1.0, 2.0, 3.0, 4.0]), "targets", id="too-many-targets"),
        pytest.param(_buy(reasons=[1, 2]), "reasons.0", id="reasons-not-strings"),
        pytest.param(_buy(reasons=["r"] * (MAX_REASONS + 1)), "reasons", id="too-many-reasons"),
        pytest.param(_buy(reasons=["r" * (MAX_REASON_CHARS + 1)]), "reasons.0", id="long-reason"),
        pytest.param(_buy(summary="s" * (MAX_SUMMARY_CHARS + 1)), "summary", id="long-summary"),
        pytest.param(
            {"action": "HOLD", "confidence": 1, "entry": "abc"}, "entry", id="hold-string-level"
        ),
    ],
)
def test_schema_violations_downgrade(reply: dict[str, Any], field: str) -> None:
    _assert_schema_hold(parse_verdict(json.dumps(reply), BULL), field)


@pytest.mark.parametrize(
    "facts",
    [
        HitFacts(direction=1, price=100.0, zone_low=98.0, zone_high=100.5, atr=0.0),
        HitFacts(direction=1, price=100.0, zone_low=98.0, zone_high=100.5, atr=float("nan")),
        HitFacts(direction=1, price=float("inf"), zone_low=98.0, zone_high=100.5, atr=2.0),
        HitFacts(direction=1, price=0.0, zone_low=98.0, zone_high=100.5, atr=2.0),
        HitFacts(direction=1, price=100.0, zone_low=101.0, zone_high=99.0, atr=2.0),
        HitFacts(direction=0, price=100.0, zone_low=98.0, zone_high=100.5, atr=2.0),  # type: ignore[arg-type]
        HitFacts(direction=True, price=100.0, zone_low=98.0, zone_high=100.5, atr=2.0),  # type: ignore[arg-type]
    ],
)
def test_unusable_hit_facts_downgrade(facts: HitFacts) -> None:
    _assert_hold(parse_verdict(json.dumps(_buy()), facts), "unusable hit facts")


def test_entry_inside_wide_zone_is_accepted_even_when_price_is_outside() -> None:
    facts = HitFacts(direction=1, price=97.0, zone_low=98.0, zone_high=110.0, atr=2.0)
    reply = _buy(entry=104.0, stop=100.0, targets=[112.0], invalidation=None)

    verdict = parse_verdict(json.dumps(reply), facts)

    assert verdict.downgraded is False
    assert verdict.entry == 104.0


def test_entry_distance_is_measured_to_the_zone_interval() -> None:
    facts = HitFacts(direction=1, price=97.0, zone_low=98.0, zone_high=110.0, atr=2.0)
    at_limit = _buy(entry=113.0, stop=109.0, targets=[121.0], invalidation=None)
    past_limit = _buy(entry=113.1, stop=109.0, targets=[121.0], invalidation=None)
    below_limit = _buy(entry=95.0, stop=92.0, targets=[101.0], invalidation=None)
    below_past = _buy(entry=94.9, stop=92.0, targets=[101.0], invalidation=None)

    assert parse_verdict(json.dumps(at_limit), facts).downgraded is False
    assert parse_verdict(json.dumps(below_limit), facts).downgraded is False
    reason = "entry more than 1.5 ATR from the zone"
    _assert_hold(parse_verdict(json.dumps(past_limit), facts), reason)
    _assert_hold(parse_verdict(json.dumps(below_past), facts), reason)


def test_text_fields_are_sanitised() -> None:
    reply = _buy(
        reasons=["line1\nline2", "a‮b​c\x1bd", "   ", "tab\there"],
        summary="x⁦y﻿z\r\nw",
    )
    verdict = parse_verdict(json.dumps(reply), BULL)

    assert verdict.downgraded is False
    assert verdict.reasons == ("line1 line2", "abcd", "tab here")
    assert verdict.summary == "xyz w"


def test_text_at_the_caps_is_kept() -> None:
    reply = _buy(reasons=["r" * MAX_REASON_CHARS] * MAX_REASONS, summary="s" * MAX_SUMMARY_CHARS)
    verdict = parse_verdict(json.dumps(reply), BULL)

    assert verdict.downgraded is False
    assert len(verdict.reasons) == MAX_REASONS
    assert len(verdict.summary) == MAX_SUMMARY_CHARS


def test_missing_optional_text_defaults_to_empty() -> None:
    verdict = parse_verdict(json.dumps({"action": "HOLD", "confidence": 10}), BULL)

    assert verdict.reasons == ()
    assert verdict.summary == ""
    assert verdict.downgraded is False


_TRADE: dict[str, Any] = {
    "action": "BUY",
    "confidence": 50.0,
    "entry": 100.0,
    "stop": 97.0,
    "targets": (106.0,),
    "risk_reward": 2.0,
}


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"entry": None}, id="trade-needs-entry"),
        pytest.param({"stop": None}, id="trade-needs-stop"),
        pytest.param({"targets": ()}, id="trade-needs-targets"),
        pytest.param({"risk_reward": None}, id="trade-needs-risk-reward"),
        pytest.param({"entry": float("nan")}, id="nan-entry"),
        pytest.param({"confidence": float("nan")}, id="nan-confidence"),
        pytest.param({"action": "HOLD"}, id="hold-with-levels"),
        pytest.param({"downgraded": True}, id="downgraded-needs-reason"),
        pytest.param({"downgrade_reason": "why"}, id="reason-needs-downgraded"),
        pytest.param(
            {"downgraded": True, "downgrade_reason": "r" * (MAX_REASON_CHARS + 1)},
            id="long-reason",
        ),
    ],
)
def test_model_enforces_invariants(fields: dict[str, Any]) -> None:
    AiVerdict(**_TRADE)
    with pytest.raises(ValidationError):
        AiVerdict(**{**_TRADE, **fields})


def test_prompt_exposes_version_and_stable_hash() -> None:
    assert prompt.PROMPT_VERSION
    assert len(prompt.prompt_hash()) == 64
    assert prompt.prompt_hash() == prompt.prompt_hash()


def test_prompt_hash_changes_when_prompt_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    before = prompt.prompt_hash()
    monkeypatch.setattr(prompt, "SYSTEM_PROMPT", prompt.SYSTEM_PROMPT + " changed")

    assert prompt.prompt_hash() != before


@pytest.mark.parametrize(
    "phrase",
    ["already-computed", "ONLY one JSON object", "HOLD", "does not place orders", "BUY", "SELL"],
)
def test_system_prompt_states_required_rules(phrase: str) -> None:
    assert phrase in prompt.SYSTEM_PROMPT


def test_user_message_embeds_sorted_key_json() -> None:
    message = prompt.build_user_message({"b": 1, "a": {"z": 1, "y": 2}})

    assert message.index('"a"') < message.index('"b"')
    assert message.index('"y"') < message.index('"z"')
    assert json.loads(message[message.index("{") :]) == {"a": {"y": 2, "z": 1}, "b": 1}


def test_user_message_rejects_oversized_context() -> None:
    with pytest.raises(prompt.ContextTooLargeError):
        prompt.build_user_message({"blob": "x" * prompt.MAX_CONTEXT_CHARS})


@pytest.mark.parametrize(
    "context",
    [{"when": object()}, {"n": float("nan")}, {"s": {1, 2}}],
    ids=["unknown-type", "nan", "set"],
)
def test_user_message_rejects_unserialisable_context(context: dict[str, object]) -> None:
    with pytest.raises(prompt.ContextError):
        prompt.build_user_message(context)
