"""
Tests for the Binance klines backfill pipeline (issue #2, PRD §4.1 R2/R4).

Storage is exercised against in-memory SQLite through the same SQLAlchemy
code that targets PostgreSQL in production; HTTP is always faked.
"""

import pandas as pd
import pytest
from sqlalchemy import create_engine

from app.services.kline_store import (
    count_klines,
    create_tables,
    find_gaps,
    load_klines,
    upsert_klines,
)
from app.services.kline_backfill import (
    KlineValidationError,
    TransientFetchError,
    backfill,
    parse_binance_klines,
)

HOUR_MS = 3_600_000
FOUR_H_MS = 4 * HOUR_MS


def raw_kline(open_time_ms: int, close: float = 100.0) -> list:
    """A row in Binance REST format."""
    return [
        open_time_ms,
        str(close),          # open
        str(close * 1.01),   # high
        str(close * 0.99),   # low
        str(close),          # close
        "123.4",             # volume
        open_time_ms + FOUR_H_MS - 1,  # close time
        "0", 0, "0", "0", "0",
    ]


def make_rows(n: int, start_ms: int = 0) -> list:
    return [raw_kline(start_ms + i * FOUR_H_MS) for i in range(n)]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    create_tables(eng)
    return eng


class TestStore:
    def test_upsert_idempotent(self, engine):
        rows = parse_binance_klines("BTCUSDT", "4h", make_rows(10))
        upsert_klines(engine, rows)
        upsert_klines(engine, rows)
        assert count_klines(engine, "BTCUSDT", "4h") == 10

    def test_load_returns_ordered_frame(self, engine):
        rows = parse_binance_klines("BTCUSDT", "4h", make_rows(5))
        upsert_klines(engine, list(reversed(rows)))
        frame = load_klines(engine, "BTCUSDT", "4h")
        assert list(frame.columns) == ["open_time", "open", "high", "low", "close", "volume"]
        assert frame["open_time"].is_monotonic_increasing
        assert len(frame) == 5

    def test_gap_detection(self, engine):
        rows = parse_binance_klines("BTCUSDT", "4h", make_rows(10))
        del rows[4]  # remove one candle
        upsert_klines(engine, rows)
        gaps = find_gaps(engine, "BTCUSDT", "4h")
        assert len(gaps) == 1
        assert gaps[0] == (pd.Timestamp(4 * FOUR_H_MS, unit="ms", tz="UTC"),
                           pd.Timestamp(5 * FOUR_H_MS, unit="ms", tz="UTC"))

    def test_no_gaps_when_contiguous(self, engine):
        upsert_klines(engine, parse_binance_klines("BTCUSDT", "4h", make_rows(10)))
        assert find_gaps(engine, "BTCUSDT", "4h") == []


class TestValidation:
    def test_high_below_low_rejected(self):
        bad = raw_kline(0)
        bad[2], bad[3] = "90.0", "110.0"  # high < low
        with pytest.raises(KlineValidationError, match="high"):
            parse_binance_klines("BTCUSDT", "4h", [bad])

    def test_non_positive_price_rejected(self):
        bad = raw_kline(0)
        bad[4] = "0"
        with pytest.raises(KlineValidationError, match="positive"):
            parse_binance_klines("BTCUSDT", "4h", [bad])


class TestBackfill:
    def test_paginates_until_exhausted(self, engine):
        pages = [make_rows(1000, 0), make_rows(500, 1000 * FOUR_H_MS), []]
        calls = []

        def fetch(symbol, interval, start_ms, limit):
            calls.append(start_ms)
            return pages.pop(0)

        stored = backfill(fetch, engine, "BTCUSDT", "4h", start_ms=0)
        assert stored == 1500
        assert count_klines(engine, "BTCUSDT", "4h") == 1500
        # Each page starts one interval after the previous page's last candle.
        assert calls[1] == 1000 * FOUR_H_MS
        assert calls[2] == 1500 * FOUR_H_MS

    def test_transient_errors_retried(self, engine):
        attempts = {"n": 0}

        def flaky_fetch(symbol, interval, start_ms, limit):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise TransientFetchError("http 429")
            return make_rows(10) if attempts["n"] == 3 else []

        stored = backfill(flaky_fetch, engine, "BTCUSDT", "4h", start_ms=0,
                          retry_sleep=0)
        assert stored == 10

    def test_retries_exhausted_raises(self, engine):
        def always_fails(symbol, interval, start_ms, limit):
            raise TransientFetchError("http 500")

        with pytest.raises(TransientFetchError):
            backfill(always_fails, engine, "BTCUSDT", "4h", start_ms=0,
                     retry_sleep=0, max_retries=3)
