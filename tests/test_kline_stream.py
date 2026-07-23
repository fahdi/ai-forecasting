"""
Tests for the live kline websocket consumer (issue #3, PRD §4.1 R4, §6).

The websocket is faked: `connect` is an injectable async factory yielding
messages. Only closed candles may be persisted; drops must reconnect, and
malformed messages must never crash the consumer.
"""

import json

import pandas as pd
import pytest
from sqlalchemy import create_engine

from app.services.kline_store import count_klines, create_tables
from app.services.kline_stream import KlineStreamConsumer

FOUR_H_MS = 4 * 3_600_000


def kline_message(symbol: str, open_time_ms: int, closed: bool, close: float = 100.0) -> str:
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@kline_4h",
            "data": {
                "e": "kline",
                "k": {
                    "t": open_time_ms,
                    "T": open_time_ms + FOUR_H_MS - 1,
                    "s": symbol,
                    "i": "4h",
                    "o": str(close),
                    "h": str(close * 1.01),
                    "l": str(close * 0.99),
                    "c": str(close),
                    "v": "42.0",
                    "x": closed,
                },
            },
        }
    )


class FakeConnection:
    def __init__(self, messages):
        self.messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        item = self.messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_connect(batches):
    """Async factory returning one FakeConnection per call (per reconnect)."""
    calls = {"n": 0}

    async def connect():
        batch = batches[min(calls["n"], len(batches) - 1)]
        calls["n"] += 1
        return FakeConnection(batch)

    connect.calls = calls
    return connect


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    create_tables(eng)
    return eng


@pytest.mark.asyncio
async def test_closed_candle_persisted(engine):
    connect = make_connect([[kline_message("BTCUSDT", 0, closed=True)]])
    consumer = KlineStreamConsumer(engine, ["BTCUSDT"], "4h", connect=connect)
    await consumer.run(max_connections=1)
    assert count_klines(engine, "BTCUSDT", "4h") == 1


@pytest.mark.asyncio
async def test_open_candle_not_persisted_but_freshness_updated(engine):
    connect = make_connect([[kline_message("BTCUSDT", 0, closed=False)]])
    consumer = KlineStreamConsumer(engine, ["BTCUSDT"], "4h", connect=connect)
    await consumer.run(max_connections=1)
    assert count_klines(engine, "BTCUSDT", "4h") == 0
    assert consumer.last_event_time("BTCUSDT") is not None


@pytest.mark.asyncio
async def test_malformed_messages_skipped(engine):
    connect = make_connect(
        [["not json", json.dumps({"unexpected": True}),
          kline_message("BTCUSDT", 0, closed=True)]]
    )
    consumer = KlineStreamConsumer(engine, ["BTCUSDT"], "4h", connect=connect)
    await consumer.run(max_connections=1)
    assert count_klines(engine, "BTCUSDT", "4h") == 1


@pytest.mark.asyncio
async def test_connection_error_triggers_reconnect(engine):
    batches = [
        [kline_message("BTCUSDT", 0, closed=True), ConnectionError("dropped")],
        [kline_message("BTCUSDT", FOUR_H_MS, closed=True)],
    ]
    connect = make_connect(batches)
    consumer = KlineStreamConsumer(
        engine, ["BTCUSDT"], "4h", connect=connect, reconnect_delay=0
    )
    await consumer.run(max_connections=2)
    assert connect.calls["n"] == 2
    assert count_klines(engine, "BTCUSDT", "4h") == 2


@pytest.mark.asyncio
async def test_staleness_per_pair(engine):
    connect = make_connect([[kline_message("BTCUSDT", 0, closed=True)]])
    fixed_now = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    consumer = KlineStreamConsumer(
        engine, ["BTCUSDT", "ETHUSDT"], "4h",
        connect=connect, now_fn=lambda: fixed_now,
    )
    await consumer.run(max_connections=1)
    # BTC saw an event "now"-ish? Its event time is epoch 0 -> ancient -> stale.
    assert consumer.is_stale("BTCUSDT") is True
    # ETH never saw any event -> stale by definition.
    assert consumer.is_stale("ETHUSDT") is True

    fresh_now = pd.Timestamp(FOUR_H_MS, unit="ms", tz="UTC")
    consumer2 = KlineStreamConsumer(
        engine, ["BTCUSDT"], "4h",
        connect=make_connect([[kline_message("BTCUSDT", 0, closed=True)]]),
        now_fn=lambda: fresh_now,
    )
    await consumer2.run(max_connections=1)
    assert consumer2.is_stale("BTCUSDT") is False
