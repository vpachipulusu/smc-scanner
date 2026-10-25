"""A small parameter sweep over one condition, judged out-of-sample only.

Each variant changes the params of one condition (every ref to it, in ``require`` and
``score``) and is run through ``walk_forward``. A ``SweepPoint`` carries the out-of-sample stats,
the baselines and the verdict, never the in-sample stats, so a variant cannot be picked on the
data it was tuned on. Points come back in grid order, unranked, each with the family size
``n_variants``: every point's verdict is judged alone, and the more variants, the likelier one
passes by luck, so a pass must be read against ``n_variants`` (picking the best of k on the test
part is itself a multiple-testing bias). The grid is capped at ``MAX_SWEEP_VALUES`` values per
param and ``MAX_SWEEP_VARIANTS`` variants. Each symbol is loaded once for the whole sweep: a
failed load is remembered too, so every variant sees the same symbols.
"""

import itertools
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Final

import pandas as pd

from smc_scanner.backtest._common import distinct_symbols, json_safe, load_frame
from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.backtest.stats import BacktestStats
from smc_scanner.backtest.walkforward import (
    DEFAULT_TRAIN_FRACTION,
    SplitKind,
    Verdict,
    check_walk_forward_args,
    walk_forward,
)
from smc_scanner.loaders.base import Loader
from smc_scanner.scanner import ScanFailure, ScanOptions
from smc_scanner.strategy.conditions import resolve_all
from smc_scanner.strategy.models import ParamValue, Strategy

MAX_SWEEP_VALUES: Final = 3  # per param
MAX_SWEEP_VARIANTS: Final = 27  # the product over the grid

Params = tuple[tuple[str, ParamValue], ...]  # (name, value) pairs, in grid order


@dataclass(frozen=True)
class SweepPoint:
    """One variant's walk-forward, out-of-sample side only."""

    params: Params  # the swept params of the condition
    n_variants: int  # how many variants the sweep judged: read any pass against it
    verdict: Verdict
    out_of_sample: BacktestStats
    random_baseline: BacktestStats
    flipped_baseline: BacktestStats
    failures: tuple[ScanFailure, ...]

    def to_dict(self) -> dict[str, object]:
        """Strict-JSON data: a non-finite float becomes None; ``params`` is an object."""
        safe: dict[str, object] = json_safe(
            {
                "params": dict(self.params),
                "n_variants": self.n_variants,
                "verdict": self.verdict,
                "out_of_sample": asdict(self.out_of_sample),
                "random_baseline": asdict(self.random_baseline),
                "flipped_baseline": asdict(self.flipped_baseline),
                "failures": [asdict(failure) for failure in self.failures],
            }
        )
        return safe


def _check_values(name: str, values: Sequence[ParamValue]) -> None:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise ValueError(f"grid[{name!r}] must be a list of values")
    if not values:
        raise ValueError(f"grid[{name!r}] must have at least one value")
    if len(values) > MAX_SWEEP_VALUES:
        raise ValueError(f"grid[{name!r}] takes at most {MAX_SWEEP_VALUES} values")
    if not all(isinstance(v, int | float | str) for v in values):  # bool is an int
        raise ValueError(f"grid[{name!r}] values must be numbers, strings or booleans")
    if any(isinstance(v, float) and not math.isfinite(v) for v in values):
        raise ValueError(f"grid[{name!r}] values must be finite")
    if len(set(values)) != len(values):
        raise ValueError(f"grid[{name!r}] has a duplicate value")


def _check_grid(grid: Mapping[str, Sequence[ParamValue]]) -> None:
    if not grid:
        raise ValueError("the grid must name at least one parameter")
    for name, values in grid.items():
        _check_values(name, values)
    variants = math.prod(len(values) for values in grid.values())
    if variants > MAX_SWEEP_VARIANTS:
        raise ValueError(f"the grid makes {variants} variants; at most {MAX_SWEEP_VARIANTS}")


def _retuned(strategy: Strategy, condition: str, params: Params) -> Strategy:
    data = strategy.model_dump()
    for field in ("require", "score"):
        data[field] = [
            {**ref, "params": {**ref["params"], **dict(params)}} if ref["key"] == condition else ref
            for ref in data[field]
        ]
    variant = Strategy.model_validate({**data, "builtin": False})
    resolve_all((*variant.require, *variant.score))  # a bad param value raises here
    return variant


def sweep_variants(
    strategy: Strategy, condition: str, grid: Mapping[str, Sequence[ParamValue]]
) -> tuple[tuple[Params, Strategy], ...]:
    """(swept params, strategy variant) for every grid combination, in grid order. The variant
    keeps the strategy's slug and is never ``builtin``. Raises on a bad grid, a condition the
    strategy does not use, or a param name or value the condition rejects."""
    _check_grid(grid)
    if all(ref.key != condition for ref in (*strategy.require, *strategy.score)):
        raise ValueError(f"condition {condition!r} is not used by the strategy")
    names = tuple(grid)
    combos = (tuple(zip(names, combo, strict=True)) for combo in itertools.product(*grid.values()))
    return tuple((params, _retuned(strategy, condition, params)) for params in combos)


class _CachedLoader:
    """Loads each (symbol, timeframe, bars) once, trimmed to ``bars``, and replays a failed
    load's exception. Never closes the wrapped loader: its owner does."""

    def __init__(self, loader: Loader) -> None:
        self._loader = loader
        self._frames: dict[tuple[str, str, int], pd.DataFrame | Exception] = {}

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        key = (symbol, timeframe, bars)
        if key not in self._frames:
            try:
                self._frames[key] = load_frame(self._loader, symbol, timeframe, bars)
            except Exception as exc:  # noqa: BLE001 - re-raised now and for every later variant
                self._frames[key] = exc
        cached = self._frames[key]
        if isinstance(cached, Exception):
            raise cached.with_traceback(None)  # no traceback piling up per variant
        return cached  # shared across variants: the package never mutates a frame

    def close(self) -> None:
        """A no-op: the wrapped loader belongs to the caller."""


def sweep(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    strategy: Strategy,
    rules: ExitRules,
    *,
    condition: str,
    grid: Mapping[str, Sequence[ParamValue]],
    split: SplitKind,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    options: ScanOptions | None = None,
    seed: int = 0,
    stride: int = 1,
) -> tuple[SweepPoint, ...]:
    """Walk-forward every ``sweep_variants`` variant with the same split and seed. Every
    argument is checked before anything loads."""
    variants = sweep_variants(strategy, condition, grid)
    check_walk_forward_args(bars, seed, stride, strategy, split, train_fraction)
    targets = distinct_symbols(symbols)
    cached = _CachedLoader(loader)
    points: list[SweepPoint] = []
    for params, variant in variants:
        result = walk_forward(
            cached,
            targets,
            timeframe,
            bars,
            variant,
            rules,
            split=split,
            train_fraction=train_fraction,
            options=options,
            seed=seed,
            stride=stride,
        )
        points.append(
            SweepPoint(
                params=params,
                n_variants=len(variants),
                verdict=result.verdict,
                out_of_sample=result.out_of_sample,
                random_baseline=result.random_baseline,
                flipped_baseline=result.flipped_baseline,
                failures=result.failures,
            )
        )
    return tuple(points)
