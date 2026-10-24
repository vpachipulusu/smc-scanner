"""Request and response models of the strategy routes and the ``/config`` catalogue.

The request models mirror ``strategy.models.Strategy`` for the OpenAPI schema (and so the
generated client), but ``Strategy`` itself stays the one validator: ``to_strategy`` builds it,
with ``builtin`` always False. Neither request model has ``builtin``; the update model has no
``slug`` either (it comes from the path).
"""

from typing import Annotated, Any, get_args

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field

from smc_scanner.api.constants import SLUG_REGEX
from smc_scanner.config import (
    DEFAULT_NEAR_ATR,
    DEFAULT_SWING_LENGTH,
    MAX_NEAR_ATR,
    MAX_SWING_LENGTH,
)
from smc_scanner.models import Status, ZoneKind
from smc_scanner.strategy.conditions import ConditionInfo
from smc_scanner.strategy.models import (
    CONDITION_KEY_PATTERN,
    MAX_CONDITION_PARAMS,
    MAX_CONDITIONS,
    MAX_PARAM_STRING_CHARS,
    MAX_STRATEGY_DESCRIPTION_CHARS,
    MAX_STRATEGY_NAME_CHARS,
    Strategy,
)

SlugPath = Annotated[str, Path(pattern=SLUG_REGEX)]
StrategySlug = Annotated[str, Field(pattern=SLUG_REGEX)]
# ``CONDITION_KEY_PATTERN`` ends in ``\Z`` like the slug pattern; ``$`` means the same here.
_CONDITION_KEY_REGEX = CONDITION_KEY_PATTERN.pattern.removesuffix(r"\Z") + "$"
# Param names and string values are bounded here too, so a rejected body is never echoed at
# length into a log line by the model's own validation messages.
ParamName = Annotated[str, Field(pattern=_CONDITION_KEY_REGEX)]
ParamValueIn = int | float | Annotated[str, Field(max_length=MAX_PARAM_STRING_CHARS)] | bool


class ConditionRefIn(BaseModel):
    """A condition named by registry key (see ``/config`` ``conditions``), with its params."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_CONDITION_KEY_REGEX)
    params: dict[ParamName, ParamValueIn] = Field(
        default_factory=dict, max_length=MAX_CONDITION_PARAMS
    )


ConditionRefs = Annotated[list[ConditionRefIn], Field(max_length=MAX_CONDITIONS)]


class StrategyUpdate(BaseModel):
    """A strategy's definition, for ``PUT /strategies/{slug}``. Defaults match ``smc-default``
    except that no condition is required or scored."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_STRATEGY_NAME_CHARS)
    description: str = Field(default="", max_length=MAX_STRATEGY_DESCRIPTION_CHARS)
    zone_kinds: list[ZoneKind] = Field(
        default=["FVG", "OB"], min_length=1, max_length=len(get_args(ZoneKind))
    )
    swing_length: int = Field(default=DEFAULT_SWING_LENGTH, ge=1, le=MAX_SWING_LENGTH)
    near_atr: float = Field(default=DEFAULT_NEAR_ATR, ge=0, le=MAX_NEAR_ATR)
    require: ConditionRefs = Field(default=[])  # pydantic copies mutable defaults
    score: ConditionRefs = Field(default=[])
    min_score: int = Field(default=0, ge=0, le=MAX_CONDITIONS)
    statuses: list[Status] = Field(
        default=["TOUCHING", "NEAR"], min_length=1, max_length=len(get_args(Status))
    )
    mtf: bool = False
    require_htf_aligned: bool = False  # needs mtf

    def to_strategy(self, slug: str) -> Strategy:
        """The validated, non-built-in ``Strategy``. ValueError (a ``ValidationError``) when the
        cross-field rules fail: duplicates, ``min_score`` above the score count, and so on."""
        return Strategy.model_validate({**self.model_dump(), "slug": slug, "builtin": False})


class StrategyCreate(StrategyUpdate):
    """A new strategy, for ``POST /strategies``: a definition plus its unique ``slug``."""

    slug: StrategySlug


class ConditionRefOut(BaseModel):
    key: str
    params: dict[str, int | float | str | bool]


class StrategyOut(BaseModel):
    """A whole strategy. Built-ins (``builtin`` true) cannot be changed or deleted."""

    slug: str
    name: str
    description: str
    zone_kinds: list[ZoneKind]
    swing_length: int
    near_atr: float
    require: list[ConditionRefOut]
    score: list[ConditionRefOut]
    min_score: int
    statuses: list[Status]
    mtf: bool
    require_htf_aligned: bool
    builtin: bool

    @classmethod
    def from_strategy(cls, strategy: Strategy) -> "StrategyOut":
        """A copy: the response never aliases a stored or built-in strategy's params."""
        return cls.model_validate(strategy.model_dump(mode="json"))


class StrategyList(BaseModel):
    items: list[StrategyOut]


class StrategySummary(BaseModel):
    """What a strategy picker needs; ``swing_length`` / ``near_atr`` can prefill the scan form."""

    slug: str
    name: str
    builtin: bool
    swing_length: int
    near_atr: float

    @classmethod
    def from_strategy(cls, strategy: Strategy) -> "StrategySummary":
        return cls.model_validate(strategy.model_dump(include=set(cls.model_fields)))


class ConditionInfoOut(BaseModel):
    """One condition a strategy may name: its key, a label and the JSON schema of its params."""

    key: str
    label: str
    params_schema: dict[str, Any]

    @classmethod
    def from_info(cls, info: ConditionInfo) -> "ConditionInfoOut":
        return cls(key=info.key, label=info.label, params_schema=info.params_schema)
