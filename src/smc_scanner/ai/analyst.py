"""Analyst service: decide which scan rows are worth an LLM call, call once per bar, save it all.

``analyse_hits`` is a plain function. It takes no locks and the caller holds none while it
runs, so a slow provider never blocks a scan. AI, data and store errors never raise out of it:
a row that cannot be analysed comes back as ``failed`` and is recorded in the store when
possible; if the store itself is broken the in-memory result is still returned.

Dedupe: one successful analysis per (symbol, timeframe, zone kind, zone bounds, bar). The
prompt version, provider and model are NOT part of that key, so a new prompt or model does not
re-analyse old bars unless the caller passes ``force=True``. A stored *failure* does not block
a later run on the same bar until it has failed ``MAX_ATTEMPTS`` times or failed within
``FAILURE_COOLDOWN``; those rows come back as ``skipped_failed_recently``. A row that failed
without a provider call (bad data, oversized context) never counts towards ``max_rows``.
"""

import logging
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import pandas as pd

from smc_scanner.ai.context import build_context
from smc_scanner.ai.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from smc_scanner.ai.providers import AiError, AiProvider
from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, AnalysisStore, StoreError
from smc_scanner.ai.verdict import AiVerdict, HitFacts, parse_verdict
from smc_scanner.models import ScanRow, Structure, Swing, ZoneState
from smc_scanner.scanner import ScanOptions
from smc_scanner.structure import analyse_structure, confirmed_swing_frame, confirmed_swings
from smc_scanner.zones import evaluate_zones

log = logging.getLogger(__name__)

DEFAULT_MIN_SCORE: Final = 2
DEFAULT_MAX_ROWS: Final = 5
MAX_ERROR_CHARS: Final = 200
MAX_ATTEMPTS: Final = 3
FAILURE_COOLDOWN: Final = timedelta(minutes=15)
CLOSE_REL_TOL: Final = 1e-9
CLOSE_ABS_TOL: Final = 1e-12
TOKENS_PER_PRICE_UNIT: Final = 1_000_000
NOT_SAVED: Final = "StoreError: result not saved"

# Rough USD per million tokens (input, output), matched by model-name prefix. Estimates only:
# check the provider's price list before relying on them for billing.
PRICE_PER_MTOK: Final[dict[str, tuple[float, float]]] = {
    "claude-opus-5-5": (5.0, 25.0),
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-haiku-5-5": (1.0, 5.0),
}

Status = Literal[
    "analysed",
    "skipped_low_score",
    "skipped_cap",
    "skipped_duplicate",
    "skipped_failed_recently",
    "failed",
]


@dataclass(frozen=True)
class HitInputs:
    """What ``build_context`` needs besides the row: the scanned frame and its derived state."""

    ohlc: pd.DataFrame
    structure: Structure
    state: ZoneState
    swings: Sequence[Swing]


HitSource = Callable[[ScanRow], HitInputs]


@dataclass(frozen=True)
class AnalysisResult:
    row: ScanRow
    status: Status
    verdict: AiVerdict | None = None
    error: str | None = None


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=CLOSE_REL_TOL, abs_tol=CLOSE_ABS_TOL)


def hit_inputs_from_ohlc(ohlc: pd.DataFrame, row: ScanRow, options: ScanOptions) -> HitInputs:
    """Recompute the scan state behind ``row`` from the frame it was scanned on."""
    swings = confirmed_swings(ohlc, options.swing_length)
    structure = analyse_structure(ohlc, swings)
    states = evaluate_zones(
        ohlc, confirmed_swing_frame(ohlc, swings), structure.atr, options.near_atr
    )
    formed_index = len(ohlc) - 1 - row.zone_age
    for state in states:
        zone = state.zone
        if (
            zone.formed_index == formed_index
            and _close(zone.bottom, row.zone_low)
            and _close(zone.top, row.zone_high)
        ):
            return HitInputs(ohlc=ohlc, structure=structure, state=state, swings=swings)
    raise ValueError(f"{row.instrument}: zone {row.zone} not found in the scanned frame")


def estimate_cost(model: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    """USD estimate, or None for an unpriced model or missing token counts."""
    if tokens_in is None or tokens_out is None:
        return None
    for name, (price_in, price_out) in PRICE_PER_MTOK.items():
        if model.startswith(name):
            return (tokens_in * price_in + tokens_out * price_out) / TOKENS_PER_PRICE_UNIT
    return None


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("now() must return a timezone-aware datetime")
    return moment.astimezone(UTC)


def _key(row: ScanRow, timeframe: str) -> AnalysisKey:
    return AnalysisKey(
        symbol=row.instrument,
        tf=timeframe,
        zone_kind=row.zone.split()[-1],
        zone_low=row.zone_low,
        zone_high=row.zone_high,
        bar_time=row.bar_time,
    )


def _describe(exc: Exception) -> str:
    """AiError text is safe by construction; for anything else only the class name is kept,
    since validation and SDK messages can echo input values or secrets."""
    if isinstance(exc, AiError):
        return f"AiError: {exc}"[:MAX_ERROR_CHARS]
    return type(exc).__name__


def _priority(item: tuple[int, ScanRow]) -> tuple[int, bool, float, int]:
    """Sort key: higher score first, then TOUCHING before NEAR, then the closer zone
    (non-finite distance last), then input order."""
    index, row = item
    dist = row.dist_atr if math.isfinite(row.dist_atr) else math.inf
    return (-row.score, row.status != "TOUCHING", dist, index)


def _stored_verdict(record: AnalysisRecord) -> AiVerdict | None:
    try:
        return AiVerdict.model_validate(record.verdict)
    except ValueError:
        return None


def _failed_recently(record: AnalysisRecord, current: datetime) -> bool:
    if record.attempts >= MAX_ATTEMPTS:
        return True
    try:
        failed_at = _utc(datetime.fromisoformat(record.created_at))
    except ValueError:
        return False
    return current - failed_at < FAILURE_COOLDOWN


@dataclass
class _Run:
    provider: AiProvider
    store: AnalysisStore
    source: HitSource
    timeframe: str
    now: Callable[[], datetime]
    force: bool

    def analyse(self, row: ScanRow, key: AnalysisKey) -> tuple[AnalysisResult, bool]:
        """The result, and whether the provider was called."""
        context: dict[str, Any] | None = None
        try:
            inputs = self.source(row)
            built = build_context(
                inputs.ohlc,
                row,
                inputs.structure,
                inputs.state,
                inputs.swings,
                timeframe=self.timeframe,
            )
            context = dict(built)
            user = build_user_message(built)
            facts = HitFacts(
                direction=inputs.state.zone.direction,
                price=row.price,
                zone_low=row.zone_low,
                zone_high=row.zone_high,
                atr=inputs.structure.atr,
            )
        except Exception as exc:
            return self._failed(row, key, context, exc), False
        try:
            reply = self.provider.complete(SYSTEM_PROMPT, user)
        except Exception as exc:
            return self._failed(row, key, context, exc), True
        verdict = parse_verdict(reply.text, facts)
        saved = self._save(
            row,
            key,
            context=context,
            verdict=verdict.model_dump(mode="json"),
            model=reply.model,
            tokens=(reply.input_tokens, reply.output_tokens),
            error=None,
        )
        return AnalysisResult(row, "analysed", verdict, None if saved else NOT_SAVED), True

    def _failed(
        self, row: ScanRow, key: AnalysisKey, context: dict[str, Any] | None, exc: Exception
    ) -> AnalysisResult:
        error = _describe(exc)
        log.warning("analysis failed for %s %s: %s", row.instrument, row.zone, type(exc).__name__)
        saved = self._save(
            row,
            key,
            context=context,
            verdict=None,
            model=self.provider.model or "",
            tokens=(None, None),
            error=error,
        )
        return AnalysisResult(row, "failed", error=error if saved else f"{error}; {NOT_SAVED}")

    def _save(
        self,
        row: ScanRow,
        key: AnalysisKey,
        *,
        context: dict[str, Any] | None,
        verdict: dict[str, Any] | None,
        model: str,
        tokens: tuple[int | None, int | None],
        error: str | None,
    ) -> bool:
        record = AnalysisRecord(
            key=key,
            created_at=_utc(self.now()).isoformat(),
            zone={
                "label": row.zone,
                "low": row.zone_low,
                "high": row.zone_high,
                "age_bars": row.zone_age,
                "prior_touches": row.prior_touches,
            },
            context=context,
            verdict=verdict,
            provider=self.provider.name,
            model=model,
            prompt_version=PROMPT_VERSION,
            tokens_in=tokens[0],
            tokens_out=tokens[1],
            cost_estimate=estimate_cost(model, *tokens),
            error=error,
        )
        try:
            self.store.save(record, overwrite=self.force and error is None)
        except StoreError:
            log.warning("could not save analysis for %s %s", row.instrument, row.zone)
            return False
        return True


def analyse_hits(
    rows: Iterable[ScanRow],
    source: HitSource,
    provider: AiProvider,
    store: AnalysisStore,
    *,
    timeframe: str,
    min_score: int = DEFAULT_MIN_SCORE,
    max_rows: int = DEFAULT_MAX_ROWS,
    force: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[AnalysisResult]:
    """One result per input row, in input order.

    Rows below ``min_score`` are skipped. The rest are taken best first (see ``_priority``).
    Already-analysed bars are reported as duplicates without a call and, like rows that failed
    before reaching the provider, do not count towards ``max_rows``; rows past the cap are
    ``skipped_cap``. ``force`` re-analyses and overwrites stored successes. ``now`` must return
    an aware datetime (ValueError otherwise, before any work is done).
    """
    listed = list(rows)
    _utc(now())  # fail fast on a naive clock
    run = _Run(provider, store, source, timeframe, now, force)
    results: dict[int, AnalysisResult] = {}
    eligible: list[tuple[int, ScanRow]] = []
    for index, row in enumerate(listed):
        if row.score < min_score:
            results[index] = AnalysisResult(row, "skipped_low_score")
        else:
            eligible.append((index, row))
    calls = 0
    seen: dict[AnalysisKey, AiVerdict | None] = {}
    for index, row in sorted(eligible, key=_priority):
        try:
            key = _key(row, timeframe)
        except ValueError as exc:
            results[index] = AnalysisResult(row, "failed", error=f"invalid hit key: {exc}")
            continue
        if key in seen:
            results[index] = AnalysisResult(row, "skipped_duplicate", seen[key])
            continue
        try:
            existing = None if force else store.get(key)
        except StoreError:
            log.warning("dedupe lookup failed for %s %s", row.instrument, row.zone)
            results[index] = AnalysisResult(row, "failed", error="StoreError: lookup failed")
            continue
        if existing is not None:
            if existing.error is None:
                results[index] = AnalysisResult(row, "skipped_duplicate", _stored_verdict(existing))
                continue
            if _failed_recently(existing, _utc(now())):
                results[index] = AnalysisResult(
                    row, "skipped_failed_recently", error=existing.error
                )
                continue
        if calls >= max_rows:
            results[index] = AnalysisResult(row, "skipped_cap")
            continue
        result, called = run.analyse(row, key)
        calls += called
        results[index] = result
        if result.status == "analysed":
            seen[key] = result.verdict
    return [results[i] for i in range(len(listed))]
