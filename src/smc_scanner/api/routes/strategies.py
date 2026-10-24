"""Strategy CRUD: built-ins first, then the user's stored strategies."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import ValidationError

from smc_scanner.api.constants import INVALID_STRATEGY_MESSAGE
from smc_scanner.api.deps import InternalKeyDep, StrategiesRateDep, StrategyServiceDep
from smc_scanner.api.schemas import RETRY_AFTER_HEADER, ErrorResponse
from smc_scanner.api.strategy_deps import checked_conditions, strategy_store_errors
from smc_scanner.api.strategy_schemas import (
    SlugPath,
    StrategyCreate,
    StrategyList,
    StrategyOut,
    StrategyUpdate,
)
from smc_scanner.strategy.models import Strategy

log = logging.getLogger(__name__)
router = APIRouter()
_MAX_LOGGED_ERROR_CHARS = 500

_ERROR: dict[str, Any] = {"model": ErrorResponse}
_RATE_LIMITED: dict[str, Any] = {
    **_ERROR,
    "description": "Too many strategy requests; see the Retry-After header",
    "headers": RETRY_AFTER_HEADER,
}
READ_ERRORS: dict[int | str, dict[str, Any]] = {
    429: _RATE_LIMITED,
    503: {**_ERROR, "description": "Strategy database unavailable"},
}
SLUG_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {**_ERROR, "description": "No strategy with that slug"},
    **READ_ERRORS,
}
WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    409: {**_ERROR, "description": "Built-in strategy, slug taken, or the strategy limit reached"},
    422: {**_ERROR, "description": "Invalid strategy, e.g. an unknown condition or bad params"},
    **READ_ERRORS,
}


def _validated(body: StrategyUpdate, slug: str) -> Strategy:
    """The body as a ``Strategy`` whose conditions all resolve; 422 with a fixed message."""
    try:
        strategy = body.to_strategy(slug)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        log.info("invalid strategy: %s", str(errors)[:_MAX_LOGGED_ERROR_CHARS])
        raise HTTPException(status_code=422, detail=INVALID_STRATEGY_MESSAGE) from exc
    return checked_conditions(strategy)


@router.get("/strategies", response_model=StrategyList, tags=["strategies"], responses=READ_ERRORS)
def list_strategies(
    _: InternalKeyDep, __: StrategiesRateDep, service: StrategyServiceDep
) -> StrategyList:
    """Every strategy: the built-ins in a fixed order, then the stored ones by slug."""
    with strategy_store_errors():
        found = service.list()
    return StrategyList(items=[StrategyOut.from_strategy(s) for s in found])


@router.get(
    "/strategies/{slug}", response_model=StrategyOut, tags=["strategies"], responses=SLUG_ERRORS
)
def get_strategy(
    slug: SlugPath, _: InternalKeyDep, __: StrategiesRateDep, service: StrategyServiceDep
) -> StrategyOut:
    """One strategy, built-in or stored."""
    with strategy_store_errors():
        return StrategyOut.from_strategy(service.get(slug))


@router.post(
    "/strategies",
    response_model=StrategyOut,
    status_code=201,
    tags=["strategies"],
    responses=WRITE_ERRORS,
)
def create_strategy(
    body: StrategyCreate, _: InternalKeyDep, __: StrategiesRateDep, service: StrategyServiceDep
) -> StrategyOut:
    """Store a new strategy. Its slug must not be a built-in's or an existing one's (409)."""
    strategy = _validated(body, body.slug)
    with strategy_store_errors():
        return StrategyOut.from_strategy(service.create(strategy))


@router.put(
    "/strategies/{slug}",
    response_model=StrategyOut,
    tags=["strategies"],
    responses={**SLUG_ERRORS, **WRITE_ERRORS},
)
def update_strategy(
    slug: SlugPath,
    body: StrategyUpdate,
    _: InternalKeyDep,
    __: StrategiesRateDep,
    service: StrategyServiceDep,
) -> StrategyOut:
    """Replace a stored strategy's definition. Built-ins cannot be changed (409)."""
    strategy = _validated(body, slug)
    with strategy_store_errors():
        return StrategyOut.from_strategy(service.update(strategy))


@router.delete(
    "/strategies/{slug}",
    status_code=204,
    response_class=Response,
    tags=["strategies"],
    responses={**SLUG_ERRORS, 409: {**_ERROR, "description": "Built-in strategy"}},
)
def delete_strategy(
    slug: SlugPath, _: InternalKeyDep, __: StrategiesRateDep, service: StrategyServiceDep
) -> Response:
    """Delete a stored strategy. Schedules that name it fall back to ``smc-default``."""
    with strategy_store_errors():
        service.delete(slug)
    return Response(status_code=204)
