"""Condition registry: the code behind the condition keys a ``Strategy`` names.

Each condition declares its own parameter model (frozen, unknown names rejected) and a pure
check over a ``ZoneContext``. The built-ins wrap ``scoring`` rather than re-implementing it.
Lookups fail with ``UnknownConditionError`` or ``ConditionParamError``; their messages never
echo the rejected values.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any, Final, Protocol, TypeGuard, runtime_checkable

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from smc_scanner import scoring
from smc_scanner.config import MAX_BARS, MAX_NEAR_ATR
from smc_scanner.models import BULLISH, Bias, ZoneContext, ZoneKind
from smc_scanner.strategy.models import CONDITION_KEY_PATTERN, ConditionRef, ParamValue


def _well_formed(name: object) -> TypeGuard[str]:
    return isinstance(name, str) and CONDITION_KEY_PATTERN.fullmatch(name) is not None


class ConditionError(ValueError):
    """A strategy names a condition that cannot be built.

    ``key`` is the condition key when it is well formed, else ``""``: neither the message nor
    the attribute ever carries arbitrary input, so both are safe to log.
    """

    def __init__(self, key: object, message: str) -> None:
        super().__init__(message)
        self.key = key if _well_formed(key) else ""


class UnknownConditionError(ConditionError):
    def __init__(self, key: object) -> None:
        shown = repr(key) if _well_formed(key) else "(malformed key)"
        super().__init__(key, f"unknown condition: {shown}")


def _location(loc: tuple[int | str, ...]) -> str:
    """A param name from an error location; names that are not key-shaped are not echoed."""
    return ".".join(str(part) if _well_formed(part) else "(malformed name)" for part in loc)


class ConditionParamError(ConditionError):
    def __init__(self, key: str, exc: ValidationError) -> None:
        problems = "; ".join(
            f"{_location(error['loc']) or 'params'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        super().__init__(key, f"bad params for {key}: {problems}")


class _Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _number_only(value: object) -> object:
    """JSON sends 2.0 as 2, so ints become floats; bools and strings are rejected."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("must be a number")
    return float(value)


# A float parameter that accepts an int but never a bool or a numeric string.
FloatParam = Annotated[float, BeforeValidator(_number_only), Field(allow_inf_nan=False)]


class NoParams(_Params):
    pass


class MaxZoneAgeParams(_Params):
    bars: int = Field(strict=True, ge=1, le=MAX_BARS)


class MaxDistanceAtrParams(_Params):
    atr: FloatParam = Field(ge=0, le=MAX_NEAR_ATR)


class ZoneKindParams(_Params):
    kind: ZoneKind


class BiasParams(_Params):
    bias: Bias


@runtime_checkable
class Condition(Protocol):
    """A condition bound to validated parameters, ready to evaluate zones."""

    @property
    def key(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def params_model(self) -> type[BaseModel]: ...

    @property
    def params(self) -> BaseModel: ...

    def evaluate(self, ctx: ZoneContext) -> bool: ...


@dataclass(frozen=True)
class _Bound[P: BaseModel]:
    key: str
    label: str
    params_model: type[P]
    params: P
    check: Callable[[ZoneContext, P], bool]

    def evaluate(self, ctx: ZoneContext) -> bool:
        return self.check(ctx, self.params)


@dataclass(frozen=True)
class _Definition[P: BaseModel]:
    key: str
    label: str
    params_model: type[P]
    check: Callable[[ZoneContext, P], bool]

    def bind(self, params: Mapping[str, ParamValue]) -> Condition:
        try:
            validated = self.params_model.model_validate(dict(params))
        except ValidationError as exc:
            raise ConditionParamError(self.key, exc) from None
        return _Bound(self.key, self.label, self.params_model, validated, self.check)


@dataclass(frozen=True)
class ConditionInfo:
    """One registry entry for listings: key, label and the JSON schema of its parameters."""

    key: str
    label: str
    params_schema: dict[str, Any]


def _direction(ctx: ZoneContext) -> Bias:
    return "bullish" if ctx.state.zone.direction == BULLISH else "bearish"


def _htf_aligned(ctx: ZoneContext, _: NoParams) -> bool:
    """Mirrors ``mtf.htf_allows``: an unknown HTF passes, a range never confirms."""
    return ctx.htf_bias is None or ctx.htf_bias == _direction(ctx)


def _max_zone_age(ctx: ZoneContext, params: MaxZoneAgeParams) -> bool:
    return ctx.last_index - ctx.state.zone.formed_index <= params.bars


_DEFINITIONS: Final[tuple[_Definition[Any], ...]] = (
    _Definition(
        "aligned",
        "Zone direction matches the trend",
        NoParams,
        lambda ctx, _: scoring.is_aligned(ctx.state, ctx.structure),
    ),
    _Definition(
        "in_ote",
        "Zone overlaps the OTE band",
        NoParams,
        lambda ctx, _: scoring.in_ote(ctx.state, ctx.structure),
    ),
    _Definition(
        "trendline_ok",
        "Latest candle holds the trendline",
        NoParams,
        lambda ctx, _: scoring.trendline_ok(ctx.state, ctx.structure, ctx.ohlc),
    ),
    _Definition(
        "stacked",
        "An OB and an FVG overlap",
        NoParams,
        lambda ctx, _: scoring.stacked(ctx.state, ctx.valid),
    ),
    _Definition("fresh", "First touch only", NoParams, lambda ctx, _: ctx.state.prior_touches == 0),
    _Definition(
        "touching",
        "Latest candle touches the zone",
        NoParams,
        lambda ctx, _: ctx.state.status == "TOUCHING",
    ),
    _Definition("max_zone_age", "Zone at most N bars old", MaxZoneAgeParams, _max_zone_age),
    _Definition(
        "max_distance_atr",
        "Price within N ATR of the zone",
        MaxDistanceAtrParams,
        lambda ctx, p: ctx.state.distance_atr <= p.atr,
    ),
    _Definition(
        "zone_kind",
        "Zone is of the given kind",
        ZoneKindParams,
        lambda ctx, p: ctx.state.zone.kind == p.kind,
    ),
    _Definition(
        "bias_is",
        "Structure bias is the given bias",
        BiasParams,
        lambda ctx, p: ctx.structure.bias == p.bias,
    ),
    _Definition("htf_aligned", "Higher timeframe confirms the direction", NoParams, _htf_aligned),
)

_REGISTRY: Final[Mapping[str, _Definition[Any]]] = MappingProxyType(
    {definition.key: definition for definition in _DEFINITIONS}
)


def conditions() -> tuple[ConditionInfo, ...]:
    """Every registered condition, in registry order, with a fresh copy of its param schema."""
    return tuple(
        ConditionInfo(d.key, d.label, d.params_model.model_json_schema()) for d in _DEFINITIONS
    )


def get(key: str, params: Mapping[str, ParamValue] | None = None) -> Condition:
    """The condition ``key`` bound to ``params``, validated against its own model."""
    definition = _REGISTRY.get(key)
    if definition is None:
        raise UnknownConditionError(key)
    return definition.bind(params or {})


def resolve(ref: ConditionRef) -> Condition:
    return get(ref.key, ref.params)


def resolve_all(refs: Sequence[ConditionRef]) -> tuple[Condition, ...]:
    return tuple(resolve(ref) for ref in refs)
