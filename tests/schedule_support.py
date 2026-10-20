"""Fakes shared by the schedule runner and service tests: clock, provider, sender, scan."""

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from smc_scanner.ai.analyst import AnalysisResult
from smc_scanner.ai.providers import AiReply
from smc_scanner.ai.store import SqliteAnalysisStore
from smc_scanner.ai.verdict import AiVerdict
from smc_scanner.models import ScanRow
from smc_scanner.notify.telegram import SendResult
from smc_scanner.scanner import ScanOptions
from smc_scanner.schedule.runner import RunDeps, RunGuard, ScanData
from smc_scanner.schedule.store import Schedule, SqliteScheduleRepository

T0 = datetime(2026, 3, 1, 12, 0, 30, tzinfo=UTC)
BAR = "2026-03-01 11:00:00"
TOKEN = "123456:ABC-def_ghi"


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def make_row(symbol: str = "EURUSD", bar_time: str = BAR, score: int = 3) -> ScanRow:
    return ScanRow(
        instrument=symbol,
        status="TOUCHING",
        zone="bull OB",
        zone_low=1.1,
        zone_high=1.2,
        price=1.15,
        dist_atr=0.0,
        bias="bullish",
        in_ote=False,
        trendline_ok=False,
        ob_fvg=False,
        score=score,
        zone_age=3,
        prior_touches=0,
        bar_time=bar_time,
    )


def buy(confidence: float = 80.0) -> AiVerdict:
    return AiVerdict(
        action="BUY",
        confidence=confidence,
        entry=1.15,
        stop=1.1,
        targets=(1.25,),
        risk_reward=2.0,
        summary="Looks fine.",
    )


def hold(confidence: float = 40.0) -> AiVerdict:
    return AiVerdict(action="HOLD", confidence=confidence, summary="No edge.")


@dataclass
class Recorder:
    """Everything the fakes saw, plus what the shared lock looked like at each call."""

    lock: threading.Lock
    scans: int = 0
    provider_calls: int = 0
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    locked_during_scan: list[bool] = field(default_factory=list)
    locked_during_provider: list[bool] = field(default_factory=list)
    locked_during_send: list[bool] = field(default_factory=list)


class FakeProvider:
    name = "fake"
    model = "fake"

    def __init__(self, rec: Recorder, fail: bool = False) -> None:
        self._rec = rec
        self._fail = fail

    def complete(self, system: str, user: str) -> AiReply:
        self._rec.provider_calls += 1
        self._rec.locked_during_provider.append(self._rec.lock.locked())
        if self._fail:
            raise RuntimeError("provider down")
        return AiReply("{}", 0, 0, "fake")


def build_deps(
    tmp_path: Path,
    *,
    verdicts: dict[str, AiVerdict] | None = None,
    rows: list[ScanRow] | None = None,
    send_ok: bool = True,
    previous: dict[str, str] | None = None,
    scan_error: Exception | None = None,
    provider_fails: bool = False,
    chat: str | None = "42",
    token: str = TOKEN,
    clock: FakeClock | None = None,
    scan_hook: object = None,
) -> tuple[RunDeps, Recorder, SqliteScheduleRepository]:
    lock = threading.Lock()
    rec = Recorder(lock)
    repo = SqliteScheduleRepository(tmp_path / "smc.db")
    store = SqliteAnalysisStore(tmp_path / "smc.db")
    scripted = verdicts if verdicts is not None else {"EURUSD": buy()}
    scanned = rows if rows is not None else [make_row(symbol) for symbol in scripted]
    prior = previous or {}

    def scan(schedule: Schedule) -> ScanData:
        rec.scans += 1
        rec.locked_during_scan.append(lock.locked())
        if callable(scan_hook):
            scan_hook()
        if scan_error is not None:
            raise scan_error
        return ScanData(rows=tuple(scanned), frames={}, options=ScanOptions())

    def analyse(
        data: ScanData, schedule: Schedule, provider: FakeProvider, _: object, __: object
    ) -> list[AnalysisResult]:
        results = []
        for row in data.rows:
            provider.complete("s", "u")
            results.append(AnalysisResult(row, "analysed", scripted[row.instrument]))
        return results

    def send(token_: str, chat_id: str, text: str) -> SendResult:
        rec.locked_during_send.append(lock.locked())
        rec.sent.append((token_, chat_id, text))
        return SendResult(ok=True) if send_ok else SendResult(ok=False, error="boom")

    deps = RunDeps(
        repo=repo,
        analysis_store=store,
        provider_factory=lambda: FakeProvider(rec, provider_fails),
        scan=scan,
        scan_lock=lock,
        previous_action=lambda symbol, tf, bar: prior.get(symbol),
        telegram_token=token,
        send=send,
        clock=clock or FakeClock(),
        default_chat_id=chat,
        analyse=analyse,  # type: ignore[arg-type]
        guard=RunGuard(),
    )
    return deps, rec, repo


def stored_schedule(repo: SqliteScheduleRepository, **changes: object) -> Schedule:
    base = Schedule(
        name="s",
        source="demo",
        tf="1h",
        symbols=("EURUSD",),
        frequency="1h",
    )
    return repo.add(Schedule(**{**base.__dict__, **changes}))
