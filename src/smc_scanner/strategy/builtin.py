"""Strategies shipped with the scanner. ``smc-default`` reproduces the pre-strategy scan."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from smc_scanner.config import DEFAULT_NEAR_ATR, DEFAULT_SWING_LENGTH
from smc_scanner.strategy.models import DEFAULT_STRATEGY_SLUG, ConditionRef, Strategy


def _refs(*keys: str) -> tuple[ConditionRef, ...]:
    return tuple(ConditionRef(key=key) for key in keys)


SMC_DEFAULT: Final = Strategy(
    slug=DEFAULT_STRATEGY_SLUG,
    name="SMC default",
    description=(
        "FVG and OB zones the latest candle touches or is near, scored 0-4 on trend "
        "alignment, OTE overlap, trendline hold and OB/FVG stacking."
    ),
    zone_kinds=("FVG", "OB"),
    swing_length=DEFAULT_SWING_LENGTH,
    near_atr=DEFAULT_NEAR_ATR,
    require=(),
    score=_refs("aligned", "in_ote", "trendline_ok", "stacked"),
    min_score=0,
    statuses=("TOUCHING", "NEAR"),
    builtin=True,
)

FRESH_OB_TREND: Final = Strategy(
    slug="fresh-ob-trend",
    name="Fresh OB with the trend",
    description=(
        "First touch of an order block that points with the trend, with at least one of "
        "OTE overlap, trendline hold or an FVG stacked on it."
    ),
    zone_kinds=("OB",),
    swing_length=DEFAULT_SWING_LENGTH,
    near_atr=DEFAULT_NEAR_ATR,
    require=_refs("fresh", "aligned"),
    score=_refs("in_ote", "trendline_ok", "stacked"),
    min_score=1,
    statuses=("TOUCHING", "NEAR"),
    builtin=True,
)

FVG_OTE_REVERSAL: Final = Strategy(
    slug="fvg-ote-reversal",
    name="FVG in the OTE",
    description=(
        "Price touching a fair value gap inside the 0.618-0.786 retracement, where a "
        "pullback often turns, with at least one of trend alignment, stacking or freshness."
    ),
    zone_kinds=("FVG",),
    swing_length=DEFAULT_SWING_LENGTH,
    near_atr=DEFAULT_NEAR_ATR,
    require=_refs("in_ote", "touching"),
    score=_refs("aligned", "stacked", "fresh"),
    min_score=1,
    statuses=("TOUCHING",),
    builtin=True,
)

HTF_ALIGNED_TOUCH: Final = Strategy(
    slug="htf-aligned-touch",
    name="HTF-aligned touch",
    description=(
        "A zone the latest candle touches, pointing with the trend on this and the next "
        "higher timeframe (an unknown higher timeframe passes), scored on OTE, trendline, "
        "stacking and freshness."
    ),
    zone_kinds=("FVG", "OB"),
    swing_length=DEFAULT_SWING_LENGTH,
    near_atr=DEFAULT_NEAR_ATR,
    require=_refs("aligned", "htf_aligned"),
    score=_refs("in_ote", "trendline_ok", "stacked", "fresh"),
    min_score=0,
    statuses=("TOUCHING",),
    mtf=True,
    builtin=True,
)

PRESETS: Final[tuple[Strategy, ...]] = (
    SMC_DEFAULT,
    FRESH_OB_TREND,
    FVG_OTE_REVERSAL,
    HTF_ALIGNED_TOUCH,
)

BUILTIN_STRATEGIES: Final[Mapping[str, Strategy]] = MappingProxyType(
    {preset.slug: preset for preset in PRESETS}
)


def builtin_copy(slug: str) -> Strategy | None:
    """A deep copy of the built-in ``slug`` (the presets are shared), or None if there is none."""
    preset = BUILTIN_STRATEGIES.get(slug)
    return None if preset is None else preset.model_copy(deep=True)
