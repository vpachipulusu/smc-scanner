"""Manual trade journal: CRUD with cursor paging, and R-based statistics."""

import base64
import binascii
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import ValidationError

from smc_scanner.api.constants import (
    DEFAULT_JOURNAL_LIMIT,
    INVALID_CURSOR_MESSAGE,
    INVALID_REQUEST_MESSAGE,
    JOURNAL_NOT_FOUND_MESSAGE,
    MAX_JOURNAL_CURSOR_CHARS,
    MAX_JOURNAL_LIMIT,
    MAX_ROW_ID,
)
from smc_scanner.api.deps import (
    InternalKeyDep,
    JournalRateDep,
    JournalStatsRateDep,
    JournalStoreDep,
    _journal_store_errors,
)
from smc_scanner.api.journal_schemas import (
    CumulativePointOut,
    JournalPage,
    JournalStatsOut,
    JournalStatsResponse,
)
from smc_scanner.api.schedule_schemas import DeleteResponse
from smc_scanner.api.schemas import ErrorResponse
from smc_scanner.journal.models import (
    SYMBOL_REGEX,
    JournalEntryIn,
    JournalEntryOut,
    JournalEntryUpdate,
)
from smc_scanner.journal.stats import cumulative_r, summarize
from smc_scanner.journal.store import JournalCursor

log = logging.getLogger(__name__)
router = APIRouter(tags=["journal"])

_CURSOR_PREFIX = "j1:"

JOURNAL_ERRORS: dict[int | str, dict[str, Any]] = {
    429: {
        "model": ErrorResponse,
        "description": "Too many requests; see the Retry-After header",
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before retrying",
                "schema": {"type": "integer"},
            }
        },
    },
    503: {"model": ErrorResponse, "description": "Journal database unavailable"},
}
ENTRY_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No journal entry with that id"},
    **JOURNAL_ERRORS,
}

EntryId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]  # a positive SQLite row id


def encode_cursor(cursor: JournalCursor) -> str:
    """An opaque token for the position after ``cursor``'s entry."""
    text = f"{_CURSOR_PREFIX}{cursor.opened_at.isoformat()}|{cursor.id}"
    return base64.urlsafe_b64encode(text.encode()).decode()


def _decode_cursor(token: str) -> JournalCursor:
    """The position behind a cursor token; anything else is a 422."""
    bad = HTTPException(status_code=422, detail=INVALID_CURSOR_MESSAGE)
    try:
        text = base64.urlsafe_b64decode(token.encode()).decode()
        stamp, _, number = text.removeprefix(_CURSOR_PREFIX).rpartition("|")
        if not text.startswith(_CURSOR_PREFIX) or not number.isascii() or not number.isdigit():
            raise bad
        opened_at = datetime.fromisoformat(stamp)
        if opened_at.tzinfo is None or not 1 <= int(number) <= MAX_ROW_ID:
            raise bad
        return JournalCursor(opened_at.astimezone(UTC), int(number))
    except (binascii.Error, UnicodeDecodeError, ValueError, OverflowError) as exc:
        raise bad from exc


@router.get("/journal", response_model=JournalPage, responses=JOURNAL_ERRORS)
def list_journal(
    _: InternalKeyDep,
    __: JournalRateDep,
    store: JournalStoreDep,
    limit: Annotated[int, Query(ge=1, le=MAX_JOURNAL_LIMIT)] = DEFAULT_JOURNAL_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_JOURNAL_CURSOR_CHARS)] = None,
    symbol: Annotated[str | None, Query(pattern=SYMBOL_REGEX)] = None,
) -> JournalPage:
    """Journal entries, newest ``opened_at`` first. Pass ``next_cursor`` back for the next page."""
    position = None if cursor is None else _decode_cursor(cursor)
    with _journal_store_errors():
        page = store.list_entries(limit=limit, cursor=position, symbol=symbol)
    return JournalPage(
        items=page.items,
        next_cursor=None if page.next_cursor is None else encode_cursor(page.next_cursor),
    )


@router.post(
    "/journal",
    response_model=JournalEntryOut,
    status_code=201,
    responses={
        409: {"model": ErrorResponse, "description": "The journal entry limit is reached"},
        **JOURNAL_ERRORS,
    },
)
def create_journal_entry(
    body: JournalEntryIn, _: InternalKeyDep, __: JournalRateDep, store: JournalStoreDep
) -> JournalEntryOut:
    """Record a trade by hand. Leave ``exit`` and ``closed_at`` out while it is still open."""
    with _journal_store_errors():
        return store.add(body)


@router.get("/journal/stats", response_model=JournalStatsResponse, responses=JOURNAL_ERRORS)
def journal_stats(
    _: InternalKeyDep, __: JournalRateDep, ___: JournalStatsRateDep, store: JournalStoreDep
) -> JournalStatsResponse:
    """Win rate, average R, expectancy and the cumulative-R series over closed trades.

    R is profit divided by the initial risk ``|entry - stop|``, for longs and shorts alike;
    currency P&L plays no part. ``open_trades`` is counted in a separate read, so it can lag a
    concurrent write by one entry. Declared before ``/journal/{entry_id}`` so it is not an id.
    """
    with _journal_store_errors():
        entries = store.closed_entries()
        open_trades = store.open_count()
    return JournalStatsResponse(
        summary=JournalStatsOut(**{**asdict(summarize(entries)), "open_trades": open_trades}),
        cumulative=[CumulativePointOut(**asdict(point)) for point in cumulative_r(entries)],
    )


@router.get("/journal/{entry_id}", response_model=JournalEntryOut, responses=ENTRY_ERRORS)
def get_journal_entry(
    entry_id: EntryId, _: InternalKeyDep, __: JournalRateDep, store: JournalStoreDep
) -> JournalEntryOut:
    """One journal entry by id."""
    with _journal_store_errors():
        entry = store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=JOURNAL_NOT_FOUND_MESSAGE)
    return entry


@router.patch("/journal/{entry_id}", response_model=JournalEntryOut, responses=ENTRY_ERRORS)
def update_journal_entry(
    entry_id: EntryId,
    body: JournalEntryUpdate,
    _: InternalKeyDep,
    __: JournalRateDep,
    store: JournalStoreDep,
) -> JournalEntryOut:
    """Change some fields; ``null`` clears an optional one (e.g. reopen a trade by clearing
    ``exit`` and ``closed_at`` together). The merged entry must still be valid."""
    with _journal_store_errors():
        try:
            return store.update(entry_id, body)
        except ValidationError as exc:
            log.info("invalid journal update: %s", exc)
            raise HTTPException(status_code=422, detail=INVALID_REQUEST_MESSAGE) from exc


@router.delete("/journal/{entry_id}", response_model=DeleteResponse, responses=ENTRY_ERRORS)
def delete_journal_entry(
    entry_id: EntryId, _: InternalKeyDep, __: JournalRateDep, store: JournalStoreDep
) -> DeleteResponse:
    """Delete one journal entry."""
    with _journal_store_errors():
        deleted = store.delete(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=JOURNAL_NOT_FOUND_MESSAGE)
    return DeleteResponse()
