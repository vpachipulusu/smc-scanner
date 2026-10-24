"""Strategies are data; conditions are code.

A strategy is a validated, JSON-serialisable description of what to scan for. It refers to
conditions by key only, and never carries code. The condition registry (``conditions``) maps
keys to implementations; the engine (``engine``) applies a strategy to a scan.
"""

# TRAD-35: condition registry, presets and engine.
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES
from smc_scanner.strategy.conditions import (
    Condition,
    ConditionError,
    ConditionInfo,
    ConditionParamError,
    UnknownConditionError,
)
from smc_scanner.strategy.engine import (
    apply_strategy,
    run_scan_with_strategy,
    scan_instrument_with_strategy,
    scan_watchlist_with_strategy,
    uses_mtf,
)
from smc_scanner.strategy.models import (
    CONDITION_KEY_PATTERN,
    DEFAULT_STRATEGY_SLUG,
    MAX_CONDITION_PARAMS,
    MAX_CONDITIONS,
    MAX_PARAM_MAGNITUDE,
    MAX_PARAM_STRING_CHARS,
    MAX_STRATEGY_DESCRIPTION_CHARS,
    MAX_STRATEGY_NAME_CHARS,
    SLUG_PATTERN,
    ConditionRef,
    ParamValue,
    Strategy,
)

__all__ = [
    "CONDITION_KEY_PATTERN",
    "DEFAULT_STRATEGY_SLUG",
    "MAX_CONDITIONS",
    "MAX_CONDITION_PARAMS",
    "MAX_PARAM_MAGNITUDE",
    "MAX_PARAM_STRING_CHARS",
    "MAX_STRATEGY_DESCRIPTION_CHARS",
    "MAX_STRATEGY_NAME_CHARS",
    "SLUG_PATTERN",
    "ConditionRef",
    "ParamValue",
    "Strategy",
    # TRAD-35
    "BUILTIN_STRATEGIES",
    "Condition",
    "ConditionError",
    "ConditionInfo",
    "ConditionParamError",
    "UnknownConditionError",
    "apply_strategy",
    "run_scan_with_strategy",
    "scan_instrument_with_strategy",
    "scan_watchlist_with_strategy",
    "uses_mtf",
]
