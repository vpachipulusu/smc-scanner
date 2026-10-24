"""Strategy data models: validated, JSON-serialisable, frozen.

A ``Strategy`` names conditions by key only; the code behind each key lives in a registry
(TRAD-35). Everything here is untrusted once it has been stored or posted, so every field is
bounded and the free-text fields are restricted to an allowlist.
"""

import math
import re
from typing import Final, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from smc_scanner.config import MAX_NEAR_ATR, MAX_SWING_LENGTH
from smc_scanner.models import Status, ZoneKind
from smc_scanner.scanner import ScanOptions

MAX_STRATEGY_NAME_CHARS: Final = 64
MAX_STRATEGY_DESCRIPTION_CHARS: Final = 280
MAX_CONDITIONS: Final = 12
MAX_CONDITION_PARAMS: Final = 8
MAX_PARAM_STRING_CHARS: Final = 32
MAX_PARAM_MAGNITUDE: Final = 1e9  # keeps numeric params far from overflow and JS precision loss
DEFAULT_STRATEGY_SLUG: Final = "smc-default"

# ``\Z`` rather than ``$``: ``$`` also matches before a trailing newline. Safe with ``match``.
SLUG_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
CONDITION_KEY_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,31}\Z")
_PARAM_STRING_PATTERN: Final = re.compile(r"[A-Za-z0-9_.-]*")
# Same alphabet as the calendar title filter in ``econ_calendar``. It keeps markup and control
# characters out; it is not a prompt-injection defence, so prompts must still fence this text.
_TEXT_PATTERN: Final = re.compile(r"[A-Za-z0-9 .,%()/&'-]*")
_HAS_ALNUM: Final = re.compile(r"[A-Za-z0-9]")

_FRESH_KEY: Final = "fresh"  # a first-touch-only strategy; the scanner drops repeat touches

ParamValue = int | float | str | bool


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _reject_duplicates(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must not contain duplicates")
    return values


class ConditionRef(BaseModel):
    """A condition named by registry key, with its tuning parameters.

    ``frozen`` is shallow: treat ``params`` as read-only. The model is not hashable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    params: dict[str, ParamValue] = Field(default_factory=dict, max_length=MAX_CONDITION_PARAMS)

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        if not CONDITION_KEY_PATTERN.fullmatch(value):
            raise ValueError("key must be 1-32 chars: a lowercase letter, then a-z, 0-9 or _")
        return value

    @field_validator("params")
    @classmethod
    def _check_params(cls, value: dict[str, ParamValue]) -> dict[str, ParamValue]:
        for name, item in value.items():
            if not CONDITION_KEY_PATTERN.fullmatch(name):
                raise ValueError(f"params name {name!r} must look like a condition key")
            if isinstance(item, str):
                _check_param_string(name, item)
            elif not isinstance(item, bool):
                _check_param_number(name, item)
        return value


def _check_param_string(name: str, value: str) -> None:
    if len(value) > MAX_PARAM_STRING_CHARS:
        raise ValueError(f"params[{name!r}] must be at most {MAX_PARAM_STRING_CHARS} characters")
    if not _PARAM_STRING_PATTERN.fullmatch(value):
        raise ValueError(f"params[{name!r}] may only contain letters, digits, _ . -")


def _check_param_number(name: str, value: float) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"params[{name!r}] must be finite")
    if abs(value) > MAX_PARAM_MAGNITUDE:
        raise ValueError(f"params[{name!r}] must be within +/-{MAX_PARAM_MAGNITUDE:g}")


class Strategy(BaseModel):
    """What to scan for: zone kinds, scan tuning, required and scored conditions.

    ``builtin`` marks shipped strategies. It is plain data here, so an API must set it
    server-side and never take it from a request body.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    name: str = Field(min_length=1, max_length=MAX_STRATEGY_NAME_CHARS)
    description: str = Field(max_length=MAX_STRATEGY_DESCRIPTION_CHARS)
    zone_kinds: tuple[ZoneKind, ...] = Field(min_length=1, max_length=len(get_args(ZoneKind)))
    swing_length: int = Field(strict=True, ge=1, le=MAX_SWING_LENGTH)
    near_atr: float = Field(strict=True, ge=0, le=MAX_NEAR_ATR, allow_inf_nan=False)
    require: tuple[ConditionRef, ...] = Field(max_length=MAX_CONDITIONS)
    score: tuple[ConditionRef, ...] = Field(max_length=MAX_CONDITIONS)
    min_score: int = Field(strict=True, ge=0)
    statuses: tuple[Status, ...] = Field(min_length=1, max_length=len(get_args(Status)))
    mtf: bool = Field(default=False, strict=True)
    require_htf_aligned: bool = Field(default=False, strict=True)
    builtin: bool = Field(default=False, strict=True)

    @field_validator("name", "description", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return _strip(value)

    @field_validator("name", "description")
    @classmethod
    def _check_text(cls, value: str, info: ValidationInfo) -> str:
        if not _TEXT_PATTERN.fullmatch(value):
            raise ValueError(
                f"{info.field_name} may only contain letters, digits, spaces and . , % ( ) / & ' -"
            )
        if info.field_name == "name" and not _HAS_ALNUM.search(value):
            raise ValueError("name must contain at least one letter or digit")
        return value

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        if not SLUG_PATTERN.fullmatch(value):
            raise ValueError("slug must be 1-32 chars: a-z, 0-9 or -, not starting with -")
        return value

    @field_validator("zone_kinds", "statuses")
    @classmethod
    def _check_unique(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        return _reject_duplicates(value, str(info.field_name))

    @model_validator(mode="after")
    def _check_cross_fields(self) -> Self:
        seen: set[str] = set()
        for key in self.condition_keys():
            if key in seen:
                raise ValueError(f"duplicate condition key: {key}")
            seen.add(key)
        if self.min_score > len(self.score):
            raise ValueError("min_score cannot exceed the number of score conditions")
        if self.require_htf_aligned and not self.mtf:
            raise ValueError("require_htf_aligned requires mtf")
        return self

    def condition_keys(self) -> tuple[str, ...]:
        """Required condition keys first, then scored ones, in declaration order."""
        return tuple(ref.key for ref in (*self.require, *self.score))

    def to_scan_options(self) -> ScanOptions:
        """Scan tuning for this strategy; ``all_touches`` unless it requires ``fresh``."""
        return ScanOptions(
            swing_length=self.swing_length,
            near_atr=self.near_atr,
            all_touches=not any(ref.key == _FRESH_KEY for ref in self.require),
        )
