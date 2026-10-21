"""Which currencies move an instrument: an explicit map for indices, metals, energy and crypto,
and the two legs of a six-letter FX pair. Unknown symbols map to no currency."""

import re
from typing import Final

from smc_scanner.econ_calendar.models import CURRENCIES

# Broker decorations: ``EURUSD.r``, ``EURUSD#``, ``EURUSD-ecn``, ``EURUSD_i``.
_SUFFIX_SPLIT: Final = re.compile(r"[._#@-]")
_PAIR_LENGTH: Final = 6

SYMBOL_CURRENCIES: Final[dict[str, tuple[str, ...]]] = {
    # US indices
    "USTEC": ("USD",),
    "US100": ("USD",),
    "NAS100": ("USD",),
    "US30": ("USD",),
    "DJ30": ("USD",),
    "US500": ("USD",),
    "SPX500": ("USD",),
    # other indices
    "GER40": ("EUR",),
    "DE40": ("EUR",),
    "DAX40": ("EUR",),
    "FRA40": ("EUR",),
    "EU50": ("EUR",),
    "UK100": ("GBP",),
    "JP225": ("JPY",),
    "AUS200": ("AUD",),
    # metals, energy, crypto: priced in dollars
    "XAUUSD": ("USD",),
    "XAGUSD": ("USD",),
    "USOIL": ("USD",),
    "UKOIL": ("USD",),
    "BTCUSD": ("USD",),
    "ETHUSD": ("USD",),
}


def currencies_for(symbol: str) -> tuple[str, ...]:
    """The currencies whose news affects ``symbol``, base first; empty when it is unknown."""
    base = _SUFFIX_SPLIT.split(symbol.strip().upper(), maxsplit=1)[0]
    mapped = SYMBOL_CURRENCIES.get(base)
    if mapped is not None:
        return mapped
    if len(base) < _PAIR_LENGTH:
        return ()
    first, second = base[:3], base[3:_PAIR_LENGTH]
    if first not in CURRENCIES or second not in CURRENCIES:
        return ()
    return (first,) if first == second else (first, second)
