"""
Live kline updates via Binance websocket (issue #3, PRD §4.1 R4, §6).

Consumes the combined kline stream, persists ONLY closed candles, tracks
per-pair freshness for the fail-closed staleness rule (R9), and reconnects
with backoff — a dropped connection never crashes the service.
"""

import asyncio
import json
import re
from typing import Callable, Dict, List, Optional

import pandas as pd
from sqlalchemy.engine import Engine
from structlog import get_logger

from app.services.kline_backfill import parse_binance_klines
from app.services.kline_store import INTERVAL_MS, upsert_klines

logger = get_logger()

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

# Rejections that will not succeed on retry: the exchange is refusing this
# client, not failing. 451 is the one that bit us (restricted location);
# 401/403 mean the same thing for credentials. 408 and 429 are explicitly not
# here - a timeout or a rate limit does recover, and retrying is correct.
PERMANENT_REJECTION_STATUSES = frozenset({401, 403, 451})

_HTTP_STATUS_IN_MESSAGE = re.compile(r"HTTP (\d{3})")


class PermanentStreamRejection(RuntimeError):
    """The exchange refused the connection in a way retrying cannot fix."""


def _status_of(exc: BaseException) -> Optional[int]:
    """HTTP status behind a websocket rejection, if there is one.

    Different `websockets` versions expose it as status_code, status, or only
    in the message text, so fall back to parsing rather than depending on one.
    """
    for attribute in ("status_code", "status"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
        code = getattr(value, "value", None)  # HTTPStatus enum
        if isinstance(code, int):
            return code

    match = _HTTP_STATUS_IN_MESSAGE.search(str(exc))
    return int(match.group(1)) if match else None


def is_permanent_rejection(exc: BaseException) -> bool:
    """True when reconnecting is futile and the process should stop."""
    return _status_of(exc) in PERMANENT_REJECTION_STATUSES


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
        heartbeat_fn: Optional[Callable[[], None]] = None,
        heartbeat_interval: float = 60.0,
    ):
        self.engine = engine
        self.pairs = pairs
        self.interval = interval
        self._connect = connect or binance_connect_factory(pairs, interval)
        self.reconnect_delay = reconnect_delay
        self._now = now_fn or (lambda: pd.Timestamp.now(tz="UTC"))
        self._last_event: Dict[str, pd.Timestamp] = {}
        self._heartbeat_fn = heartbeat_fn
        self._heartbeat_interval = heartbeat_interval
        self._last_heartbeat: Optional[pd.Timestamp] = None

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

    def _maybe_heartbeat(self) -> None:
        """R14 liveness ping — rate-limited, and never allowed to break the
        consumer if the monitoring endpoint is down."""
        if self._heartbeat_fn is None:
            return
        now = self._now()
        if (self._last_heartbeat is not None
                and (now - self._last_heartbeat).total_seconds()
                < self._heartbeat_interval):
            return
        try:
            self._heartbeat_fn()
            self._last_heartbeat = now
        except Exception as exc:
            logger.warning("Heartbeat ping failed", error=str(exc))

    async def run(self, max_connections: Optional[int] = None) -> None:
        connections = 0
        while True:
            connections += 1
            try:
                connection = await self._connect()
                async for message in connection:
                    self._process(message)
                    self._maybe_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Spinning on a rejection that can never succeed is how three
                # days of missing market data looked exactly like reconnect
                # churn. Stop, so the process exits nonzero and the container
                # restart count says something.
                if is_permanent_rejection(exc):
                    logger.error(
                        "Kline stream permanently rejected; not retrying",
                        error=str(exc),
                        status=_status_of(exc),
                    )
                    raise PermanentStreamRejection(str(exc)) from exc
                logger.warning("Kline stream dropped; will reconnect",
                               error=str(exc))
            if max_connections is not None and connections >= max_connections:
                return
            if self.reconnect_delay:
                await asyncio.sleep(self.reconnect_delay)
