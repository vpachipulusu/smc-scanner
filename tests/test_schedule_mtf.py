"""The runner hands a schedule's MTF flags to the scan and the analyst."""

from pathlib import Path

import pytest
from mtf_support import HIT_FRAME, SWING, TfLoader, zigzag
from schedule_support import FakeClock

from smc_scanner.ai.providers import FakeProvider
from smc_scanner.ai.store import SqliteAnalysisStore
from smc_scanner.ai_cli import FrameCache
from smc_scanner.schedule.runner import ScanData, default_analyse, make_scan_fn
from smc_scanner.schedule.store import Schedule
from smc_scanner.strategy import Strategy
from smc_scanner.strategy.builtin import SMC_DEFAULT

# a scheduled scan takes its swing length from the strategy
SHORT_SWING = Strategy.model_validate(
    {**SMC_DEFAULT.model_dump(), "slug": "short-swing", "builtin": False, "swing_length": SWING}
)
HOLD = '{"action": "HOLD", "confidence": 40, "reasons": ["weak"], "summary": "No edge."}'


def _schedule(**changes: object) -> Schedule:
    base = Schedule(name="s", source="demo", tf="1h", symbols=("EURUSD",), frequency="1h", id=1)
    return Schedule(**{**base.__dict__, "min_score": 0, **changes})


def _loader(htf_drift: int = 1) -> TfLoader:
    return TfLoader(
        {
            ("EURUSD", "1h"): HIT_FRAME,
            ("EURUSD", "4h"): zigzag(htf_drift),
            ("EURUSD", "30m"): zigzag(-1),
        }
    )


def _scan(schedule: Schedule, loader: TfLoader) -> ScanData:
    return make_scan_fn(loader_factory=lambda _: loader)(schedule, SHORT_SWING)


def test_scan_without_mtf_keeps_only_the_scan_timeframe() -> None:
    data = _scan(_schedule(), _loader())

    assert set(data.all_frames) == {("EURUSD", "1h")}
    assert set(data.frames) == {"EURUSD"}


def test_scan_with_mtf_keeps_the_neighbour_frames_and_the_primary_frame_map() -> None:
    data = _scan(_schedule(mtf=True), _loader())

    assert {("EURUSD", "1h"), ("EURUSD", "4h"), ("EURUSD", "30m")} <= set(data.all_frames)
    assert data.frames["EURUSD"] is HIT_FRAME  # the HTF load must not replace the scan frame
    assert len(data.rows) == 1


def test_scan_applies_the_alignment_filter() -> None:
    kept = _scan(_schedule(mtf=True, require_htf_aligned=True), _loader(1))
    dropped = _scan(_schedule(mtf=True, require_htf_aligned=True), _loader(-1))

    assert len(kept.rows) == 1
    assert dropped.rows == ()


def test_frame_cache_keeps_the_first_timeframe_as_primary() -> None:
    cache = FrameCache(_loader())

    cache.load("EURUSD", "1h", 10)
    cache.load("EURUSD", "4h", 10)

    assert cache.frames["EURUSD"] is HIT_FRAME
    assert cache.frames_by_timeframe[("EURUSD", "4h")] is not HIT_FRAME


@pytest.mark.parametrize("mtf", [False, True])
def test_default_analyse_sends_mtf_blocks_only_for_mtf_schedules(tmp_path: Path, mtf: bool) -> None:
    schedule = _schedule(mtf=mtf)
    data = _scan(schedule, _loader())
    provider = FakeProvider([HOLD])

    results = default_analyse(
        data, schedule, provider, SqliteAnalysisStore(tmp_path / "smc.db"), FakeClock()
    )

    assert [r.status for r in results] == ["analysed"]
    [(_, user)] = provider.calls
    assert ('"htf"' in user) is mtf
    assert ('"ltf"' in user) is mtf
