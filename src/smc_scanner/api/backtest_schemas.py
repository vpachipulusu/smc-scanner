"""Request and response models of the backtest routes."""

import logging
from typing import Annotated, Any, Literal

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from smc_scanner.api.constants import (
    MAX_BACKTEST_SEED,
    MAX_BACKTEST_STRIDE,
    MAX_LABEL_CHARS,
    MAX_ROW_ID,
    MAX_SYMBOLS,
    SYMBOL_PATTERN,
)
from smc_scanner.api.strategy_schemas import StrategySlug
from smc_scanner.backtest.jobs import MAX_TRAIN_FRACTION, MIN_TRAIN_FRACTION, baselines_of
from smc_scanner.backtest.outcome import MAX_ATR_MULTIPLE, MAX_RR, MAX_SPREAD, ExitRules
from smc_scanner.backtest.store import BacktestRecord, BacktestStatus, JsonObject, Verdict
from smc_scanner.backtest.walkforward import DEFAULT_TRAIN_FRACTION, SplitKind
from smc_scanner.config import DEFAULT_BARS, DEFAULT_TIMEFRAME, MAX_BARS, MIN_BARS, Timeframe

log = logging.getLogger(__name__)

_MAX_LOGGED_ERROR_CHARS = 500
BacktestId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]
SymbolName = Annotated[str, Field(pattern=SYMBOL_PATTERN.pattern)]
_DEFAULT_RULES = ExitRules()


class ExitRulesIn(BaseModel):
    """How a signal becomes a trade, within ``ExitRules``'s limits. ``spread`` is in price
    units, paid once per trade."""

    model_config = ConfigDict(extra="forbid", strict=True)

    rr: float = Field(default=_DEFAULT_RULES.rr, gt=0, le=MAX_RR, allow_inf_nan=False)
    stop_buffer_atr: float = Field(
        default=_DEFAULT_RULES.stop_buffer_atr, ge=0, le=MAX_ATR_MULTIPLE, allow_inf_nan=False
    )
    time_stop_bars: int = Field(default=_DEFAULT_RULES.time_stop_bars, ge=1, le=MAX_BARS)
    spread: float = Field(default=_DEFAULT_RULES.spread, ge=0, le=MAX_SPREAD, allow_inf_nan=False)
    min_risk_atr: float = Field(
        default=_DEFAULT_RULES.min_risk_atr, ge=0, le=MAX_ATR_MULTIPLE, allow_inf_nan=False
    )

    def to_rules(self) -> ExitRules:
        return ExitRules(**self.model_dump())


class BacktestCreate(BaseModel):
    """A backtest to run in the background. ``source`` is demo or mt5 only: the API never takes
    file paths. Without ``symbols`` the source's watchlist is used; duplicates are dropped."""

    model_config = ConfigDict(extra="forbid", strict=True)

    strategy: StrategySlug
    source: Literal["mt5", "demo"]
    tf: Timeframe = DEFAULT_TIMEFRAME
    bars: int = Field(default=DEFAULT_BARS, ge=MIN_BARS, le=MAX_BARS)
    symbols: Annotated[list[SymbolName], Field(min_length=1, max_length=MAX_SYMBOLS)] | None = None
    rules: ExitRulesIn = Field(default_factory=ExitRulesIn)
    split: SplitKind = "time"
    train_fraction: float = Field(
        default=DEFAULT_TRAIN_FRACTION,
        ge=MIN_TRAIN_FRACTION,
        le=MAX_TRAIN_FRACTION,
        allow_inf_nan=False,
    )
    seed: int = Field(default=0, ge=0, le=MAX_BACKTEST_SEED)
    stride: int = Field(default=1, ge=1, le=MAX_BACKTEST_STRIDE)

    @field_validator("symbols")
    @classmethod
    def _unique(cls, symbols: list[str] | None) -> list[str] | None:
        return None if symbols is None else list(dict.fromkeys(symbols))


class BacktestStatsOut(BaseModel):
    """``BacktestStats``: R-based statistics of the closed trades; ratios are null at n = 0."""

    n: int
    n_open: int
    n_void: int
    low_sample: bool
    hit_rate: float | None
    average_r: float | None
    expectancy_r: float | None
    median_r: float | None
    best_r: float | None
    worst_r: float | None
    total_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None
    avg_bars_held: float | None
    ci_low: float | None
    ci_high: float | None


class BacktestResultsOut(BaseModel):
    """The stored statistics: in-sample and out-of-sample, the null baselines on the
    out-of-sample part (keyed ``random`` and ``flipped``), and pooled over the whole run (only
    in CLI runs). Parts the run did not produce are null."""

    pooled: BacktestStatsOut | None = None
    in_sample: BacktestStatsOut | None = None
    out_of_sample: BacktestStatsOut | None = None
    baselines: dict[str, BacktestStatsOut] | None = None

    @classmethod
    def from_stats(cls, stats: JsonObject | None) -> "BacktestResultsOut | None":
        """The typed view of a row's stats JSON, or None (logged) when it does not fit."""
        if stats is None:
            return None
        try:
            return cls.model_validate({**stats, "baselines": baselines_of(stats) or None})
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False, include_context=False)
            shown = str(errors)[:_MAX_LOGGED_ERROR_CHARS]
            log.error("stored backtest stats do not fit the schema: %s", shown)
            return None


class ExitRulesOut(BaseModel):
    rr: float
    stop_buffer_atr: float
    time_stop_bars: int
    spread: float
    min_risk_atr: float


def _rules_out(rules: dict[str, Any]) -> ExitRulesOut | None:
    try:
        return ExitRulesOut.model_validate(rules)
    except ValidationError:
        log.error("stored backtest rules do not fit the schema")
        return None


class BacktestOut(BaseModel):
    """One backtest row. ``status`` goes pending, running, then done or failed; ``results`` and
    ``verdict`` are set once done, ``error`` (a fixed message) once failed."""

    id: int
    created_at: str = Field(max_length=MAX_LABEL_CHARS)
    strategy: str
    source: str
    tf: str
    bars: int
    symbols: list[str]
    rules: ExitRulesOut | None
    split: str
    train_fraction: float | None
    seed: int
    stride: int
    status: BacktestStatus
    verdict: Verdict | None
    duration_seconds: float | None
    error: str | None
    results: BacktestResultsOut | None

    @classmethod
    def from_record(cls, record: BacktestRecord) -> "BacktestOut":
        return cls(
            id=record.id,
            created_at=record.created_at,
            strategy=record.strategy,
            source=record.source,
            tf=record.timeframe,
            bars=record.bars,
            symbols=list(record.symbols),
            rules=_rules_out(record.rules),
            split=record.split,
            train_fraction=record.train_fraction,
            seed=record.seed,
            stride=record.stride,
            status=record.status,
            verdict=record.verdict,
            duration_seconds=record.duration_seconds,
            error=record.error,
            results=BacktestResultsOut.from_stats(record.stats),
        )


class BacktestSummaryOut(BaseModel):
    """The badge of a strategy's latest finished backtest: its verdict and the out-of-sample
    expectancy (the pooled one when the run had no out-of-sample part), with its interval."""

    id: int
    strategy: str
    created_at: str = Field(max_length=MAX_LABEL_CHARS)
    verdict: Verdict | None
    n: int | None
    expectancy_r: float | None
    ci_low: float | None
    ci_high: float | None
    low_sample: bool | None

    @classmethod
    def from_record(cls, record: BacktestRecord) -> "BacktestSummaryOut":
        results = BacktestResultsOut.from_stats(record.stats)
        stats = None if results is None else (results.out_of_sample or results.pooled)
        return cls(
            id=record.id,
            strategy=record.strategy,
            created_at=record.created_at,
            verdict=record.verdict,
            n=None if stats is None else stats.n,
            expectancy_r=None if stats is None else stats.expectancy_r,
            ci_low=None if stats is None else stats.ci_low,
            ci_high=None if stats is None else stats.ci_high,
            low_sample=None if stats is None else stats.low_sample,
        )


class BacktestListItem(BacktestSummaryOut):
    """A row of ``GET /backtests``: the badge figures plus how the run went. The full
    results are on ``GET /backtests/{id}``."""

    status: BacktestStatus
    source: str
    tf: str
    bars: int
    duration_seconds: float | None
    error: str | None

    @classmethod
    def from_record(cls, record: BacktestRecord) -> "BacktestListItem":
        summary = BacktestSummaryOut.from_record(record)
        return cls(
            **summary.model_dump(),
            status=record.status,
            source=record.source,
            tf=record.timeframe,
            bars=record.bars,
            duration_seconds=record.duration_seconds,
            error=record.error,
        )


class BacktestList(BaseModel):
    items: list[BacktestListItem]
