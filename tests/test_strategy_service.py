"""Strategy service: built-ins first, built-in protection, resolve with the default slug."""

from pathlib import Path
from typing import Any

import pytest

from smc_scanner.ai.store import StoreError
from smc_scanner.strategy.models import DEFAULT_STRATEGY_SLUG, ConditionRef, Strategy
from smc_scanner.strategy.service import BuiltinStrategyError, StrategyService
from smc_scanner.strategy.store import (
    SqliteStrategyRepository,
    StrategyConflictError,
    StrategyNotFoundError,
    non_builtin,
)


def make(slug: str, **changes: Any) -> Strategy:
    fields: dict[str, Any] = {
        "slug": slug,
        "name": f"Strategy {slug}",
        "description": "",
        "zone_kinds": ("OB", "FVG"),
        "swing_length": 10,
        "near_atr": 0.5,
        "require": (),
        "score": (ConditionRef(key="ote"),),
        "min_score": 0,
        "statuses": ("TOUCHING",),
    }
    return Strategy(**{**fields, **changes})


class FakeRepository:
    """In-memory ``StrategyRepository`` with the same errors as the SQLite one."""

    def __init__(self, *stored: Strategy) -> None:
        self.rows: dict[str, Strategy] = {s.slug: s for s in stored}

    def list(self) -> tuple[Strategy, ...]:
        return tuple(self.rows[slug] for slug in sorted(self.rows))

    def get(self, slug: str) -> Strategy:
        if slug not in self.rows:
            raise StrategyNotFoundError(slug)
        return self.rows[slug]

    def create(self, strategy: Strategy) -> Strategy:
        if strategy.slug in self.rows:
            raise StrategyConflictError(strategy.slug)
        self.rows[strategy.slug] = non_builtin(strategy)
        return self.rows[strategy.slug]

    def update(self, strategy: Strategy) -> Strategy:
        self.get(strategy.slug)
        self.rows[strategy.slug] = non_builtin(strategy)
        return self.rows[strategy.slug]

    def delete(self, slug: str) -> None:
        self.get(slug)
        del self.rows[slug]


DEFAULT = make(DEFAULT_STRATEGY_SLUG, builtin=True)
FVG_ONLY = make("fvg-only", builtin=True, zone_kinds=("FVG",))
BUILTINS = {DEFAULT.slug: DEFAULT, FVG_ONLY.slug: FVG_ONLY}


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository(make("zeta"), make("alpha"))


@pytest.fixture
def service(repository: FakeRepository) -> StrategyService:
    return StrategyService(repository, BUILTINS)


def test_list_returns_builtins_in_mapping_order_then_stored(service: StrategyService) -> None:
    slugs = [s.slug for s in service.list()]

    assert slugs == [DEFAULT_STRATEGY_SLUG, "fvg-only", "alpha", "zeta"]


def test_list_keeps_the_mapping_order_not_slug_order(repository: FakeRepository) -> None:
    service = StrategyService(repository, {FVG_ONLY.slug: FVG_ONLY, DEFAULT.slug: DEFAULT})

    assert [s.slug for s in service.list()][:2] == ["fvg-only", DEFAULT_STRATEGY_SLUG]


def test_list_hides_a_stored_row_shadowed_by_a_builtin() -> None:
    repository = FakeRepository(make("fvg-only", name="Old user copy"), make("mine"))
    service = StrategyService(repository, BUILTINS)

    listed = service.list()

    assert [s.slug for s in listed] == [DEFAULT_STRATEGY_SLUG, "fvg-only", "mine"]
    assert listed[1] == FVG_ONLY


def test_get_finds_builtins_and_stored(service: StrategyService) -> None:
    assert service.get("fvg-only") == FVG_ONLY
    assert service.get("alpha") == make("alpha")


def test_get_prefers_the_builtin_over_a_shadowed_row() -> None:
    service = StrategyService(FakeRepository(make("fvg-only")), BUILTINS)

    assert service.get("fvg-only") == FVG_ONLY


def test_get_unknown_slug_raises(service: StrategyService) -> None:
    with pytest.raises(StrategyNotFoundError):
        service.get("missing")


def test_create_stores_a_non_builtin_copy(
    service: StrategyService, repository: FakeRepository
) -> None:
    created = service.create(make("mine", builtin=True))

    assert created.builtin is False
    assert repository.rows["mine"] == make("mine")
    assert service.get("mine").builtin is False


def test_create_rejects_a_builtin_slug(
    service: StrategyService, repository: FakeRepository
) -> None:
    with pytest.raises(StrategyConflictError):
        service.create(make(DEFAULT_STRATEGY_SLUG))
    assert DEFAULT_STRATEGY_SLUG not in repository.rows


def test_create_passes_through_a_stored_conflict(service: StrategyService) -> None:
    with pytest.raises(StrategyConflictError):
        service.create(make("alpha"))


def test_update_and_delete_refuse_builtins(
    service: StrategyService, repository: FakeRepository
) -> None:
    before = dict(repository.rows)

    with pytest.raises(BuiltinStrategyError):
        service.update(make("fvg-only", name="Hacked"))
    with pytest.raises(BuiltinStrategyError):
        service.delete(DEFAULT_STRATEGY_SLUG)
    assert repository.rows == before
    assert service.get("fvg-only") == FVG_ONLY


def test_update_replaces_a_stored_strategy_as_non_builtin(
    service: StrategyService, repository: FakeRepository
) -> None:
    updated = service.update(make("alpha", name="Renamed", builtin=True))

    assert updated == make("alpha", name="Renamed")
    assert repository.rows["alpha"] == updated


def test_update_and_delete_unknown_slug_raise(service: StrategyService) -> None:
    with pytest.raises(StrategyNotFoundError):
        service.update(make("missing"))
    with pytest.raises(StrategyNotFoundError):
        service.delete("missing")


def test_delete_removes_a_stored_strategy(
    service: StrategyService, repository: FakeRepository
) -> None:
    service.delete("alpha")

    assert "alpha" not in repository.rows


def test_resolve_none_is_the_default_strategy(service: StrategyService) -> None:
    assert service.resolve(None) == DEFAULT


def test_resolve_finds_builtins_and_stored(service: StrategyService) -> None:
    assert service.resolve("fvg-only") == FVG_ONLY
    assert service.resolve("zeta") == make("zeta")


def test_resolve_unknown_slug_raises(service: StrategyService) -> None:
    with pytest.raises(StrategyNotFoundError):
        service.resolve("missing")


def test_resolve_none_without_a_default_builtin_raises(repository: FakeRepository) -> None:
    service = StrategyService(repository, {FVG_ONLY.slug: FVG_ONLY})

    with pytest.raises(StrategyNotFoundError):
        service.resolve(None)


def test_builtins_are_marked_builtin(repository: FakeRepository) -> None:
    plain = make("plain")

    service = StrategyService(repository, {plain.slug: plain})

    assert service.get("plain").builtin is True
    assert plain.builtin is False


def test_builtins_are_copied_not_aliased(repository: FakeRepository) -> None:
    service = StrategyService(repository, BUILTINS)

    assert service.get("fvg-only") == FVG_ONLY
    assert service.get("fvg-only") is not FVG_ONLY


def test_builtins_mapping_is_copied(repository: FakeRepository) -> None:
    builtins = dict(BUILTINS)
    service = StrategyService(repository, builtins)

    builtins["late"] = make("late", builtin=True)
    del builtins["fvg-only"]

    assert [s.slug for s in service.list()][:2] == [DEFAULT_STRATEGY_SLUG, "fvg-only"]
    with pytest.raises(StrategyNotFoundError):
        service.get("late")


def test_builtin_keys_must_match_their_slugs(repository: FakeRepository) -> None:
    with pytest.raises(ValueError, match="slug"):
        StrategyService(repository, {"other": DEFAULT})


def test_builtin_strategy_error_is_a_store_error() -> None:
    assert issubclass(BuiltinStrategyError, StoreError)


def test_service_works_over_the_sqlite_repository(tmp_path: Path) -> None:
    service = StrategyService(SqliteStrategyRepository(tmp_path / "smc.db"), BUILTINS)

    service.create(make("mine", builtin=True))
    with pytest.raises(StrategyConflictError):
        service.create(make("fvg-only"))

    assert [s.slug for s in service.list()] == [DEFAULT_STRATEGY_SLUG, "fvg-only", "mine"]
    assert service.resolve("mine") == make("mine")
