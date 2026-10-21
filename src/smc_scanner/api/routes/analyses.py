"""``/analyse`` and the stored-analysis routes."""

import logging
import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from smc_scanner.ai.analyst import (
    AnalysisResult,
    analyse_hits,
    make_hit_source,
)
from smc_scanner.ai.budget import (
    BudgetExceededError,
)
from smc_scanner.ai.store import (
    AnalysisRecord,
    StoreError,
)
from smc_scanner.ai.verdict import CONFIDENCE_MAX, CONFIDENCE_MIN, Action, AiVerdict
from smc_scanner.ai_cli import MAX_NOTE_CHARS, SKIP_NOTES, FrameCache
from smc_scanner.api.constants import (
    AI_FAILED_MESSAGE,
    DEFAULT_ANALYSES_LIMIT,
    MAX_ANALYSES_LIMIT,
    MAX_CURSOR_CHARS,
    MAX_ROW_ID,
    NOT_FOUND_MESSAGE,
    NOTHING_LOADED_MESSAGE,
    SYMBOL_PATTERN,
)
from smc_scanner.api.deps import (
    AnalyseRateDep,
    CalendarServiceDep,
    InternalKeyDep,
    ProviderFactoryDep,
    _analyse_lock,
    _budget_guard,
    _budget_refused,
    _open_store,
    _scan_lock,
    _store_unavailable,
)
from smc_scanner.api.helpers import _clip, _decode_cursor, _encode_cursor, _symbols
from smc_scanner.api.schemas import (
    RETRY_AFTER_HEADER,
    AiResultOut,
    AnalysedRowOut,
    AnalyseRequest,
    AnalyseResponse,
    AnalysisOut,
    AnalysisPage,
    ErrorResponse,
    ScanFailureOut,
    ScanRowOut,
)
from smc_scanner.loaders import make_loader
from smc_scanner.models import Bias
from smc_scanner.scanner import ScanOptions, run_scan

log = logging.getLogger(__name__)
_TIMEFRAME_NAME = re.compile(r"[A-Za-z0-9]{1,8}")
router = APIRouter()


def _note(result: AnalysisResult) -> str:
    verdict = result.verdict
    if result.status == "failed":
        return "analysis failed, see the server log"
    if verdict is not None and verdict.downgraded:
        return (verdict.downgrade_reason or "")[:MAX_NOTE_CHARS]
    if result.status == "analysed" and result.error:
        return "not saved, it will be retried"
    return SKIP_NOTES.get(result.status, "")


def _analysed_row(result: AnalysisResult, htf_bias: Bias | None = None) -> AnalysedRowOut:
    ai = AiResultOut(status=result.status, verdict=result.verdict, note=_note(result))
    return AnalysedRowOut(**ScanRowOut.from_row(result.row, htf_bias).model_dump(), ai=ai)


def _provider_failed_everywhere(results: list[AnalysisResult]) -> bool:
    """Something failed and nothing worked: no verdict made or reused."""
    if not any(result.status == "failed" for result in results):
        return False
    return not any(result.status in {"analysed", "skipped_duplicate"} for result in results)


@router.post(
    "/analyse",
    response_model=AnalyseResponse,
    tags=["analyses"],
    responses={
        429: {
            "model": ErrorResponse,
            "description": "Rate limited, or the daily AI budget is used up; see Retry-After",
            "headers": RETRY_AFTER_HEADER,
        },
        502: {"model": ErrorResponse, "description": "The AI provider failed for the whole run"},
        503: {
            "model": ErrorResponse,
            "description": "Nothing loaded, AI disabled, no database or invalid budget settings",
        },
    },
)
def analyse(
    body: AnalyseRequest,
    _: InternalKeyDep,
    __: AnalyseRateDep,
    make_ai_provider: ProviderFactoryDep,
    calendar: CalendarServiceDep,
) -> AnalyseResponse:
    """Scan, then ask the AI about the best hits; every row comes back with its AI result.

    The scan runs under the scan lock, which is released before any provider call. The
    analysis phase is serialised by its own lock, so concurrent identical runs queue and the
    second one finds the first one's verdicts instead of calling the provider again.

    429 when the daily AI budget is used up (``AI_MAX_CALLS_PER_DAY`` / ``AI_MAX_COST_PER_DAY``)
    or the endpoint is rate limited; ``Retry-After`` says when to try again. Hits already
    analysed are served from the database even then, since they need no call. A budget refusal
    comes when a call is needed: rows analysed before it stay in the database (read them from
    ``GET /analyses``) but are not in the 429 body.
    """
    provider = make_ai_provider()
    store = _open_store(read_only=False)
    budget = _budget_guard(store)
    options = ScanOptions(swing_length=body.swing, near_atr=body.near, all_touches=body.all_touches)
    wanted = _symbols(body.source, ",".join(body.symbols) if body.symbols else None)
    with _scan_lock:
        frames = FrameCache(make_loader(body.source))
        result = run_scan(
            frames,
            wanted,
            body.tf,
            body.bars,
            options,
            mtf=body.mtf,
            require_htf_aligned=body.require_htf_aligned,
            ltf_min_score=body.min_score,
            ltf_max_rows=body.max_rows,
        )
    if result.all_failed:
        raise HTTPException(status_code=503, detail=NOTHING_LOADED_MESSAGE)
    try:
        with _analyse_lock:
            results = analyse_hits(
                result.rows,
                make_hit_source(
                    frames.frames,
                    options,
                    timeframe=body.tf,
                    mtf=body.mtf,
                    lookup=lambda symbol, tf: frames.frames_by_timeframe.get((symbol, tf)),
                ),
                provider,
                store,
                timeframe=body.tf,
                min_score=body.min_score,
                max_rows=body.max_rows,
                budget=budget,
                calendar=calendar.snapshot,
            )
    except BudgetExceededError as exc:
        raise _budget_refused(exc) from exc
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    if _provider_failed_everywhere(results):
        raise HTTPException(status_code=502, detail=AI_FAILED_MESSAGE)
    return AnalyseResponse(
        source=body.source,
        tf=body.tf,
        count=len(results),
        rows=[_analysed_row(r, result.htf_bias.get(r.row.instrument)) for r in results],
        failures=[ScanFailureOut(symbol=f.symbol, error=f.error) for f in result.failures],
    )


def _stored_verdict(record: AnalysisRecord) -> AiVerdict | None:
    if record.verdict is None:
        return None
    try:
        return AiVerdict.model_validate(record.verdict)
    except ValueError:
        log.warning("stored verdict %s does not validate", record.id)
        return None


def _timeframes_used(record: AnalysisRecord) -> list[str]:
    """The scan timeframe, then the neighbour timeframes whose block is in the stored context.
    Stored JSON is untrusted: only well-formed timeframe names are returned."""
    used = [record.key.tf] if _TIMEFRAME_NAME.fullmatch(record.key.tf) else []
    context = record.context
    if not isinstance(context, dict):
        return used
    for name in ("htf", "ltf"):
        block = context.get(name)
        timeframe = block.get("timeframe") if isinstance(block, dict) else None
        if (
            isinstance(timeframe, str)
            and _TIMEFRAME_NAME.fullmatch(timeframe)
            and timeframe not in used
        ):
            used.append(timeframe)
    return used


def _analysis_out(record: AnalysisRecord) -> AnalysisOut:
    verdict = _stored_verdict(record)
    key = record.key
    label = record.zone.get("label")
    return AnalysisOut(
        id=record.id or 0,
        created_at=record.created_at,
        symbol=key.symbol,
        tf=key.tf,
        zone_kind=key.zone_kind,
        zone=_clip(label if isinstance(label, str) else key.zone_kind),
        zone_low=key.zone_low,
        zone_high=key.zone_high,
        bar_time=key.bar_time,
        provider=_clip(record.provider),
        model=_clip(record.model),
        prompt_version=_clip(record.prompt_version),
        attempts=record.attempts,
        status="ok" if verdict is not None and record.error is None else "failed",
        verdict=verdict,
        timeframes_used=_timeframes_used(record),
    )


@router.get("/analyses", response_model=AnalysisPage, tags=["analyses"])
def list_analyses(
    _: InternalKeyDep,
    symbol: Annotated[str | None, Query(pattern=SYMBOL_PATTERN.pattern)] = None,
    action: Action | None = None,
    min_confidence: Annotated[float | None, Query(ge=CONFIDENCE_MIN, le=CONFIDENCE_MAX)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ANALYSES_LIMIT)] = DEFAULT_ANALYSES_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_CHARS)] = None,
) -> AnalysisPage:
    """Stored analyses, newest first. Pass ``next_cursor`` back to get the following page."""
    before_id = None if cursor is None else _decode_cursor(cursor)
    store = _open_store(read_only=True)
    try:
        records = store.list_filtered(
            symbol=symbol,
            action=action,
            min_confidence=min_confidence,
            before_id=before_id,
            limit=limit + 1,
        )
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    page = records[:limit]
    more = len(records) > limit and page[-1].id is not None
    return AnalysisPage(
        items=[_analysis_out(record) for record in page],
        next_cursor=_encode_cursor(page[-1].id or 0) if more else None,
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisOut,
    tags=["analyses"],
    responses={404: {"model": ErrorResponse, "description": "No analysis with that id"}},
)
def get_analysis(
    analysis_id: Annotated[int, Path(ge=1, le=MAX_ROW_ID)], _: InternalKeyDep
) -> AnalysisOut:
    store = _open_store(read_only=True)
    try:
        record = store.get_by_id(analysis_id)
    except StoreError as exc:
        raise _store_unavailable(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MESSAGE)
    return _analysis_out(record)
