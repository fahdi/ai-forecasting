"""
How much of the expected kline history do we actually hold?

kline_store.find_gaps() compares consecutive stored candles, so it only ever
finds INTERIOR holes. An outage that is still ongoing has no right-hand candle,
so find_gaps() reports nothing for it. That is the live production case: klines
stale since 2026-07-31 with no interior gap at all, and every existing check
calls it fine.

Coverage is measured against a window instead: how many closed bars should sit
on the interval grid between window_start and the last closed bar, versus how
many are stored. That counts leading, interior and trailing shortfalls alike.

Pure function over scalars, matching market_data_status and backup_status, so
the health endpoint runs one cheap bounded aggregate rather than pulling every
open_time into Python on each poll.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

INTERVAL_MS = {
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

# Owned here so renaming a status cannot silently leave /health/detailed green,
# the same discipline as app/services/backup_status.py.
DEGRADED_STATUSES = frozenset({"degraded", "missing"})


def _iso(open_time_ms: Optional[int]) -> Optional[str]:
    if open_time_ms is None:
        return None
    return (
        datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc)
        .replace(tzinfo=None)
        .isoformat()
    )


def coverage_status(
    stored_bars: Optional[int],
    oldest_open_time_ms: Optional[int],
    newest_open_time_ms: Optional[int],
    interval: str,
    window_start_ms: int,
    now_ms: int,
) -> Dict[str, Any]:
    """Judge how complete the stored history is over a window."""
    base = {
        "interval": interval,
        "stored_bars": stored_bars,
        "expected_bars": None,
        "missing_bars": None,
        "coverage_pct": None,
        "newest_kline": _iso(newest_open_time_ms),
    }

    step = INTERVAL_MS.get(interval)
    if step is None:
        return {
            **base,
            "status": "unknown",
            "message": f"No bar length defined for interval {interval!r}",
        }

    # The bar opening at grid_now is still open, so the newest bar that should
    # exist is the one before it.
    grid_now = (now_ms // step) * step
    last_expected = grid_now - step
    # The ingestor stores only closed candles, but if an open one was stored
    # anyway it must not read as a surplus.
    if newest_open_time_ms is not None and newest_open_time_ms >= grid_now:
        last_expected = newest_open_time_ms

    # Align the window start up onto the grid.
    aligned_start = -(-window_start_ms // step) * step
    if last_expected < aligned_start:
        return {
            **base,
            "status": "unknown",
            "message": "Window contains no closed bars yet",
        }

    expected = (last_expected - aligned_start) // step + 1
    base["expected_bars"] = expected

    if not stored_bars:
        return {
            **base,
            "status": "missing",
            "message": f"No klines stored for the last {expected} expected {interval} bars",
            "missing_bars": expected,
            "coverage_pct": 0.0,
        }

    if stored_bars > expected:
        return {
            **base,
            "status": "unknown",
            "message": (
                f"{stored_bars} bars stored against {expected} expected; the table holds "
                "duplicate or off-grid rows, so coverage cannot be judged"
            ),
        }

    missing = expected - stored_bars
    coverage_pct = round(100.0 * stored_bars / expected, 2)
    base.update({"missing_bars": missing, "coverage_pct": coverage_pct})

    if missing == 0:
        return {
            **base,
            "status": "healthy",
            "message": f"All {expected} expected {interval} bars are stored",
        }

    return {
        **base,
        "status": "degraded",
        "message": (
            f"{missing} of {expected} expected {interval} bars are missing "
            f"({coverage_pct}% coverage); history has holes"
        ),
    }
