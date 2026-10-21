"""Response models shared by the routes (the generated client is built from these)."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from smc_scanner.ai.analyst import (
    DEFAULT_MAX_ROWS,
    DEFAULT_MIN_SCORE,
)
from smc_scanner.ai.analyst import Status as AiStatus
from smc_scanner.ai.verdict import AiVerdict
from smc_scanner.ai_cli import MAX_NOTE_CHARS
from smc_scanner.api.constants import (
    MAX_AI_MIN_SCORE,
    MAX_AI_ROWS,
    MAX_CURSOR_CHARS,
    MAX_LABEL_CHARS,
    MAX_SYMBOLS,
)
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
from smc_scanner.models import Bias, ScanRow, Status


class ErrorResponse(BaseModel):
    """Body of every error response."""

    success: Literal[False] = False
    error: str


RETRY_AFTER_HEADER: dict[str, Any] = {
    "Retry-After": {"description": "Seconds to wait before retrying", "schema": {"type": "integer"}}
}


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or wrong internal key"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
    503: {"model": ErrorResponse, "description": "No symbol could be loaded"},
}


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ScanRowOut(BaseModel):
    instrument: str
    status: Status
    zone: str
    zone_low: float
    zone_high: float
    price: float
    dist_atr: float
    bias: Bias
    in_ote: bool
    trendline_ok: bool
    ob_fvg: bool
    score: int
    zone_age: int
    prior_touches: int
    bar_time: str = Field(max_length=MAX_LABEL_CHARS)

    @classmethod
    def from_row(cls, row: ScanRow) -> "ScanRowOut":
        return cls.model_validate(row, from_attributes=True)


class ScanFailureOut(BaseModel):
    symbol: str = Field(max_length=MAX_LABEL_CHARS)
    error: str


class ScanResponse(BaseModel):
    source: ApiSource
    tf: Timeframe
    count: int
    rows: list[ScanRowOut]
    failures: list[ScanFailureOut]


class AiResultOut(BaseModel):
    """What the analyst did with one row: its status, the verdict if there is one, a short note."""

    status: AiStatus
    verdict: AiVerdict | None
    note: str = Field(max_length=MAX_NOTE_CHARS)


class AnalysedRowOut(ScanRowOut):
    """A scan row plus its AI result. A subclass rather than a nullable field on ``ScanRowOut``,
    which ``/scan`` also returns and where it would always be null."""

    ai: AiResultOut


class AnalyseRequest(BaseModel):
    """The ``/scan`` parameters as a JSON body, plus the analyst's knobs."""

    model_config = ConfigDict(extra="forbid")

    source: ApiSource = "mt5"
    tf: Timeframe = DEFAULT_TIMEFRAME
    symbols: (
        Annotated[
            list[Annotated[str, Field(max_length=32)]], Field(min_length=1, max_length=MAX_SYMBOLS)
        ]
        | None
    ) = None
    bars: int = Field(default=DEFAULT_BARS, ge=MIN_BARS, le=MAX_BARS)
    swing: int = Field(default=DEFAULT_SWING_LENGTH, ge=1, le=MAX_SWING_LENGTH)
    near: float = Field(default=DEFAULT_NEAR_ATR, ge=0, le=MAX_NEAR_ATR)
    all_touches: bool = False
    provider: Literal["claude"] | None = None
    min_score: int = Field(default=DEFAULT_MIN_SCORE, ge=0, le=MAX_AI_MIN_SCORE)
    max_rows: int = Field(default=DEFAULT_MAX_ROWS, ge=1, le=MAX_AI_ROWS)


class AnalyseResponse(BaseModel):
    source: ApiSource
    tf: Timeframe
    count: int
    rows: list[AnalysedRowOut]
    failures: list[ScanFailureOut]


class AnalysisOut(BaseModel):
    """One stored analysis. The context, token counts and error text stay in the database."""

    id: int
    created_at: str = Field(max_length=MAX_LABEL_CHARS)
    symbol: str
    tf: str = Field(max_length=MAX_LABEL_CHARS)
    zone_kind: str = Field(max_length=MAX_LABEL_CHARS)
    zone: str = Field(max_length=MAX_LABEL_CHARS)
    zone_low: float
    zone_high: float
    bar_time: str
    provider: str = Field(max_length=MAX_LABEL_CHARS)
    model: str = Field(max_length=MAX_LABEL_CHARS)
    prompt_version: str = Field(max_length=MAX_LABEL_CHARS)
    attempts: int
    status: Literal["ok", "failed"]
    verdict: AiVerdict | None


class AnalysisPage(BaseModel):
    items: list[AnalysisOut]
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)


class ScanDefaults(BaseModel):
    source: ApiSource
    tf: Timeframe
    bars: int
    swing: int
    near: float


class ScanLimits(BaseModel):
    min_bars: int
    max_bars: int
    max_swing: int
    max_near: float
    max_symbols: int


class ConfigResponse(BaseModel):
    """What the scan form needs: choices, defaults, limits and the watchlist per source."""

    sources: list[ApiSource]
    timeframes: list[Timeframe]
    defaults: ScanDefaults
    limits: ScanLimits
    watchlist: dict[str, list[str]]
    ai_enabled: bool  # an AI provider key is set; only the flag, never the key or its name
    telegram_enabled: bool  # a Telegram bot token is set; only the flag
