"""Request helpers shared by the route modules."""

import base64
import binascii
import logging

from fastapi import HTTPException

from smc_scanner.api.constants import (
    CURSOR_PREFIX,
    INVALID_CURSOR_MESSAGE,
    MAX_LABEL_CHARS,
    MAX_ROW_ID,
    MAX_SYMBOLS,
    SYMBOL_PATTERN,
    WATCHLIST_MESSAGE,
)
from smc_scanner.config import (
    ApiSource,
)
from smc_scanner.watchlist import DEFAULT_WATCHLIST, WatchlistError, resolve_symbols

log = logging.getLogger(__name__)


def _symbols(source: ApiSource, raw: str | None) -> list[str]:
    if raw:
        symbols = [part.strip() for part in raw.split(",") if part.strip()]
        if len(symbols) > MAX_SYMBOLS:
            raise HTTPException(status_code=422, detail=f"At most {MAX_SYMBOLS} symbols")
        bad = [symbol for symbol in symbols if not SYMBOL_PATTERN.match(symbol)]
        if bad:
            raise HTTPException(status_code=422, detail=f"Invalid symbol name: {bad[0]!r}")
        return symbols
    try:
        return resolve_symbols(DEFAULT_WATCHLIST, source)
    except WatchlistError as exc:
        log.error("watchlist: %s", exc)
        raise HTTPException(status_code=500, detail=WATCHLIST_MESSAGE) from exc


def _clip(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    return text[:limit]


def _encode_cursor(record_id: int) -> str:
    return base64.urlsafe_b64encode(f"{CURSOR_PREFIX}{record_id}".encode()).decode()


def _decode_cursor(cursor: str) -> int:
    """The id behind an opaque cursor; anything else is a 422."""
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE) from exc
    number = text.removeprefix(CURSOR_PREFIX)
    if not text.startswith(CURSOR_PREFIX) or not number.isascii() or not number.isdigit():
        raise HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE)
    value = int(number)
    if value > MAX_ROW_ID:
        raise HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE)
    return value
