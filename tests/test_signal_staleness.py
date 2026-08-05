"""
The R9 staleness boundary (app.services.signal_service._is_stale).

This single boolean decides whether the bot may open a position. It is the
only reason no orders are being placed against the 120-hour-old klines
production is currently serving.

It was exercised at 0 hours (fresh) and 16 hours / 3 days (stale), which
leaves the boundary untested in the direction that costs money. Widening
STALE_AFTER from 8h to 10h keeps both of those cases classified correctly
while letting the bot trade on candles up to 14 hours old. These tests pin the
threshold in absolute terms so a change to either constant has to be
deliberate.
"""

import pandas as pd
import pytest

from app.services.signal_service import (
    INTERVAL_DELTA,
    STALE_AFTER,
    _is_stale,
)

NOW = pd.Timestamp("2026-08-05T12:00:00Z")

# A candle stamped at open_time T closes at T + INTERVAL_DELTA, and is stale
# once that close is more than STALE_AFTER in the past. So the bot stops
# entering on a candle 12 hours after it opened.
EFFECTIVE_WINDOW_HOURS = 12.0


def _opened(hours_ago: float) -> pd.Timestamp:
    return NOW - pd.Timedelta(hours=hours_ago)


def test_the_effective_window_is_twelve_hours():
    """Pinned in absolute hours, not re-derived from the constants.

    Restating the formula would pass no matter what the constants became.
    """
    window = (INTERVAL_DELTA + STALE_AFTER).total_seconds() / 3600
    assert window == EFFECTIVE_WINDOW_HOURS


def test_a_just_fresh_candle_permits_entry():
    assert _is_stale(_opened(EFFECTIVE_WINDOW_HOURS - 0.1), now=NOW) is False


def test_a_just_stale_candle_blocks_entry():
    assert _is_stale(_opened(EFFECTIVE_WINDOW_HOURS + 0.1), now=NOW) is True


def test_exactly_on_the_boundary_is_not_yet_stale():
    """Documents the tie-break: strictly greater-than, so the edge trades."""
    assert _is_stale(_opened(EFFECTIVE_WINDOW_HOURS), now=NOW) is False


@pytest.mark.parametrize("hours_ago", [0, 4, 8, 11.9])
def test_everything_inside_the_window_is_fresh(hours_ago):
    assert _is_stale(_opened(hours_ago), now=NOW) is False


@pytest.mark.parametrize("hours_ago", [12.1, 16, 24, 120])
def test_everything_beyond_the_window_is_stale(hours_ago):
    """120 hours is what production is serving right now."""
    assert _is_stale(_opened(hours_ago), now=NOW) is True


def test_a_future_candle_is_not_stale():
    """Clock skew between the ingestor and the API must not block trading."""
    assert _is_stale(NOW + pd.Timedelta(hours=1), now=NOW) is False


def test_defaults_to_wall_clock_when_no_now_is_given():
    """The production call site passes no `now`."""
    assert _is_stale(pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=5)) is True
    assert _is_stale(pd.Timestamp.now(tz="UTC")) is False
