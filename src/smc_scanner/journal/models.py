"""Pydantic models for manual trade-journal entries.

``JournalEntryIn`` is the validated write shape, ``JournalEntryOut`` adds the stored identity and
timestamps, and ``JournalEntryUpdate`` is a partial patch (only the fields that were sent are
applied, and an explicit ``null`` clears an optional field). Cross-field rules live on
``JournalEntryIn`` only; the store applies a patch to the stored entry and re-validates the
merged result, so an update can never leave an entry that ``JournalEntryIn`` would refuse.
"""

from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_NOTES_CHARS: Final = 2000
SYMBOL_REGEX: Final = r"^[A-Za-z0-9._#@\-]{1,32}$"

Side = Literal["long", "short"]
Timeframe = Literal["5m", "15m", "30m", "1h", "4h", "1d"]  # mirrors config.TIMEFRAMES
Symbol = Annotated[str, StringConstraints(pattern=SYMBOL_REGEX)]
MAX_AMOUNT: Final = 1e12  # keeps R-multiples and sums finite
MAX_ID: Final = 2**63 - 1  # SQLite INTEGER
MIN_RELATIVE_RISK: Final = 1e-6  # |entry - stop| / entry

Price = Annotated[float, Field(gt=0, le=MAX_AMOUNT, allow_inf_nan=False)]
Size = Annotated[float, Field(gt=0, le=MAX_AMOUNT, allow_inf_nan=False)]
Money = Annotated[float, Field(ge=-MAX_AMOUNT, le=MAX_AMOUNT, allow_inf_nan=False)]
Notes = Annotated[str, StringConstraints(max_length=MAX_NOTES_CHARS)]
AnalysisId = Annotated[int, Field(ge=1, le=MAX_ID)]

_REQUIRED_FIELDS: Final = ("symbol", "timeframe", "side", "entry", "stop", "opened_at", "notes")


class JournalEntryIn(BaseModel):
    """One manually recorded trade. ``exit`` and ``closed_at`` are set together or not at all."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    side: Side
    entry: Price
    stop: Price
    exit: Price | None = None
    size: Size | None = None
    pnl_currency: Money | None = None
    opened_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    notes: Notes = ""
    analysis_id: AnalysisId | None = None

    @model_validator(mode="after")
    def _check_trade(self) -> Self:
        if self.side == "long" and self.stop >= self.entry:
            raise ValueError("a long trade needs stop below entry")
        if self.side == "short" and self.stop <= self.entry:
            raise ValueError("a short trade needs stop above entry")
        if abs(self.entry - self.stop) < self.entry * MIN_RELATIVE_RISK:
            raise ValueError("stop is too close to entry")
        if (self.exit is None) != (self.closed_at is None):
            raise ValueError("exit and closed_at must be given together")
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("closed_at must not be before opened_at")
        if self.exit is None and self.pnl_currency is not None:
            raise ValueError("pnl_currency needs a closed trade")
        return self


class JournalEntryOut(JournalEntryIn):
    """A stored entry. Timestamps are aware."""

    id: int
    created_at: AwareDatetime
    updated_at: AwareDatetime


class JournalEntryUpdate(BaseModel):
    """Partial patch: unset fields are kept, ``None`` clears an optional field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol | None = None
    timeframe: Timeframe | None = None
    side: Side | None = None
    entry: Price | None = None
    stop: Price | None = None
    exit: Price | None = None
    size: Size | None = None
    pnl_currency: Money | None = None
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    notes: Notes | None = None
    analysis_id: AnalysisId | None = None

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> Self:
        for name in _REQUIRED_FIELDS:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")
        return self
