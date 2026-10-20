"""AiVerdict model and strict parsing of untrusted LLM replies.

`parse_verdict` never raises: any malformed, oversized or implausible reply becomes a HOLD
verdict flagged `downgraded=True` with the reason. Risk/reward is always computed locally.

Local plausibility limits (all in ATR units of the hit): stop 0.1-5 away from entry, targets at
most 15 away, and reward/risk to the first target between 1.0 and 20. The 1.0 floor is enforced
(a trade risking more than it can win is downgraded); the prompt asks the model for >= 2.

`summary`, `reasons` and `downgrade_reason` are model-controlled display text. They are stripped
of control, bidi and zero-width characters and newlines, but are NOT escaped for any output
format: whoever renders them (HTML, Telegram, terminal) must escape them for that format.
"""

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1
MAX_REPLY_CHARS = 20_000
MAX_TARGETS = 3
MAX_REASONS = 8
MAX_REASON_CHARS = 200
MAX_SUMMARY_CHARS = 600
MAX_ENTRY_ATR_DISTANCE = 1.5
MIN_STOP_ATR = 0.1
MAX_STOP_ATR = 5.0
MAX_TARGET_ATR = 15.0
MIN_RISK_REWARD = 1.0
MAX_RISK_REWARD = 20.0
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 100.0

Action = Literal["BUY", "SELL", "HOLD"]
Quality = Literal["A", "B", "C"]

_FENCE = re.compile(r"^```[A-Za-z]*\s*\n?(.*?)\s*```$", re.DOTALL)
_LINE_BREAKS = "\n\r\t\v\f  "
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf"})  # control, plus format (bidi, zero-width, BOM)


@dataclass(frozen=True)
class HitFacts:
    """Scanner facts about the hit, used to sanity-check the model's levels."""

    direction: Literal[1, -1]
    price: float
    zone_low: float
    zone_high: float
    atr: float


@dataclass(frozen=True)
class _Levels:
    entry: float
    stop: float
    targets: tuple[float, ...]
    risk_reward: float


def clean_text(text: str) -> str:
    """Drop control/format characters, turn line breaks into spaces, collapse whitespace."""
    kept = (
        " " if ch in _LINE_BREAKS else ch
        for ch in text
        if ch in _LINE_BREAKS or unicodedata.category(ch) not in _DROPPED_CATEGORIES
    )
    return " ".join("".join(kept).split())


class AiVerdict(BaseModel):
    """Validated verdict. `risk_reward` is computed locally, never taken from the model."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    schema_version: int = SCHEMA_VERSION
    action: Action
    confidence: float = Field(ge=CONFIDENCE_MIN, le=CONFIDENCE_MAX)
    quality: Quality | None = None
    entry: float | None = None
    stop: float | None = None
    targets: tuple[float, ...] = Field(default=(), max_length=MAX_TARGETS)
    risk_reward: float | None = None
    invalidation: float | None = None
    reasons: tuple[Annotated[str, Field(max_length=MAX_REASON_CHARS)], ...] = Field(
        default=(), max_length=MAX_REASONS
    )
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    downgraded: bool = False
    downgrade_reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        return clean_text(value)

    @field_validator("downgrade_reason")
    @classmethod
    def _clean_reason(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value)

    @field_validator("reasons")
    @classmethod
    def _clean_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(cleaned for r in value if (cleaned := clean_text(r)))

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        levels = (self.entry, self.stop, self.invalidation, self.risk_reward)
        if self.action == "HOLD":
            if any(v is not None for v in levels) or self.targets:
                raise ValueError("HOLD must not carry trade levels")
        elif (
            self.entry is None or self.stop is None or self.risk_reward is None or not self.targets
        ):
            raise ValueError(f"{self.action} needs entry, stop, targets and risk_reward")
        if self.downgraded != bool(self.downgrade_reason):
            raise ValueError("downgraded requires a downgrade_reason, and only then")
        return self


class _ModelReply(BaseModel):
    """What the model is asked to return; unknown fields (e.g. risk_reward) are ignored."""

    model_config = ConfigDict(extra="ignore", strict=True)

    action: Action
    confidence: float
    quality: Quality | None = None
    entry: float | None = None
    stop: float | None = None
    targets: list[float] = Field(default_factory=list, max_length=MAX_TARGETS)
    invalidation: float | None = None
    reasons: list[Annotated[str, Field(max_length=MAX_REASON_CHARS)]] = Field(
        default_factory=list, max_length=MAX_REASONS
    )
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)


def _hold(reason: str) -> AiVerdict:
    return AiVerdict(
        action="HOLD",
        confidence=0.0,
        summary=f"Downgraded to HOLD: {reason}"[:MAX_SUMMARY_CHARS],
        downgraded=True,
        downgrade_reason=reason[:MAX_REASON_CHARS],
    )


def _facts_usable(facts: HitFacts) -> bool:
    numbers = (facts.price, facts.zone_low, facts.zone_high, facts.atr)
    return (
        not isinstance(facts.direction, bool)
        and facts.direction in (1, -1)
        and all(math.isfinite(n) for n in numbers)
        and facts.price > 0
        and 0 < facts.zone_low <= facts.zone_high
        and facts.atr > 0
    )


def _strip_fences(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1) if match else text


def _decode(raw: object) -> tuple[_ModelReply | None, str]:
    """Return the validated reply, or None plus the reason it was rejected."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty or non-text reply"
    if len(raw) > MAX_REPLY_CHARS:
        return None, f"reply too large (>{MAX_REPLY_CHARS} chars)"
    try:
        data = json.loads(_strip_fences(raw.strip()))
    except (ValueError, RecursionError):
        return None, "reply is not valid JSON"
    if not isinstance(data, dict):
        return None, "reply is not a JSON object"
    try:
        return _ModelReply.model_validate(data), ""
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "reply"
        return None, f"schema violation in {where}: {first['msg']}"


def _check_prices(reply: _ModelReply, entry: float, stop: float) -> str | None:
    named: list[tuple[str, float | None]] = [("entry", entry), ("stop", stop)]
    named.append(("invalidation", reply.invalidation))
    named += [(f"target {i + 1}", t) for i, t in enumerate(reply.targets)]
    for name, value in named:
        if value is not None and (not math.isfinite(value) or value <= 0):
            return f"non-finite or non-positive price in {name}"
    return None


def _check_geometry(reply: _ModelReply, entry: float, stop: float) -> str | None:
    sign = 1 if reply.action == "BUY" else -1
    if sign * (entry - stop) <= 0:
        return "stop on the wrong side of entry"
    offsets = [sign * (t - entry) for t in reply.targets]
    if any(o <= 0 for o in offsets):
        return "target on the wrong side of entry"
    if any(later <= earlier for earlier, later in zip(offsets, offsets[1:], strict=False)):
        return "targets not ordered nearest-first"
    if reply.invalidation is not None and sign * (entry - reply.invalidation) <= 0:
        return "invalidation on the wrong side of entry"
    return None


def _check_distances(reply: _ModelReply, entry: float, stop: float, facts: HitFacts) -> str | None:
    stop_atr = abs(entry - stop) / facts.atr
    if not MIN_STOP_ATR <= stop_atr <= MAX_STOP_ATR:
        return f"stop distance outside {MIN_STOP_ATR}-{MAX_STOP_ATR} ATR"
    if max(abs(t - entry) for t in reply.targets) / facts.atr > MAX_TARGET_ATR:
        return f"target distance above {MAX_TARGET_ATR} ATR"
    gap = max(facts.zone_low - entry, 0.0, entry - facts.zone_high)
    if gap > MAX_ENTRY_ATR_DISTANCE * facts.atr:
        return f"entry more than {MAX_ENTRY_ATR_DISTANCE} ATR from the zone"
    return None


def _check_levels(reply: _ModelReply, facts: HitFacts) -> _Levels | str:
    """Sanity-check a BUY/SELL reply; return the vetted levels or the downgrade reason."""
    if (facts.direction == 1) != (reply.action == "BUY"):
        return f"{reply.action} contradicts hit direction {facts.direction}"
    if reply.entry is None:
        return "missing entry"
    if reply.stop is None:
        return "missing stop"
    if not reply.targets:
        return "needs at least one target"
    entry, stop = reply.entry, reply.stop
    problem = (
        _check_prices(reply, entry, stop)
        or _check_geometry(reply, entry, stop)
        or _check_distances(reply, entry, stop, facts)
    )
    if problem is not None:
        return problem
    risk_reward = abs(reply.targets[0] - entry) / abs(entry - stop)
    if not MIN_RISK_REWARD <= risk_reward <= MAX_RISK_REWARD:
        return f"risk/reward outside {MIN_RISK_REWARD}-{MAX_RISK_REWARD}"
    return _Levels(entry, stop, tuple(reply.targets), risk_reward)


def _build(reply: _ModelReply, levels: _Levels | None) -> AiVerdict:
    common = {
        "action": reply.action,
        "confidence": reply.confidence,
        "quality": reply.quality,
        "reasons": tuple(reply.reasons),
        "summary": reply.summary,
    }
    if levels is None:
        return AiVerdict(**common)  # type: ignore[arg-type]
    return AiVerdict(
        **common,  # type: ignore[arg-type]
        entry=levels.entry,
        stop=levels.stop,
        targets=levels.targets,
        risk_reward=levels.risk_reward,
        invalidation=reply.invalidation,
    )


def parse_verdict(raw: str, facts: HitFacts) -> AiVerdict:
    """Parse an untrusted model reply into an AiVerdict; never raises."""
    if not _facts_usable(facts):
        return _hold("unusable hit facts")
    reply, reason = _decode(raw)
    if reply is None:
        return _hold(reason)
    if not CONFIDENCE_MIN <= reply.confidence <= CONFIDENCE_MAX:
        return _hold(f"confidence outside {CONFIDENCE_MIN:.0f}-{CONFIDENCE_MAX:.0f}")
    if reply.action == "HOLD":
        return _build(reply, None)
    levels = _check_levels(reply, facts)
    if isinstance(levels, str):
        return _hold(levels)
    return _build(reply, levels)
