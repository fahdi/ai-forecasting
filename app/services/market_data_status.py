"""
Market data freshness for /health/detailed.

The other health components answer "can this process reach its dependencies".
None of them answer the question the product depends on: is market data still
arriving? On 2026-08-03 Binance started returning HTTP 451 to this host, the
kline ingestor and freqtrade both exited, and the endpoint reported "healthy"
for 32 hours.

Freshness is measured from the newest kline the ingestor persisted rather than
from process liveness, so an ingestor that is up but no longer ingesting reads
as stale too.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

INTERVAL_SECONDS = {
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}

# One missed bar is a blip (a reconnect, a slow close); two and a half means
# the feed is not coming back on its own.
STALE_AFTER_INTERVALS = 2.5


def market_data_status(
    newest_open_time_ms: Optional[int],
    interval: str = "4h",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Judge the freshness of the newest persisted kline."""
    now = now or datetime.utcnow()

    if newest_open_time_ms is None:
        return {
            "status": "missing",
            "message": "No klines have ever been ingested",
            "interval": interval,
            "newest_kline": None,
            "age_hours": None,
        }

    newest = datetime.fromtimestamp(newest_open_time_ms / 1000.0, tz=timezone.utc).replace(
        tzinfo=None
    )
    # Clock skew between the ingestor host and this one must not read as stale.
    age_seconds = max(0.0, (now - newest).total_seconds())
    age_hours = age_seconds / 3600.0

    common = {
        "interval": interval,
        "newest_kline": newest.isoformat(),
        "age_hours": round(age_hours, 2),
    }

    window = INTERVAL_SECONDS.get(interval)
    if window is None:
        return {
            "status": "unknown",
            "message": f"No staleness threshold defined for interval {interval!r}",
            **common,
        }

    if age_seconds > window * STALE_AFTER_INTERVALS:
        return {
            "status": "stale",
            "message": (
                f"Newest {interval} kline is {age_hours:.1f}h old; "
                "market data has stopped arriving"
            ),
            **common,
        }

    return {
        "status": "healthy",
        "message": f"Newest {interval} kline is {age_hours:.1f}h old",
        **common,
    }
