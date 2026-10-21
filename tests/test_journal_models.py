"""Journal models: field limits, side/stop geometry, exit/closed consistency."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from smc_scanner.journal.models import (
    MAX_NOTES_CHARS,
    JournalEntryIn,
    JournalEntryUpdate,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def raw(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": "EURUSD",
        "timeframe": "1h",
        "side": "long",
        "entry": 1.1000,
        "stop": 1.0950,
        "opened_at": T0,
    }
    return {**base, **changes}


def test_open_long_entry_is_valid() -> None:
    entry = JournalEntryIn(**raw())
    assert entry.exit is None and entry.closed_at is None and entry.notes == ""


def test_closed_short_entry_is_valid() -> None:
    entry = JournalEntryIn(
        **raw(side="short", entry=1.1, stop=1.105, exit=1.09, closed_at=T0 + timedelta(hours=2))
    )
    assert entry.exit == 1.09


@pytest.mark.parametrize(
    "changes",
    [
        {"stop": 1.1},  # long: stop equals entry
        {"stop": 1.2},  # long: stop above entry
        {"side": "short"},  # short with stop below entry
        {"side": "sideways"},
        {"timeframe": "2h"},
        {"symbol": "EUR USD"},
        {"symbol": ""},
        {"entry": 0},
        {"entry": -1},
        {"entry": math.nan},
        {"entry": math.inf},
        {"stop": math.nan},
        {"size": 0},
        {"size": math.inf},
        {"opened_at": datetime(2026, 3, 1, 12, 0)},  # naive
        {"notes": "x" * (MAX_NOTES_CHARS + 1)},
        {"analysis_id": 0},
        {"unknown": 1},
        {"exit": 1.2},  # exit without closed_at
        {"closed_at": T0 + timedelta(hours=1)},  # closed_at without exit
        {"exit": 1.2, "closed_at": T0 - timedelta(hours=1)},  # closed before opened
        {"exit": math.nan, "closed_at": T0 + timedelta(hours=1)},
        {"pnl_currency": 5.0},  # pnl on an open trade
        {"pnl_currency": math.nan, "exit": 1.2, "closed_at": T0 + timedelta(hours=1)},
    ],
)
def test_invalid_entries_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        JournalEntryIn(**raw(**changes))


def test_notes_at_the_cap_are_accepted() -> None:
    assert len(JournalEntryIn(**raw(notes="x" * MAX_NOTES_CHARS)).notes) == MAX_NOTES_CHARS


def test_update_is_partial_and_checks_fields() -> None:
    patch = JournalEntryUpdate(notes="later")
    assert patch.model_dump(exclude_unset=True) == {"notes": "later"}
    with pytest.raises(ValidationError):
        JournalEntryUpdate(entry=math.nan)
    with pytest.raises(ValidationError):
        JournalEntryUpdate(bogus=1)  # type: ignore[call-arg]


def test_update_cannot_clear_required_fields() -> None:
    with pytest.raises(ValidationError, match="cannot be cleared"):
        JournalEntryUpdate(stop=None)
    assert JournalEntryUpdate(exit=None).exit is None


@pytest.mark.parametrize(
    "changes",
    [
        {"entry": 1e13, "stop": 1.0},
        {"entry": 100.0, "stop": 100.0 - 1e-9},  # risk too small to measure
        {"analysis_id": 2**63},
        {"size": 1e13},
        {"exit": 1.2, "closed_at": T0 + timedelta(hours=1), "pnl_currency": 1e13},
    ],
)
def test_extreme_values_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        JournalEntryIn(**raw(**changes))
