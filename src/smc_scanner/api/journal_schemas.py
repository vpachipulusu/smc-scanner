"""Response models for the journal routes. Request bodies are the journal's own models."""

from datetime import datetime

from pydantic import BaseModel, Field

from smc_scanner.api.constants import MAX_JOURNAL_CURSOR_CHARS
from smc_scanner.journal.models import JournalEntryOut


class JournalPage(BaseModel):
    """One page of entries, newest ``opened_at`` first."""

    items: list[JournalEntryOut]
    next_cursor: str | None = Field(
        default=None,
        max_length=MAX_JOURNAL_CURSOR_CHARS,
        description="Pass back as ``cursor`` for the next page; null on the last page",
    )


class JournalStatsOut(BaseModel):
    """Aggregates over closed trades, in R (profit divided by the initial risk). Open trades are
    counted in ``open_trades`` only. Ratios are null while there is nothing to average."""

    closed_trades: int
    open_trades: int
    wins: int = Field(description="Closed trades with R above zero")
    losses: int = Field(description="Closed trades with R below zero")
    breakeven: int = Field(description="Closed trades with R of exactly zero")
    win_rate: float | None = Field(description="wins / closed_trades, between 0 and 1")
    average_r: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    expectancy: float | None = Field(description="Expected R per trade; equals average_r")
    total_r: float


class CumulativePointOut(BaseModel):
    """The running R total after one closed trade."""

    entry_id: int
    closed_at: datetime
    r: float = Field(description="R of this trade")
    cumulative_r: float


class JournalStatsResponse(BaseModel):
    summary: JournalStatsOut
    cumulative: list[CumulativePointOut] = Field(
        description="One point per closed trade, in close order"
    )
