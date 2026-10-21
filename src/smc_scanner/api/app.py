"""The FastAPI app: lifespan, exception handlers, middleware and the routers."""

import logging
import os
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from smc_scanner import __version__
from smc_scanner.ai.budget import (
    CALLS_ENV,
    COST_ENV,
)
from smc_scanner.api import deps
from smc_scanner.api.constants import (
    BIND_HOST_ENVS,
    DEFAULT_ALLOWED_HOSTS,
    INTERNAL_ERROR_MESSAGE,
    INTERNAL_KEY_ENV,
    INVALID_REQUEST_MESSAGE,
    LOOPBACK_HOSTS,
    SCHEDULER_ENV,
    SCHEDULER_FALSY,
    SCHEDULER_TRUTHY,
)
from smc_scanner.api.routes import analyses, calendar, journal, scan, schedules
from smc_scanner.api.schemas import ERROR_RESPONSES

log = logging.getLogger(__name__)
load_dotenv()


def _operation_id(route: APIRoute) -> str:
    """``health``, ``config``, ``scan``: the generated SDK function names."""
    return route.name


def _allowed_hosts() -> list[str]:
    raw = os.environ.get("SMC_API_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)
    return [host.strip() for host in raw.split(",") if host.strip()]


def _error_response(
    status_code: int, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
        headers=None if headers is None else dict(headers),
    )


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Error"
    return _error_response(exc.status_code, message, exc.headers)


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    log.info("invalid request: %s", exc.errors())
    return _error_response(422, INVALID_REQUEST_MESSAGE)


async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled exception", exc_info=exc)
    return _error_response(500, INTERNAL_ERROR_MESSAGE)


def _scheduler_enabled() -> bool:
    value = os.environ.get(SCHEDULER_ENV, "").strip().lower()
    if value and value not in SCHEDULER_TRUTHY and value not in SCHEDULER_FALSY:
        log.warning("%s has an unrecognised value, the scheduler stays off", SCHEDULER_ENV)
    return value in SCHEDULER_TRUTHY


def _is_loopback(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


def _argv_host(argv: Sequence[str]) -> str:
    """The value of a ``--host`` flag in a launcher's command line, or ""."""
    for index, arg in enumerate(argv):
        if arg == "--host" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--host="):
            return arg.removeprefix("--host=")
    return ""


def startup_warnings(env: Mapping[str, str], argv: Sequence[str] = ()) -> list[str]:
    """Configuration worth a log line at startup. Names variables only, never their values.

    The server cannot see its own bind address, so "exposed" means a launcher said so
    (``SMC_API_HOST`` / ``UVICORN_HOST`` / a ``--host`` flag in ``argv``) or
    ``SMC_API_ALLOWED_HOSTS`` lists a non-loopback name.
    """
    warnings: list[str] = []
    named = [env.get(name, "") for name in BIND_HOST_ENVS]
    named += [_argv_host(argv), *env.get("SMC_API_ALLOWED_HOSTS", "").split(",")]
    exposed = any(host.strip() and not _is_loopback(host) for host in named)
    if exposed and not env.get(INTERNAL_KEY_ENV, ""):
        warnings.append(
            f"{INTERNAL_KEY_ENV} is not set but the API is reachable beyond loopback: "
            "anyone who can reach it can scan and spend AI budget"
        )
    if not env.get(CALLS_ENV, "").strip() and not env.get(COST_ENV, "").strip():
        warnings.append(f"neither {CALLS_ENV} nor {COST_ENV} is set: AI spend is unlimited")
    return warnings


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the scheduler for the life of the app when ``SMC_SCHEDULER`` is on (off by default).
    A fresh service is built per startup, so start-stop-start works."""
    for warning in startup_warnings(os.environ, sys.argv):
        log.warning("%s", warning)
    if not _scheduler_enabled():
        yield
        return
    if os.environ.get("WEB_CONCURRENCY", "1").strip() not in {"", "1"}:
        log.warning("%s with several workers: every worker would scan and alert", SCHEDULER_ENV)
    # misconfiguration fails startup loudly: the user opted in. That includes an invalid
    # AI_MAX_* cap (the message names the variable); caps are read once here, so a changed
    # value reaches scheduled runs after a restart, while /analyse reads them per request.
    service = deps._build_scheduler()  # looked up per start, so tests can swap it
    try:
        service.start()
        yield
    finally:
        service.stop()


app = FastAPI(
    lifespan=_lifespan,
    title="SMC scanner",
    version=__version__,
    description="Screens a watchlist for price touching or near fresh order blocks and "
    "fair value gaps. Read-only; it never places trades.",
    generate_unique_id_function=_operation_id,
    responses=ERROR_RESPONSES,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, _unhandled_handler)
for module in (
    scan,
    analyses,
    schedules,
    journal,
    calendar,
):  # registration order is the OpenAPI path order
    app.include_router(module.router)
