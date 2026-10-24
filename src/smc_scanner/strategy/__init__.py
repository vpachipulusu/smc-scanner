"""Strategies are data; conditions are code.

A strategy is a validated, JSON-serialisable description of what to scan for. It refers to
conditions by key only, and never carries code. The condition registry that maps keys to
implementations lands in TRAD-35.
"""

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
]
