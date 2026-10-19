"""Thin FastAPI wrapper over ``run_scan``: ``GET /scan`` returns the same rows as the CLI
as JSON. Runs on the Windows machine that has the MT5 terminal.

    uvicorn smc_scanner.api:app --host 127.0.0.1 --port 8000

Bind to loopback only: there is no authentication. Hosts other than those in
``SMC_API_ALLOWED_HOSTS`` (default ``127.0.0.1,localhost``) are rejected. Sources are
``mt5`` and ``demo``; the csv source takes file paths, so it is CLI-only. Scans are
serialised with a lock because the MT5 connection is process-wide.
"""

import logging
import os
import re
import threading
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from smc_scanner import __version__
from smc_scanner.config import (
    DEFAULT_BARS,
    DEFAULT_NEAR_ATR,
    DEFAULT_SWING_LENGTH,
    DEFAULT_TIMEFRAME,
    MAX_BARS,
    MAX_NEAR_ATR,
    MAX_SWING_LENGTH,
    MIN_BARS,
    ApiSource,
    Timeframe,
)
from smc_scanner.loaders import make_loader
from smc_scanner.report import rows_to_dicts
from smc_scanner.scanner import ScanOptions, run_scan
from smc_scanner.watchlist import DEFAULT_WATCHLIST, WatchlistError, resolve_symbols

log = logging.getLogger(__name__)
load_dotenv()

MAX_SYMBOLS = 50
MAX_SYMBOLS_QUERY_LENGTH = 1000
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9._#@\-]{1,32}$")
DEFAULT_ALLOWED_HOSTS = "127.0.0.1,localhost"

_scan_lock = threading.Lock()

app = FastAPI(
    title="SMC scanner",
    version=__version__,
    description="Screens a watchlist for price touching or near fresh order blocks and "
    "fair value gaps. Read-only; it never places trades.",
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        host.strip()
        for host in os.environ.get("SMC_API_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS).split(",")
        if host.strip()
    ],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def _symbols(source: str, raw: str | None) -> list[str]:
    if raw:
        symbols = [part.strip() for part in raw.split(",") if part.strip()]
        if len(symbols) > MAX_SYMBOLS:
            raise HTTPException(status_code=422, detail=f"at most {MAX_SYMBOLS} symbols")
        bad = [symbol for symbol in symbols if not SYMBOL_PATTERN.match(symbol)]
        if bad:
            raise HTTPException(status_code=422, detail=f"invalid symbol name: {bad[0]!r}")
        return symbols
    try:
        return resolve_symbols(DEFAULT_WATCHLIST, source)
    except WatchlistError as exc:
        log.error("watchlist: %s", exc)
        raise HTTPException(status_code=500, detail="watchlist is missing or invalid") from exc


@app.get("/scan")
def scan(
    source: ApiSource = "mt5",
    tf: Timeframe = DEFAULT_TIMEFRAME,
    symbols: Annotated[
        str | None,
        Query(
            description="comma-separated; default watchlist", max_length=MAX_SYMBOLS_QUERY_LENGTH
        ),
    ] = None,
    bars: Annotated[int, Query(ge=MIN_BARS, le=MAX_BARS)] = DEFAULT_BARS,
    swing: Annotated[int, Query(ge=1, le=MAX_SWING_LENGTH)] = DEFAULT_SWING_LENGTH,
    near: Annotated[float, Query(ge=0, le=MAX_NEAR_ATR)] = DEFAULT_NEAR_ATR,
    all_touches: bool = False,
) -> dict[str, object]:
    """Scan the given symbols (or the watchlist) on one timeframe.

    503 when no symbol could be loaded at all (terminal down, bad login); otherwise the
    per-symbol failures are listed next to the rows.
    """
    options = ScanOptions(swing_length=swing, near_atr=near, all_touches=all_touches)
    wanted = _symbols(source, symbols)
    with _scan_lock:
        result = run_scan(make_loader(source), wanted, tf, bars, options)
    if result.all_failed:
        raise HTTPException(status_code=503, detail="no symbol could be loaded; see server log")
    return {
        "source": source,
        "tf": tf,
        "count": len(result.rows),
        "rows": rows_to_dicts(result.rows),
        "failures": [{"symbol": f.symbol, "error": f.error} for f in result.failures],
    }
