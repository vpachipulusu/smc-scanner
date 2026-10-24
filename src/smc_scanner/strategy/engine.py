"""Strategy engine: filter and score zone contexts by a ``Strategy``.

``scanner`` finds the candidate zones (``zone_contexts``) and runs the watchlist loop; this
module decides which zones become rows. It drives the loop by injecting a row producer, so
``scanner`` never imports the strategy package (``strategy.models`` imports ``scanner``).
A ``None`` strategy means ``smc-default``, which reproduces the pre-strategy scan.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Final

import pandas as pd

from smc_scanner.loaders.base import Loader
from smc_scanner.models import Bias, ScanRow, ZoneContext
from smc_scanner.scanner import (
    HtfLookup,
    RowProducer,
    ScanOptions,
    ScanResult,
    context_row,
    latest_bar,
    scan_watchlist,
    zone_contexts,
)
from smc_scanner.strategy.builtin import SMC_DEFAULT
from smc_scanner.strategy.conditions import Condition, resolve_all
from smc_scanner.strategy.models import Strategy

_HTF_KEY: Final = "htf_aligned"


@dataclass(frozen=True)
class _Plan:
    """A strategy with its conditions resolved once, so a bad one fails before any scan."""

    strategy: Strategy
    required: tuple[Condition, ...]
    scored: tuple[Condition, ...]
    needs_htf: bool  # a condition reads the higher-timeframe bias


def _plan(strategy: Strategy) -> _Plan:
    return _Plan(
        strategy,
        resolve_all(strategy.require),
        resolve_all(strategy.score),
        needs_htf=_HTF_KEY in strategy.condition_keys(),
    )


def uses_mtf(strategy: Strategy) -> bool:
    """Whether scanning with ``strategy`` loads the higher timeframe whatever the caller asks:
    its own ``mtf`` flag, or an ``htf_aligned`` condition (which would pass every zone without)."""
    return strategy.mtf or _HTF_KEY in strategy.condition_keys()


def _scan_options(strategy: Strategy, options: ScanOptions | None) -> ScanOptions:
    return options if options is not None else strategy.to_scan_options()


def _row(ctx: ZoneContext, plan: _Plan, symbol: str, price: float, bar_time: str) -> ScanRow | None:
    strategy = plan.strategy
    if ctx.state.zone.kind not in strategy.zone_kinds or ctx.state.status not in strategy.statuses:
        return None
    results: dict[str, bool] = {}
    for condition in plan.required:  # stop at the first failure: the zone is dropped anyway
        results[condition.key] = condition.evaluate(ctx)
        if not results[condition.key]:
            return None
    passed = {condition.key: condition.evaluate(ctx) for condition in plan.scored}
    score = sum(passed.values())
    if score < strategy.min_score:
        return None
    # context_row fills the confluence columns (in_ote, trendline_ok, ob_fvg), which every
    # strategy reports; only its 0-4 score is replaced by the strategy's own.
    base = context_row(ctx, symbol=symbol, price=price, bar_time=bar_time)
    return replace(base, score=score, strategy=strategy.slug, conditions={**results, **passed})


def _apply(
    contexts: Sequence[ZoneContext], plan: _Plan, symbol: str, price: float, bar_time: str
) -> list[ScanRow]:
    rows = (_row(ctx, plan, symbol, price, bar_time) for ctx in contexts)
    return [row for row in rows if row is not None]


def apply_strategy(
    contexts: Sequence[ZoneContext], strategy: Strategy, *, symbol: str, price: float, bar_time: str
) -> list[ScanRow]:
    """Rows for the zones that pass: kind and status allowed, every ``require`` condition true,
    and at least ``min_score`` of the ``score`` conditions true (the row's ``score``)."""
    return _apply(contexts, _plan(strategy), symbol, price, bar_time)


def scan_instrument_with_strategy(
    symbol: str,
    ohlc: pd.DataFrame,
    strategy: Strategy | None = None,
    *,
    options: ScanOptions | None = None,
    htf_bias: Bias | None = None,
) -> list[ScanRow]:
    """``scanner.scan_instrument`` through a strategy. ``options`` overrides the strategy's own
    scan tuning (``Strategy.to_scan_options``), so existing ``ScanOptions`` callers keep theirs.
    ``htf_bias`` is the caller's: None makes ``htf_aligned`` pass."""
    chosen = strategy or SMC_DEFAULT
    plan = _plan(chosen)
    contexts = zone_contexts(symbol, ohlc, _scan_options(chosen, options), htf_bias)
    price, bar_time = latest_bar(ohlc)
    return _apply(contexts, plan, symbol, price, bar_time)


def _producer(plan: _Plan, options: ScanOptions) -> RowProducer:
    def produce(symbol: str, ohlc: pd.DataFrame, htf: HtfLookup) -> list[ScanRow]:
        contexts = zone_contexts(symbol, ohlc, options)
        if contexts and plan.needs_htf:  # otherwise the scanner loads it only for hits
            bias = htf()
            contexts = tuple(replace(ctx, htf_bias=bias) for ctx in contexts)
        price, bar_time = latest_bar(ohlc)
        return _apply(contexts, plan, symbol, price, bar_time)

    return produce


def scan_watchlist_with_strategy(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    strategy: Strategy | None = None,
    *,
    options: ScanOptions | None = None,
    mtf: bool = False,
    require_htf_aligned: bool = False,
    ltf_min_score: int | None = None,
    ltf_max_rows: int | None = None,
) -> ScanResult:
    """``scanner.scan_watchlist`` through a strategy. The strategy's ``mtf`` and
    ``require_htf_aligned`` switch those on in addition to the arguments, and so does an
    ``htf_aligned`` condition (it would pass every zone without the HTF). ``options`` overrides
    the strategy's scan tuning. Unknown conditions or bad params raise before anything loads.
    A higher timeframe that fails to load counts as unknown and passes, as ``htf_allows`` does."""
    chosen = strategy or SMC_DEFAULT
    plan = _plan(chosen)
    scan_options = _scan_options(chosen, options)
    return scan_watchlist(
        loader,
        symbols,
        timeframe,
        bars,
        scan_options,
        mtf=mtf or uses_mtf(chosen),
        require_htf_aligned=require_htf_aligned or chosen.require_htf_aligned,
        ltf_min_score=ltf_min_score,
        ltf_max_rows=ltf_max_rows,
        row_producer=_producer(plan, scan_options),
    )


def run_scan_with_strategy(
    loader: Loader,
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
    strategy: Strategy | None = None,
    *,
    options: ScanOptions | None = None,
    mtf: bool = False,
    require_htf_aligned: bool = False,
    ltf_min_score: int | None = None,
    ltf_max_rows: int | None = None,
) -> ScanResult:
    """``scan_watchlist_with_strategy`` with the loader closed afterwards, whatever happens."""
    try:
        return scan_watchlist_with_strategy(
            loader,
            symbols,
            timeframe,
            bars,
            strategy,
            options=options,
            mtf=mtf,
            require_htf_aligned=require_htf_aligned,
            ltf_min_score=ltf_min_score,
            ltf_max_rows=ltf_max_rows,
        )
    finally:
        loader.close()
