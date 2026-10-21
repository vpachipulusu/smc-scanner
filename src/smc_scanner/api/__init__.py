"""FastAPI wrapper over ``run_scan`` for the Next.js frontend (``nextjs-frontend/``).

    uvicorn smc_scanner.api:app --host 127.0.0.1 --port 8000

Only the Next.js *server* calls this API (the browser never does), the same split as
StoreCart: no CORS, loopback-only hosts (``SMC_API_ALLOWED_HOSTS``, default
``127.0.0.1,localhost``), and an optional shared key. When ``SMC_INTERNAL_KEY`` is set,
``/scan`` and ``/config`` require it in ``X-Internal-Key``; unset means open on loopback,
which is fine for a single-user machine.

Every error body is ``{"success": false, "error": "..."}`` so the generated TypeScript
client and the frontend's ``callBackend`` see one shape. Sources are ``mt5`` and ``demo``;
the csv source takes file paths, so it is CLI-only. Scans are serialised with a lock
because the MT5 connection is process-wide.

Run a single worker: the scan lock, run guard, cooldowns, rate limits and AI budget
reservations are process-local. ``POST /analyse`` and ``GET /scan`` are rate limited per endpoint
(429 with ``Retry-After``); AI calls are capped per UTC day by ``AI_MAX_CALLS_PER_DAY`` and
``AI_MAX_COST_PER_DAY`` (429 once reached, unset means unlimited).

Layout: ``app`` (app, lifespan, handlers), ``deps`` (injected dependencies and the shared
process-wide state), ``routes/`` (one router per area), ``schemas`` / ``schedule_schemas``
(models). This module re-exports what tests and other modules import from ``smc_scanner.api``.
Re-exports are read-only aliases: monkeypatch a name on the module that defines and uses it
(``deps``, ``routes.schedules``, ...), not on this package.
"""

from smc_scanner.api.app import _scheduler_enabled, app, startup_warnings
from smc_scanner.api.constants import (
    ANALYSE_LOCK_POLL_SECONDS,
    INTERNAL_KEY_ENV,
    INTERNAL_KEY_HEADER,
    RATE_LIMIT_MESSAGE,
    RUN_COOLDOWN_MESSAGE,
    RUN_NOW_COOLDOWN_SECONDS,
    SCHEDULER_ENV,
)
from smc_scanner.api.deps import (
    RATE_LIMITERS,
    _analyse_lock,
    _build_run_deps,
    _build_scheduler,
    _request_run_deps,
    _run_guard,
    _scan_lock,
    get_provider_factory,
    get_run_deps_factory,
    get_telegram_sender,
    reset_rate_limits,
)
from smc_scanner.api.routes.analyses import _note
from smc_scanner.api.routes.schedules import _run_now_at
from smc_scanner.api.schedule_schemas import Frequency

__all__ = [
    "ANALYSE_LOCK_POLL_SECONDS",
    "INTERNAL_KEY_ENV",
    "INTERNAL_KEY_HEADER",
    "RATE_LIMITERS",
    "RATE_LIMIT_MESSAGE",
    "RUN_COOLDOWN_MESSAGE",
    "RUN_NOW_COOLDOWN_SECONDS",
    "SCHEDULER_ENV",
    "Frequency",
    "_analyse_lock",
    "_build_run_deps",
    "_build_scheduler",
    "_note",
    "_request_run_deps",
    "_run_guard",
    "_run_now_at",
    "_scan_lock",
    "_scheduler_enabled",
    "app",
    "get_provider_factory",
    "get_run_deps_factory",
    "get_telegram_sender",
    "reset_rate_limits",
    "startup_warnings",
]
