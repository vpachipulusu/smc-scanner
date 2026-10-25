"""Backtests: start one in the background, follow its status, read the stored results.

Rows of a strategy that no longer exists (a deleted stored strategy) are hidden from the list
and the latest-result badge; ``GET /backtests/{id}`` still returns them. ``DELETE
/strategies/{slug}`` leaves its backtest rows in place; the store's overall row cap prunes them
in time. A strategy re-created under a deleted slug shows the old slug's rows again.

The API must run with a single worker: the one-at-a-time guard is per process (see
``backtest.jobs``). Starting a run has its own, tighter rate limit than the reads, so polling
never starves it.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response

from smc_scanner.api.backtest_schemas import (
    BacktestCreate,
    BacktestId,
    BacktestList,
    BacktestListItem,
    BacktestOut,
    BacktestSummaryOut,
)
from smc_scanner.api.constants import (
    BACKTEST_NOT_FOUND_MESSAGE,
    BACKTEST_RUNNING_MESSAGE,
    BACKTEST_TOO_LARGE_MESSAGE,
    DEFAULT_BACKTESTS_LIMIT,
    INVALID_REQUEST_MESSAGE,
    MAX_BACKTEST_COST,
    MAX_BACKTESTS_LIMIT,
    NO_BACKTEST_MESSAGE,
    SLUG_REGEX,
)
from smc_scanner.api.deps import (
    BacktestJobsDep,
    BacktestsCreateRateDep,
    BacktestsRateDep,
    BacktestStoreDep,
    InternalKeyDep,
    RunnerFactoryDep,
    StrategyServiceDep,
    backtest_store_errors,
)
from smc_scanner.api.helpers import _symbols
from smc_scanner.api.schemas import RETRY_AFTER_HEADER, ErrorResponse
from smc_scanner.api.strategy_deps import resolve_strategy
from smc_scanner.api.strategy_schemas import SlugPath
from smc_scanner.backtest.jobs import (
    BacktestRequest,
    BacktestRunningError,
    SplitSpec,
    replay_cost,
)
from smc_scanner.strategy.store import StrategyNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(tags=["backtests"])

_ERROR: dict[str, Any] = {"model": ErrorResponse}
_RATE_LIMITED: dict[str, Any] = {
    **_ERROR,
    "description": "Too many backtest requests; see the Retry-After header",
    "headers": RETRY_AFTER_HEADER,
}
READ_ERRORS: dict[int | str, dict[str, Any]] = {
    429: _RATE_LIMITED,
    503: {**_ERROR, "description": "Backtest database unavailable"},
}
CREATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    202: {
        "description": "Accepted: the pending row; poll the Location header's URL",
        "headers": {
            "Location": {
                "description": "The new backtest, /backtests/{id}",
                "schema": {"type": "string"},
            }
        },
    },
    409: {**_ERROR, "description": "Backtest already running"},
    422: {
        **_ERROR,
        "description": "Invalid request: e.g. the csv source, an unknown strategy, a symbol "
        "split with one symbol, or a run over the cost cap",
    },
    429: {**_RATE_LIMITED, "description": "Too many backtests started; see Retry-After"},
    503: {**_ERROR, "description": "Backtest or strategy database unavailable"},
}


@router.get("/backtests", response_model=BacktestList, responses=READ_ERRORS)
def list_backtests(
    _: InternalKeyDep,
    __: BacktestsRateDep,
    store: BacktestStoreDep,
    service: StrategyServiceDep,
    strategy: Annotated[str | None, Query(pattern=SLUG_REGEX)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BACKTESTS_LIMIT)] = DEFAULT_BACKTESTS_LIMIT,
) -> BacktestList:
    """Backtests, newest first, of one strategy or of all, as summaries (``GET
    /backtests/{id}`` has the full results). Rows of deleted strategies are hidden."""
    with backtest_store_errors():
        visible = [found.slug for found in service.list()]
        records = store.list(strategy=strategy, visible=visible, limit=limit)
    return BacktestList(items=[BacktestListItem.from_record(record) for record in records])


@router.get(
    "/backtests/{backtest_id}",
    response_model=BacktestOut,
    responses={404: {**_ERROR, "description": "No backtest with that id"}, **READ_ERRORS},
)
def get_backtest(
    backtest_id: BacktestId, _: InternalKeyDep, __: BacktestsRateDep, store: BacktestStoreDep
) -> BacktestOut:
    """One backtest with its status and results; poll it until ``done`` or ``failed``."""
    with backtest_store_errors():
        record = store.get(backtest_id)
    if record is None:
        raise HTTPException(status_code=404, detail=BACKTEST_NOT_FOUND_MESSAGE)
    return BacktestOut.from_record(record)


@router.get(
    "/strategies/{slug}/backtest",
    response_model=BacktestSummaryOut,
    responses={
        404: {**_ERROR, "description": "No such strategy, or no finished backtest of it"},
        **READ_ERRORS,
    },
)
def get_strategy_backtest(
    slug: SlugPath,
    _: InternalKeyDep,
    __: BacktestsRateDep,
    store: BacktestStoreDep,
    service: StrategyServiceDep,
) -> BacktestSummaryOut:
    """The latest finished backtest of a strategy, as a badge: verdict, expectancy, its
    interval and the trade count."""
    with backtest_store_errors():
        try:
            service.get(slug)
        except StrategyNotFoundError as exc:  # a StoreError: caught before the 503 mapping
            raise HTTPException(status_code=404, detail=NO_BACKTEST_MESSAGE) from exc
        record = store.latest_done(slug)
    if record is None:
        raise HTTPException(status_code=404, detail=NO_BACKTEST_MESSAGE)
    return BacktestSummaryOut.from_record(record)


@router.post("/backtests", response_model=BacktestOut, status_code=202, responses=CREATE_RESPONSES)
def create_backtest(
    body: BacktestCreate,
    response: Response,
    _: InternalKeyDep,
    __: BacktestsCreateRateDep,
    service: StrategyServiceDep,
    store: BacktestStoreDep,
    jobs: BacktestJobsDep,
    runner_factory: RunnerFactoryDep,
) -> BacktestOut:
    """Start a walk-forward backtest of one strategy in the background and return its pending
    row (202, with ``Location``). One runs at a time: another request meanwhile gets 409. Poll
    ``GET /backtests/{id}`` for the status. The cost, symbols x bars^2 / stride, is capped
    (422): each replayed prefix costs about as much as its length."""
    strategy = resolve_strategy(service, body.strategy)
    symbols = list(dict.fromkeys(body.symbols or _symbols(body.source, None)))
    if replay_cost(len(symbols), body.bars, body.stride) > MAX_BACKTEST_COST:
        raise HTTPException(status_code=422, detail=BACKTEST_TOO_LARGE_MESSAGE)
    try:
        request = BacktestRequest(
            strategy=strategy,
            source=body.source,
            timeframe=body.tf,
            bars=body.bars,
            symbols=tuple(symbols),
            rules=body.rules.to_rules(),
            split=SplitSpec(body.split, body.train_fraction),
            seed=body.seed,
            stride=body.stride,
        )
    except ValueError as exc:  # the schema mirrors these limits, so this is a safety net
        log.info("backtest request rejected: %s", exc)
        raise HTTPException(status_code=422, detail=INVALID_REQUEST_MESSAGE) from exc
    runner = runner_factory()
    try:
        with backtest_store_errors():
            record = jobs.submit(request, runner, store)
    except BacktestRunningError as exc:
        raise HTTPException(status_code=409, detail=BACKTEST_RUNNING_MESSAGE) from exc
    response.headers["Location"] = f"/backtests/{record.id}"
    return BacktestOut.from_record(record)
