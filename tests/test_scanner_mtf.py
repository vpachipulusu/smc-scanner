"""Opt-in higher-timeframe bias on scan rows, the alignment filter and LTF prefetch."""

import pytest
from mtf_support import HIT_FRAME, SWING, TfLoader, zigzag

from smc_scanner.scanner import ScanOptions, run_scan, scan_watchlist

OPTIONS = ScanOptions(swing_length=SWING)


def _loader(htf: object = None) -> TfLoader:
    frames = {("EURUSD", "1h"): HIT_FRAME, ("EURUSD", "30m"): zigzag(1)}
    if htf is not None:
        frames[("EURUSD", "4h")] = htf  # type: ignore[assignment]
    return TfLoader(frames)


def test_default_scan_loads_only_the_scan_timeframe() -> None:
    loader = _loader(zigzag(1))

    result = scan_watchlist(loader, ["EURUSD"], "1h", 100, OPTIONS)

    assert loader.calls == [("EURUSD", "1h")]
    assert len(result.rows) == 1
    assert result.htf_bias == {}


def test_mtf_records_the_htf_bias_for_hit_symbols() -> None:
    loader = _loader(zigzag(-1))

    result = scan_watchlist(loader, ["EURUSD"], "1h", 100, OPTIONS, mtf=True)

    assert result.htf_bias == {"EURUSD": "bearish"}
    assert len(result.rows) == 1  # shown, not filtered
    assert ("EURUSD", "4h") in loader.calls


def test_symbols_without_hits_do_not_load_the_htf() -> None:
    loader = TfLoader({("EURUSD", "1h"): HIT_FRAME.iloc[:16]})

    result = scan_watchlist(loader, ["EURUSD"], "1h", 100, OPTIONS, mtf=True)

    assert result.rows == ()
    assert loader.calls == [("EURUSD", "1h")]


@pytest.mark.parametrize(
    ("htf_drift", "kept"), [(1, True), (-1, False), (0, False)], ids=["agree", "oppose", "range"]
)
def test_require_htf_aligned_drops_rows_the_htf_does_not_confirm(
    htf_drift: int, kept: bool
) -> None:
    loader = _loader(zigzag(htf_drift))

    result = scan_watchlist(
        loader, ["EURUSD"], "1h", 100, OPTIONS, mtf=True, require_htf_aligned=True
    )

    assert bool(result.rows) is kept


def test_unavailable_htf_passes_the_filter() -> None:
    loader = _loader(None)  # no 4h data: the load fails

    result = scan_watchlist(
        loader, ["EURUSD"], "1h", 100, OPTIONS, mtf=True, require_htf_aligned=True
    )

    assert len(result.rows) == 1
    assert result.htf_bias == {"EURUSD": None}
    assert result.failures == ()  # a missing HTF is not a scan failure


def test_top_timeframe_has_no_htf_and_passes() -> None:
    loader = TfLoader({("EURUSD", "1d"): HIT_FRAME})

    result = scan_watchlist(
        loader, ["EURUSD"], "1d", 100, OPTIONS, mtf=True, require_htf_aligned=True
    )

    assert len(result.rows) == 1
    assert result.htf_bias == {"EURUSD": None}


def test_require_without_mtf_is_rejected() -> None:
    with pytest.raises(ValueError, match="mtf"):
        scan_watchlist(_loader(), ["EURUSD"], "1h", 100, OPTIONS, require_htf_aligned=True)


def test_ltf_is_prefetched_only_for_rows_that_reach_the_score_gate() -> None:
    loader = _loader(zigzag(1))
    row_score = scan_watchlist(loader, ["EURUSD"], "1h", 100, OPTIONS).rows[0].score

    high = _loader(zigzag(1))
    scan_watchlist(high, ["EURUSD"], "1h", 100, OPTIONS, mtf=True, ltf_min_score=row_score)
    low = _loader(zigzag(1))
    scan_watchlist(low, ["EURUSD"], "1h", 100, OPTIONS, mtf=True, ltf_min_score=row_score + 1)
    off = _loader(zigzag(1))
    scan_watchlist(off, ["EURUSD"], "1h", 100, OPTIONS, mtf=True)

    assert ("EURUSD", "30m") in high.calls
    assert ("EURUSD", "30m") not in low.calls
    assert ("EURUSD", "30m") not in off.calls


def test_a_failing_ltf_prefetch_is_not_an_error() -> None:
    loader = TfLoader({("EURUSD", "1h"): HIT_FRAME, ("EURUSD", "4h"): zigzag(1)})

    result = scan_watchlist(loader, ["EURUSD"], "1h", 100, OPTIONS, mtf=True, ltf_min_score=0)

    assert result.failures == ()
    assert len(result.rows) == 1


def test_run_scan_forwards_the_flags_and_closes_the_loader() -> None:
    loader = _loader(zigzag(-1))

    result = run_scan(loader, ["EURUSD"], "1h", 100, OPTIONS, mtf=True, require_htf_aligned=True)

    assert result.rows == ()
    assert loader.closed
