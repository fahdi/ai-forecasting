"""
Live kline updates via Binance websocket (issue #3, PRD §4.1 R4, §6).

Consumes the combined kline stream, persists ONLY closed candles, tracks
per-pair freshness for the fail-closed staleness rule (R9), and reconnects
with backoff — a dropped connection never crashes the service.
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional

import pandas as pd
from sqlalchemy.engine import Engine
from structlog import get_logger

from app.services.kline_backfill import parse_binance_klines
from app.services.kline_store import INTERVAL_MS, upsert_klines

logger = get_logger()

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"


def binance_connect_factory(pairs: List[str], interval: str) -> Callable:
    """Real websocket connection factory (lazy import of `websockets`)."""
    streams = "/".join(f"{p.lower()}@kline_{interval}" for p in pairs)
    url = f"{BINANCE_WS_BASE}?streams={streams}"

    async def connect():
        import websockets

        return await websockets.connect(url, ping_interval=20, ping_timeout=20)

    return connect


class KlineStreamConsumer:
    def __init__(
        self,
        engine: Engine,
        pairs: List[str],
        interval: str,
        connect: Optional[Callable] = None,
        reconnect_delay: float = 5.0,
        now_fn: Callable[[], pd.Timestamp] = None,
    ):
        self.engine = engine
        self.pairs = pairs
        self.interval = interval
        self._connect = connect or binance_connect_factory(pairs, interval)
        self.reconnect_delay = reconnect_delay
        self._now = now_fn or (lambda: pd.Timestamp.now(tz="UTC"))
        self._last_event: Dict[str, pd.Timestamp] = {}

    def last_event_time(self, pair: str) -> Optional[pd.Timestamp]:
        return self._last_event.get(pair)

    def is_stale(self, pair: str) -> bool:
        """R9 rule: no event, or last candle close older than 2 intervals."""
        last = self._last_event.get(pair)
        if last is None:
            return True
        stale_after = pd.Timedelta(milliseconds=2 * INTERVAL_MS[self.interval])
        return (self._now() - last) > stale_after

    def _process(self, message: str) -> None:
        try:
            payload = json.loads(message)
            kline = payload["data"]["k"]
            symbol = kline["s"]
            self._last_event[symbol] = pd.Timestamp(kline["T"], unit="ms", tz="UTC")
            if not kline["x"]:
                return  # in-progress candle: freshness only, never persisted
            rows = parse_binance_klines(
                symbol,
                self.interval,
                [[kline["t"], kline["o"], kline["h"], kline["l"], kline["c"],
                  kline["v"], kline["T"]]],
            )
            upsert_klines(self.engine, rows)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping malformed kline message", error=str(exc))

    async def run(self, max_connections: Optional[int] = None) -> None:
        connections = 0
        while True:
            connections += 1
            try:
                connection = await self._connect()
                async for message in connection:
                    self._process(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Kline stream dropped; will reconnect",
                               error=str(exc))
            if max_connections is not None and connections >= max_connections:
                return
            if self.reconnect_delay:
                await asyncio.sleep(self.reconnect_delay)
