"""Strategy lookup and editing over built-in presets plus the user's stored strategies.

Built-ins are injected (not imported) so this layer does not depend on where the presets live.
They are read-only: their slugs cannot be created, updated or deleted, and a stored row that
shares a built-in slug (e.g. a preset added after the user saved that slug) is hidden behind the
built-in. Such a row still counts toward the store's cap until it is removed from the database.
"""

from collections.abc import Mapping
from types import MappingProxyType

from smc_scanner.ai.store import StoreError
from smc_scanner.strategy.models import DEFAULT_STRATEGY_SLUG, Strategy
from smc_scanner.strategy.store import StrategyConflictError, StrategyRepository, non_builtin


class BuiltinStrategyError(StoreError):
    """Built-in strategies cannot be changed or deleted."""


def _as_builtin(strategy: Strategy) -> Strategy:
    """Always a fresh validated copy, so callers' references never alias the shared presets."""
    return Strategy.model_validate({**strategy.model_dump(), "builtin": True})


def _checked_builtins(builtins: Mapping[str, Strategy]) -> Mapping[str, Strategy]:
    """A read-only copy, each marked built-in; keys must equal their strategy's slug."""
    copied: dict[str, Strategy] = {}
    for key, strategy in builtins.items():
        if key != strategy.slug:
            raise ValueError(f"built-in key {key!r} does not match its slug {strategy.slug!r}")
        copied[key] = _as_builtin(strategy)
    return MappingProxyType(copied)


class StrategyService:
    def __init__(self, repository: StrategyRepository, builtins: Mapping[str, Strategy]) -> None:
        self._repository = repository
        self._builtins = _checked_builtins(builtins)

    def list(self) -> tuple[Strategy, ...]:
        """Built-ins in the mapping's order, then stored strategies by slug."""
        stored = (s for s in self._repository.list() if s.slug not in self._builtins)
        return (*self._builtins.values(), *stored)

    def get(self, slug: str) -> Strategy:
        builtin = self._builtins.get(slug)
        return builtin if builtin is not None else self._repository.get(slug)

    def create(self, strategy: Strategy) -> Strategy:
        if strategy.slug in self._builtins:
            raise StrategyConflictError(f"{strategy.slug!r} is a built-in strategy")
        return self._repository.create(non_builtin(strategy))

    def update(self, strategy: Strategy) -> Strategy:
        self._refuse_builtin(strategy.slug)
        return self._repository.update(non_builtin(strategy))

    def delete(self, slug: str) -> None:
        self._refuse_builtin(slug)
        self._repository.delete(slug)

    def resolve(self, slug: str | None) -> Strategy:
        """The strategy to scan with; ``None`` means ``DEFAULT_STRATEGY_SLUG``."""
        return self.get(DEFAULT_STRATEGY_SLUG if slug is None else slug)

    def _refuse_builtin(self, slug: str) -> None:
        if slug in self._builtins:
            raise BuiltinStrategyError(f"{slug!r} is a built-in strategy and cannot be changed")
