"""Watchlist file: ``{source: [symbols]}`` in YAML, e.g. ``mt5: [EURUSD, XAUUSD]``."""

import os
from pathlib import Path

import yaml

from smc_scanner.config import DEFAULT_DEMO_SYMBOLS, SOURCES

# Relative to the working directory unless SMC_WATCHLIST points somewhere explicit.
DEFAULT_WATCHLIST = Path(os.environ.get("SMC_WATCHLIST", "watchlist.yaml"))


class WatchlistError(Exception):
    pass


def load_watchlist(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        raise WatchlistError(f"watchlist not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WatchlistError(f"{path}: invalid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise WatchlistError(f"{path}: expected a mapping of source -> list of symbols")
    result: dict[str, list[str]] = {}
    for source, symbols in data.items():
        if source not in SOURCES:
            raise WatchlistError(f"{path}: unknown source {source!r}")
        if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
            raise WatchlistError(f"{path}: {source} must be a list of symbol strings")
        result[str(source)] = [s.strip() for s in symbols if s.strip()]
    return result


def symbols_for(watchlist: dict[str, list[str]], source: str) -> list[str]:
    symbols = watchlist.get(source, [])
    if not symbols:
        raise WatchlistError(f"no symbols listed for source {source!r}")
    return symbols


def resolve_symbols(path: Path, source: str) -> list[str]:
    """Symbols for ``source`` from the watchlist file.

    The demo source needs no file: without one, or without a ``demo`` entry, it uses the
    built-in demo symbols.
    """
    if source == "demo" and not path.is_file():
        return list(DEFAULT_DEMO_SYMBOLS)
    watchlist = load_watchlist(path)
    if source == "demo" and "demo" not in watchlist:
        return list(DEFAULT_DEMO_SYMBOLS)
    return symbols_for(watchlist, source)
