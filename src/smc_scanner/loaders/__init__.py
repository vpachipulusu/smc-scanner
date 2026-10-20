"""Candle sources. ``make_loader`` picks one by name; every loader satisfies ``Loader``."""

from smc_scanner.config import SOURCES
from smc_scanner.loaders.base import Loader, LoaderError, normalise


def make_loader(source: str, closed_only: bool = True) -> Loader:
    if source == "mt5":
        from smc_scanner.loaders.mt5 import Mt5Loader

        return Mt5Loader(closed_only=closed_only)
    if source == "csv":
        from smc_scanner.loaders.csv_loader import CsvLoader

        return CsvLoader()
    if source == "demo":
        from smc_scanner.loaders.demo import DemoLoader

        return DemoLoader()
    raise LoaderError(f"unknown source {source!r}; expected one of {', '.join(SOURCES)}")


__all__ = ["Loader", "LoaderError", "make_loader", "normalise"]
