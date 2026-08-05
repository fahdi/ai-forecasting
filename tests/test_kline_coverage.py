"""
Kline coverage as a reported health component (issue #48, PRD R4).

app/services/kline_store.py find_gaps() compares CONSECUTIVE stored candles, so
it only ever finds interior holes. An outage that is still ongoing has no
right-hand candle, so find_gaps() returns [] for it. That is exactly the live
production case: klines have been stale since 2026-07-31 and the hole is
invisible to every existing check.

Coverage is therefore measured against a WINDOW - expected bars on the interval
grid versus bars actually stored - which counts leading, interior and trailing
shortfalls alike.

Pure function over scalars, in the shape health.py already uses for
market_data_status and backup_status: the endpoint runs one cheap aggregate and
hands the numbers here.
"""

import pytest

from app.services.kline_coverage import DEGRADED_STATUSES, INTERVAL_MS, coverage_status

H4 = INTERVAL_MS["4h"]
NOW = 1_785_000_000_000  # arbitrary fixed epoch ms
GRID_NOW = (NOW // H4) * H4
LAST_CLOSED = GRID_NOW - H4


def call(stored_bars, oldest=None, newest=None, interval="4h", window_start=None, now=NOW):
    return coverage_status(
        stored_bars=stored_bars,
        oldest_open_time_ms=oldest,
        newest_open_time_ms=newest,
        interval=interval,
        window_start_ms=window_start if window_start is not None else LAST_CLOSED - 99 * H4,
        now_ms=now,
    )


class TestCompleteCoverage:
    def test_a_full_contiguous_window_is_healthy(self):
        result = call(stored_bars=100, oldest=LAST_CLOSED - 99 * H4, newest=LAST_CLOSED)
        assert result["status"] == "healthy"
        assert result["missing_bars"] == 0
        assert result["expected_bars"] == 100
        assert result["coverage_pct"] == 100.0

    def test_the_currently_open_bar_does_not_read_as_a_trailing_gap(self):
        """Off-by-one guard: the open bar is not yet expected."""
        result = call(stored_bars=101, oldest=LAST_CLOSED - 99 * H4, newest=GRID_NOW)
        assert result["status"] == "healthy"
        assert result["missing_bars"] == 0


class TestShortfalls:
    def test_an_interior_hole_is_degraded(self):
        result = call(stored_bars=97, oldest=LAST_CLOSED - 99 * H4, newest=LAST_CLOSED)
        assert result["status"] == "degraded"
        assert result["missing_bars"] == 3

    def test_an_ongoing_outage_is_degraded_even_though_find_gaps_sees_nothing(self):
        """The regression guard for the live production case.

        Newest candle five days old, no interior holes at all, so find_gaps()
        returns []. Coverage must still report the shortfall.
        """
        five_days = (5 * 24 * 60 * 60 * 1000) // H4
        newest = LAST_CLOSED - five_days * H4
        result = call(stored_bars=100 - five_days, oldest=LAST_CLOSED - 99 * H4, newest=newest)

        assert result["status"] == "degraded"
        assert result["missing_bars"] == five_days
        assert result["status"] in DEGRADED_STATUSES

    def test_a_leading_shortfall_is_counted(self):
        """Window opens before the oldest stored candle."""
        result = call(stored_bars=50, oldest=LAST_CLOSED - 49 * H4, newest=LAST_CLOSED)
        assert result["status"] == "degraded"
        assert result["missing_bars"] == 50

    def test_no_klines_at_all_is_missing_not_healthy(self):
        result = call(stored_bars=0, oldest=None, newest=None)
        assert result["status"] == "missing"
        assert result["status"] in DEGRADED_STATUSES


class TestUnusableInputs:
    def test_more_stored_than_expected_is_unknown_never_negative(self):
        """Duplicate or off-grid rows must not produce a negative shortfall."""
        result = call(stored_bars=500, oldest=LAST_CLOSED - 99 * H4, newest=LAST_CLOSED)
        assert result["status"] == "unknown"
        assert result["missing_bars"] is None or result["missing_bars"] >= 0

    def test_an_unknown_interval_does_not_raise(self):
        result = call(stored_bars=10, oldest=LAST_CLOSED, newest=LAST_CLOSED, interval="7m")
        assert result["status"] == "unknown"

    def test_unknown_is_not_treated_as_healthy(self):
        assert "unknown" not in {"healthy"}
        result = call(stored_bars=10, interval="7m")
        assert result["status"] != "healthy"

    def test_a_window_with_no_closed_bars_yet_is_unknown(self):
        result = call(stored_bars=0, window_start=GRID_NOW + H4)
        assert result["status"] in {"unknown", "missing"}


class TestReportShape:
    def test_every_field_the_dashboard_needs_is_present(self):
        result = call(stored_bars=97, oldest=LAST_CLOSED - 99 * H4, newest=LAST_CLOSED)
        for key in (
            "status",
            "message",
            "interval",
            "expected_bars",
            "stored_bars",
            "missing_bars",
            "coverage_pct",
            "newest_kline",
        ):
            assert key in result, key

    def test_the_message_names_the_shortfall(self):
        result = call(stored_bars=97, oldest=LAST_CLOSED - 99 * H4, newest=LAST_CLOSED)
        assert "3" in result["message"]

    def test_degraded_statuses_owns_what_counts_as_a_fault(self):
        """Same pattern as backup_status: renaming a status cannot silently
        leave health green."""
        assert DEGRADED_STATUSES == frozenset({"degraded", "missing"})


class TestAgainstRealStoredKlines:
    def test_the_aggregate_health_runs_matches_the_pure_function(self, tmp_path):
        """Integration: real table, real hole, same query shape health uses."""
        from sqlalchemy import create_engine, text

        from app.services.kline_store import create_tables, upsert_klines

        engine = create_engine("sqlite://")
        create_tables(engine)

        start = LAST_CLOSED - 49 * H4
        rows = []
        for i in range(50):
            if 10 <= i < 13:  # a three-bar hole
                continue
            open_time = start + i * H4
            rows.append(
                {
                    "pair": "BTCUSDT",
                    "interval": "4h",
                    "open_time_ms": open_time,
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 10.0,
                }
            )
        upsert_klines(engine, rows)

        with engine.connect() as conn:
            stored, oldest, newest = conn.execute(
                text(
                    'SELECT COUNT(*), MIN(open_time_ms), MAX(open_time_ms) FROM klines '
                    'WHERE pair = :pair AND "interval" = :interval '
                    'AND open_time_ms >= :window_start'
                ),
                {"pair": "BTCUSDT", "interval": "4h", "window_start": start},
            ).one()

        result = coverage_status(
            stored_bars=stored,
            oldest_open_time_ms=oldest,
            newest_open_time_ms=newest,
            interval="4h",
            window_start_ms=start,
            now_ms=NOW,
        )
        assert result["missing_bars"] == 3
        assert result["status"] == "degraded"
