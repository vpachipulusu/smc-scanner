"""Delivery rules for a verdict: pure functions returning ``(deliver, skip_reason)``.

The skip reason is a short stable code so skips can be logged and counted. Rules apply in a
fixed order: HOLD suppression, minimum confidence, then unchanged-signal suppression.
"""

from dataclasses import dataclass
from typing import Final

SKIP_HOLD: Final = "hold_not_sent"
SKIP_LOW_CONFIDENCE: Final = "below_min_confidence"
SKIP_UNCHANGED: Final = "signal_unchanged"


@dataclass(frozen=True)
class Decision:
    deliver: bool
    skip_reason: str = ""


def decide(
    *,
    action: str,
    confidence: float,
    min_confidence: float,
    only_on_change: bool,
    send_hold: bool,
    previous_action: str | None,
) -> Decision:
    """Whether a verdict should be sent.

    ``previous_action`` is the last stored action for the same symbol and timeframe on an
    earlier bar; None (no history) counts as a change, so a first signal is always sent.
    """
    if action == "HOLD" and not send_hold:
        return Decision(False, SKIP_HOLD)
    if confidence < min_confidence:
        return Decision(False, SKIP_LOW_CONFIDENCE)
    if only_on_change and previous_action == action:
        return Decision(False, SKIP_UNCHANGED)
    return Decision(True)
