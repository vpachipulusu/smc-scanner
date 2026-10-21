"""Limits, messages and settings shared by the API modules."""

import re
from typing import Any

from smc_scanner.config import (
    ApiSource,
)

API_SOURCES: tuple[ApiSource, ...] = ("mt5", "demo")
MAX_SYMBOLS = 50
MAX_SYMBOLS_QUERY_LENGTH = 1000
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9._#@\-]{1,32}$")
DEFAULT_ALLOWED_HOSTS = "127.0.0.1,localhost"
INTERNAL_KEY_HEADER = "X-Internal-Key"
INTERNAL_KEY_ENV = "SMC_INTERNAL_KEY"
SCHEDULER_ENV = "SMC_SCHEDULER"
SCHEDULER_TRUTHY = frozenset({"1", "true", "yes", "on"})
SCHEDULER_FALSY = frozenset({"0", "false", "no", "off"})
ANALYSE_LOCK_POLL_SECONDS = 1.0

INVALID_REQUEST_MESSAGE = "Invalid request"
INTERNAL_ERROR_MESSAGE = "Internal server error"
NOTHING_LOADED_MESSAGE = "No symbol could be loaded; see the scanner log"
WATCHLIST_MESSAGE = "Watchlist is missing or invalid"
STORE_UNAVAILABLE_MESSAGE = "Analysis database unavailable"
AI_FAILED_MESSAGE = "AI provider failed"
NOT_FOUND_MESSAGE = "Analysis not found"
INVALID_CURSOR_MESSAGE = "Invalid cursor"

AI_PROVIDER_NAME = "claude"  # the only provider the API offers; the fake one is CLI/demo-only
MAX_AI_MIN_SCORE = 4
MAX_AI_ROWS = 20
DEFAULT_ANALYSES_LIMIT = 50
MAX_ANALYSES_LIMIT = 200
MAX_CURSOR_CHARS = 64
MAX_LABEL_CHARS = 100
MAX_ROW_ID = 2**63 - 1  # SQLite INTEGER; larger ids would overflow the driver
AI_UNAVAILABLE_MESSAGE = "AI analysis is unavailable; see the server log"
BUDGET_MESSAGE = "The daily AI budget is used up; try again after it resets"
BUDGET_CONFIG_MESSAGE = "AI budget settings are invalid; see the server log"
RATE_LIMIT_MESSAGE = "Too many requests; try again shortly"
SCAN_RATE_LIMIT = (20, 60.0)  # requests, per window seconds
ANALYSE_RATE_LIMIT = (6, 60.0)  # each run can spend money, so it is the tightest
BIND_HOST_ENVS = ("SMC_API_HOST", "UVICORN_HOST")  # where a launcher can say what it binds to
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
CURSOR_PREFIX = "id:"

SCHEDULE_NOT_FOUND_MESSAGE = "Schedule not found"
SCHEDULE_LIMIT_MESSAGE = "Schedule limit reached"
SCHEDULE_STORE_MESSAGE = "Schedule database unavailable"
ALREADY_RUNNING_MESSAGE = "This schedule is already running"
SCAN_IN_PROGRESS_MESSAGE = "A scan is already in progress"
STOPPING_MESSAGE = "The scheduler is shutting down"
TELEGRAM_FAILED_MESSAGE = "Telegram rejected the test message"
RUN_UNAVAILABLE_MESSAGE = "Run setup is invalid; see the server log"
TELEGRAM_COOLDOWN_MESSAGE = "A test message was sent a moment ago; try again shortly"
TELEGRAM_TEST_COOLDOWN_SECONDS = 5.0
RUN_NOW_COOLDOWN_SECONDS = 10.0
RUN_COOLDOWN_MESSAGE = "This schedule was run a moment ago; try again shortly"
_OMITTED: Any = None  # default of PATCH fields that are omittable but not nullable
DEFAULT_SCHEDULE_MIN_SCORE = 2
DEFAULT_LOGS_LIMIT = 50
MAX_LOGS_LIMIT = 100  # one below the job log's own cap, because one extra row detects "more"
RUN_NOW_LOCK_TIMEOUT_SECONDS = 0.0  # run-now answers 409 at once instead of queueing behind a scan
CHAT_ID_REGEX = r"^(?:-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$"

JOURNAL_RATE_LIMIT = (120, 60.0)  # every journal route; no money is spent
JOURNAL_STATS_RATE_LIMIT = (10, 60.0)  # stats read and parse every closed row
JOURNAL_NOT_FOUND_MESSAGE = "Journal entry not found"
JOURNAL_LIMIT_MESSAGE = "Journal entry limit reached"
JOURNAL_STORE_MESSAGE = "Journal database unavailable"
DEFAULT_JOURNAL_LIMIT = 50
MAX_JOURNAL_LIMIT = 100
MAX_JOURNAL_CURSOR_CHARS = 96
