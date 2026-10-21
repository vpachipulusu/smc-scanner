"""Glue between the command line and the analyst: frames, provider, store, table cells.

Nothing here raises for an AI problem: ``analyse_for_cli`` turns every failure into
per-row notes so the scan results are always shown.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from smc_scanner.ai.analyst import AnalysisResult, HitInputs, analyse_hits, hit_inputs_from_ohlc
from smc_scanner.ai.providers import AiError, AiProvider, AiReply, make_provider
from smc_scanner.ai.store import SqliteAnalysisStore, StoreError, db_path_from_env
from smc_scanner.loaders.base import Loader
from smc_scanner.models import ScanRow
from smc_scanner.report import AiCells
from smc_scanner.scanner import ScanOptions

log = logging.getLogger(__name__)

DEMO_PROVIDER = "fake"
PROVIDER_CHOICES = ("claude", DEMO_PROVIDER)
MAX_NOTE_CHARS = 120
STORE_NOTE = "database error, see log"
DEMO_REPLY = (
    '{"action": "HOLD", "confidence": 0, "reasons": ["demo provider, no model was called"],'
    ' "summary": "Demo run, no real analysis."}'
)
SKIP_NOTES = {
    "skipped_low_score": "score below minimum",
    "skipped_cap": "over the per-run cap",
    "skipped_duplicate": "already analysed",
    "skipped_failed_recently": "failed recently, retry later",
}


class DemoProvider:
    """Canned HOLD replies so ``--demo --ai`` runs offline; records each call."""

    name = DEMO_PROVIDER
    model = "demo"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> AiReply:
        self.calls.append((system, user))
        return AiReply(DEMO_REPLY, 0, 0, self.model)


def build_provider(name: str | None) -> AiProvider:
    """The demo provider for ``fake``, otherwise the configured real one."""
    if name == DEMO_PROVIDER:
        return DemoProvider()
    return make_provider(name)


class FrameCache:
    """Loader wrapper that remembers each frame it loaded, so hits can be re-analysed
    without a second download.

    ``frames`` holds the first timeframe loaded (the one being scanned), by symbol, so a
    multi-timeframe scan loading neighbours never replaces it; ``frames_by_timeframe`` holds
    every frame by (symbol, timeframe).
    """

    def __init__(self, inner: Loader) -> None:
        self._inner = inner
        self._primary: str | None = None
        self.frames: dict[str, pd.DataFrame] = {}
        self.frames_by_timeframe: dict[tuple[str, str], pd.DataFrame] = {}

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        frame = self._inner.load(symbol, timeframe, bars)
        if self._primary is None:
            self._primary = timeframe
        if timeframe == self._primary:
            self.frames[symbol] = frame
        self.frames_by_timeframe[(symbol, timeframe)] = frame
        return frame

    def close(self) -> None:
        self._inner.close()


@dataclass(frozen=True)
class AiSettings:
    provider: str | None
    min_score: int
    max_rows: int
    demo: bool = False


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= MAX_NOTE_CHARS else one_line[: MAX_NOTE_CHARS - 1] + "…"


def _cells(result: AnalysisResult) -> AiCells:
    verdict = result.verdict
    if verdict is not None:
        note = SKIP_NOTES.get(result.status, "")
        if verdict.downgraded:
            note = _short(verdict.downgrade_reason or "")
        if result.status == "analysed" and result.error:
            note = _short(f"not saved: {result.error}")  # it will be sent again next cycle
        return AiCells(
            action=verdict.action,
            confidence=verdict.confidence,
            entry=verdict.entry,
            stop=verdict.stop,
            target=verdict.targets[0] if verdict.targets else None,
            note=note,
        )
    if result.status == "failed":
        return AiCells(note=_short(f"failed: {result.error or 'unknown error'}"))
    return AiCells(note=SKIP_NOTES.get(result.status, result.status))


def _store_path(settings: AiSettings) -> Path:
    """Demo verdicts get their own file so they never look like real analysed bars."""
    path = db_path_from_env()
    return path.with_name(path.stem + ".demo.db") if settings.provider == DEMO_PROVIDER else path


def _unavailable(rows: Sequence[ScanRow], reason: str) -> list[AiCells]:
    return [AiCells(note=_short(f"unavailable: {reason}")) for _ in rows]


def analyse_for_cli(
    rows: Sequence[ScanRow],
    frames: dict[str, pd.DataFrame],
    options: ScanOptions,
    timeframe: str,
    settings: AiSettings,
) -> list[AiCells]:
    """One AI cell set per row, in order. Never raises; problems become notes and a log line."""
    if not rows:
        return []
    if settings.provider == DEMO_PROVIDER and not settings.demo:
        log.error("the fake AI provider is for --demo runs only")
        return _unavailable(rows, "fake provider needs --demo")
    try:
        provider = build_provider(settings.provider)
    except AiError as exc:
        log.error("AI analysis unavailable: %s", exc)
        return _unavailable(rows, str(exc))  # names the missing variable, no secrets
    try:
        store = SqliteAnalysisStore(_store_path(settings))
    except StoreError as exc:
        log.error("AI analysis unavailable: %s", exc)
        return _unavailable(rows, STORE_NOTE)  # the path stays in the log, not the CSV

    def source(row: ScanRow) -> HitInputs:
        return hit_inputs_from_ohlc(frames[row.instrument], row, options)

    try:
        results = analyse_hits(
            rows,
            source,
            provider,
            store,
            timeframe=timeframe,
            min_score=settings.min_score,
            max_rows=settings.max_rows,
        )
    except AiError as exc:
        log.error("AI analysis failed: %s", exc)
        return _unavailable(rows, str(exc))
    except StoreError as exc:
        log.error("AI analysis failed: %s", exc)
        return _unavailable(rows, STORE_NOTE)
    except Exception as exc:  # noqa: BLE001 - AI must never hide the scan; class name only
        log.error("AI analysis failed: %s", type(exc).__name__)
        return _unavailable(rows, type(exc).__name__)
    return [_cells(result) for result in results]
