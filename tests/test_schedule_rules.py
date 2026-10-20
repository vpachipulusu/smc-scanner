"""Delivery rules: a pure matrix plus the read-only history lookup."""

import itertools

import pytest

from smc_scanner.schedule.rules import (
    SKIP_HOLD,
    SKIP_LOW_CONFIDENCE,
    SKIP_UNCHANGED,
    Decision,
    decide,
)


def _decide(
    action: str = "BUY",
    confidence: float = 80.0,
    *,
    min_confidence: float = 0.0,
    only_on_change: bool = False,
    send_hold: bool = False,
    previous: str | None = None,
) -> Decision:
    return decide(
        action=action,
        confidence=confidence,
        min_confidence=min_confidence,
        only_on_change=only_on_change,
        send_hold=send_hold,
        previous_action=previous,
    )


def test_plain_signal_is_delivered() -> None:
    assert _decide() == Decision(True, "")


def test_confidence_below_minimum_is_skipped() -> None:
    result = _decide(confidence=59.9, min_confidence=60)

    assert result == Decision(False, SKIP_LOW_CONFIDENCE)


def test_confidence_equal_to_minimum_is_delivered() -> None:
    assert _decide(confidence=60, min_confidence=60).deliver


def test_hold_is_suppressed_unless_send_hold() -> None:
    assert _decide("HOLD") == Decision(False, SKIP_HOLD)
    assert _decide("HOLD", send_hold=True).deliver


def test_hold_still_has_to_meet_min_confidence() -> None:
    result = _decide("HOLD", 10, min_confidence=50, send_hold=True)

    assert result == Decision(False, SKIP_LOW_CONFIDENCE)


def test_unchanged_signal_is_skipped_when_only_on_change() -> None:
    result = _decide("BUY", only_on_change=True, previous="BUY")

    assert result == Decision(False, SKIP_UNCHANGED)


def test_changed_signal_is_delivered_when_only_on_change() -> None:
    assert _decide("SELL", only_on_change=True, previous="BUY").deliver


def test_first_ever_signal_counts_as_a_change() -> None:
    assert _decide("BUY", only_on_change=True, previous=None).deliver


def test_same_signal_is_delivered_when_only_on_change_is_off() -> None:
    assert _decide("BUY", previous="BUY").deliver


def test_unchanged_hold_is_skipped_as_hold_first() -> None:
    assert _decide("HOLD", only_on_change=True, previous="HOLD").skip_reason == SKIP_HOLD


@pytest.mark.parametrize(
    ("action", "send_hold", "only_on_change", "previous"),
    list(
        itertools.product(
            ["BUY", "SELL", "HOLD"], [False, True], [False, True], [None, "BUY", "SELL", "HOLD"]
        )
    ),
)
def test_matrix_decision_is_consistent(
    action: str, send_hold: bool, only_on_change: bool, previous: str | None
) -> None:
    result = _decide(action, send_hold=send_hold, only_on_change=only_on_change, previous=previous)

    expected = not ((action == "HOLD" and not send_hold) or (only_on_change and previous == action))
    assert result.deliver is expected
    assert (result.skip_reason == "") is expected
