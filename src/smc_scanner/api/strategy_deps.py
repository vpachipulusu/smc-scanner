"""The strategy service the routes and scheduled runs use, and how its errors map to HTTP.

The repository is opened lazily: built-ins resolve without touching the database, so a scan
without ``strategy`` (or with a built-in) works exactly as before when the file is unusable.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

from fastapi import HTTPException

from smc_scanner.ai.store import StoreError
from smc_scanner.api.constants import (
    BUILTIN_STRATEGY_MESSAGE,
    INVALID_STRATEGY_MESSAGE,
    STRATEGY_EXISTS_MESSAGE,
    STRATEGY_LIMIT_MESSAGE,
    STRATEGY_NOT_FOUND_MESSAGE,
    STRATEGY_STORE_MESSAGE,
    UNKNOWN_STRATEGY_MESSAGE,
)
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES
from smc_scanner.strategy.conditions import ConditionError, resolve_all
from smc_scanner.strategy.models import Strategy
from smc_scanner.strategy.service import BuiltinStrategyError, StrategyService
from smc_scanner.strategy.store import (
    SqliteStrategyRepository,
    StrategyConflictError,
    StrategyLimitError,
    StrategyNotFoundError,
)

__all__ = [
    "checked_conditions",
    "resolve_strategy",
    "strategy_service_for",
    "strategy_store_errors",
]

log = logging.getLogger(__name__)


class _LazyStrategyRepository:
    """``SqliteStrategyRepository`` opened on first use (then kept); a failed open is retried."""

    def __init__(
        self, path: Callable[[], Path], init_lock: AbstractContextManager[object] | None
    ) -> None:
        self._path = path
        self._init_lock: AbstractContextManager[object] = init_lock or nullcontext()
        self._lock = threading.Lock()
        self._opened: SqliteStrategyRepository | None = None

    def _repository(self) -> SqliteStrategyRepository:
        with self._lock:
            if self._opened is None:
                with self._init_lock:  # first-time schema setup must not race the other stores
                    self._opened = SqliteStrategyRepository(self._path())
            return self._opened

    def list(self) -> tuple[Strategy, ...]:
        return self._repository().list()

    def get(self, slug: str) -> Strategy:
        return self._repository().get(slug)

    def create(self, strategy: Strategy) -> Strategy:
        return self._repository().create(strategy)

    def update(self, strategy: Strategy) -> Strategy:
        return self._repository().update(strategy)

    def delete(self, slug: str) -> None:
        self._repository().delete(slug)


def strategy_service_for(
    path: Callable[[], Path], *, init_lock: AbstractContextManager[object] | None = None
) -> StrategyService:
    """Built-ins plus the strategies stored in the file ``path()`` names (read on first use)."""
    return StrategyService(_LazyStrategyRepository(path, init_lock), BUILTIN_STRATEGIES)


def _store_unavailable(exc: StoreError) -> HTTPException:
    log.error("strategy store failed: %s", exc)  # the path stays in the log
    return HTTPException(status_code=503, detail=STRATEGY_STORE_MESSAGE)


@contextmanager
def strategy_store_errors() -> Iterator[None]:
    """Map the service's errors: not found 404; taken slug, built-in or the cap 409; else 503."""
    try:
        yield
    except StrategyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=STRATEGY_NOT_FOUND_MESSAGE) from exc
    except StrategyConflictError as exc:
        raise HTTPException(status_code=409, detail=STRATEGY_EXISTS_MESSAGE) from exc
    except BuiltinStrategyError as exc:
        raise HTTPException(status_code=409, detail=BUILTIN_STRATEGY_MESSAGE) from exc
    except StrategyLimitError as exc:
        raise HTTPException(status_code=409, detail=STRATEGY_LIMIT_MESSAGE) from exc
    except StoreError as exc:
        raise _store_unavailable(exc) from exc


def checked_conditions(strategy: Strategy) -> Strategy:
    """``strategy`` when every condition it names resolves; else 422 with a fixed message
    (``ConditionError`` text is safe to log, but the client gets nothing to probe with)."""
    try:
        resolve_all((*strategy.require, *strategy.score))
    except ConditionError as exc:
        log.info("strategy %s rejected: %s", strategy.slug, exc)
        raise HTTPException(status_code=422, detail=INVALID_STRATEGY_MESSAGE) from exc
    return strategy


def resolve_strategy(service: StrategyService, slug: str | None) -> Strategy:
    """The strategy a scan, analysis or schedule names (``None``: ``smc-default``). Unknown is
    422, an unreadable store 503, a stored strategy whose conditions no longer resolve 422."""
    try:
        found = service.resolve(slug)
    except StrategyNotFoundError as exc:
        raise HTTPException(status_code=422, detail=UNKNOWN_STRATEGY_MESSAGE) from exc
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    return checked_conditions(found)
