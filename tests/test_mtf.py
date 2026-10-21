"""Neighbour timeframes, HTF bias, last BOS, the alignment filter and fail-soft MTF inputs."""

from dataclasses import replace

import pandas as pd
import pytest
from mtf_support import HIT_FRAME, SWING, zigzag

from smc_scanner.config import TIMEFRAMES, neighbour_timeframes
from smc_scanner.models import Bias, ScanRow
from smc_scanner.mtf import (
    MtfInputs,
    TimeframeView,
    build_mtf_inputs,
    htf_allows,
    timeframe_view,
)
from smc_scanner.scanner import ScanOptions, scan_instrument

OPTIONS = ScanOptions(swing_length=SWING)


def _row() -> ScanRow:
    return next(r for r in scan_instrument("TEST", HIT_FRAME, OPTIONS) if r.zone == "bull FVG")


@pytest.mark.parametrize(
    ("tf", "expected"),
    [
        ("5m", ("15m", None)),
        ("15m", ("30m", "5m")),
        ("1h", ("4h", "30m")),
        ("4h", ("1d", "1h")),
        ("1d", (None, "4h")),
    ],
)
def test_neighbour_timeframes_follow_the_timeframe_order(
    tf: str, expected: tuple[str | None, str | None]
) -> None:
    assert neighbour_timeframes(tf) == expected


def test_every_timeframe_has_a_consistent_neighbour_chain() -> None:
    for earlier, later in zip(TIMEFRAMES, TIMEFRAMES[1:], strict=False):
        assert neighbour_timeframes(earlier)[0] == later
        assert neighbour_timeframes(later)[1] == earlier


def test_unknown_timeframe_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeframe"):
        neighbour_timeframes("1w")


@pytest.mark.parametrize(("drift", "bias"), [(1, "bullish"), (-1, "bearish"), (0, "range")])
def test_timeframe_view_reports_the_bias(drift: int, bias: str) -> None:
    view = timeframe_view(zigzag(drift), "4h", SWING)

    assert view.timeframe == "4h"
    assert view.bias == bias


def test_last_bos_is_the_most_recent_break_with_a_time() -> None:
    view = timeframe_view(zigzag(1), "4h", SWING)

    assert view.last_bos is not None
    assert view.last_bos.direction == "bullish"
    assert pd.Timestamp(view.last_bos.time) <= pd.Timestamp(zigzag(1)["time"].iloc[-1])


def test_flat_frame_has_no_bos() -> None:
    flat = HIT_FRAME.iloc[:16]

    assert timeframe_view(flat, "4h", SWING).last_bos is None


@pytest.mark.parametrize(
    ("bias", "allowed"),
    [("bullish", True), ("bearish", False), ("range", False), (None, True)],
)
def test_htf_filter_keeps_agreeing_and_unknown_bias(bias: Bias | None, allowed: bool) -> None:
    assert htf_allows(_row(), bias) is allowed


def test_bearish_zone_needs_a_bearish_htf() -> None:
    row = _row()
    bear = replace(row, zone="bear OB")

    assert htf_allows(bear, "bearish") is True
    assert htf_allows(bear, "bullish") is False


def test_build_inputs_uses_neighbours_and_marks_alignment() -> None:
    frames = {("TEST", "4h"): zigzag(1), ("TEST", "30m"): zigzag(-1)}

    inputs = build_mtf_inputs(_row(), "1h", SWING, lambda s, tf: frames.get((s, tf)))

    assert (inputs.higher, inputs.lower) == ("4h", "30m")
    assert inputs.htf is not None and inputs.htf.bias == "bullish"
    assert inputs.ltf is not None and inputs.ltf.bias == "bearish"


def test_missing_frames_leave_the_views_empty_but_keep_the_timeframes() -> None:
    inputs = build_mtf_inputs(_row(), "1h", SWING, lambda s, tf: None)

    assert inputs == MtfInputs(higher="4h", lower="30m", htf=None, ltf=None)


def test_a_broken_frame_degrades_to_no_view() -> None:
    broken = pd.DataFrame({"time": [], "open": []})

    inputs = build_mtf_inputs(_row(), "1d", SWING, lambda s, tf: broken)

    assert inputs.higher is None and inputs.htf is None and inputs.ltf is None
    assert inputs.lower == "4h"


def test_view_is_immutable() -> None:
    view = TimeframeView("4h", "range", None)
    with pytest.raises(AttributeError):
        setattr(view, "bias", "bullish")  # noqa: B010
