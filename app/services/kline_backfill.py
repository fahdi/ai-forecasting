"""
Binance klines backfill (issue #2, PRD §4.1 R2/R4).

`backfill` paginates a fetch function (injectable — the real one uses the
public Binance REST API) and upserts validated candles. Transient failures
are retried with bounded attempts; validation failures are permanent errors.
"""

import time
from typing import Callable, List

from sqlalchemy.engine import Engine

from app.services.kline_store import INTERVAL_MS, upsert_klines

PAGE_LIMIT = 1000

FetchPage = Callable[[str, str, int, int], List[list]]


class KlineValidationError(Exception):
    pass


class TransientFetchError(Exception):
    pass


def parse_binance_klines(pair: str, interval: str, raw_rows: List[list]) -> List[dict]:
    """Convert Binance REST kline rows to storage rows, validating each."""
    rows = []
    for raw in raw_rows:
        row = {
            "pair": pair,
            "interval": interval,
            "open_time_ms": int(raw[0]),
            "open": float(raw[1]),
            "high": float(raw[2]),
            "low": float(raw[3]),
            "close": float(raw[4]),
            "volume": float(raw[5]),
        }
        if min(row["open"], row["high"], row["low"], row["close"]) <= 0:
            raise KlineValidationError(
                f"{pair} {interval} @ {row['open_time_ms']}: prices must be positive"
            )
        if row["high"] < row["low"]:
            raise KlineValidationError(
                f"{pair} {interval} @ {row['open_time_ms']}: high below low"
            )
        if row["volume"] < 0:
            raise KlineValidationError(
                f"{pair} {interval} @ {row['open_time_ms']}: negative volume"
            )
        rows.append(row)
    return rows


def fetch_binance_page(symbol: str, interval: str, start_ms: int, limit: int) -> List[list]:
    """Real fetch against the Binance public REST API."""
    import httpx

    try:
        response = httpx.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval,
                    "startTime": start_ms, "limit": limit},
            timeout=15.0,
        )
    except httpx.TransportError as exc:
        raise TransientFetchError(str(exc)) from exc
    if response.status_code in (429, 418) or response.status_code >= 500:
        raise TransientFetchError(f"http {response.status_code}")
    response.raise_for_status()
    return response.json()


def backfill(
    fetch: FetchPage,
    engine: Engine,
    pair: str,
    interval: str,
    start_ms: int,
    end_ms: int = None,
    max_retries: int = 5,
    retry_sleep: float = 2.0,
) -> int:
    """Page through candles from start_ms until exhausted (or end_ms). Returns
    the number of candles fetched and upserted."""
    step = INTERVAL_MS[interval]
    cursor = start_ms
    total = 0
    while True:
        attempts = 0
        while True:
            try:
                raw_rows = fetch(pair, interval, cursor, PAGE_LIMIT)
                break
            except TransientFetchError:
                attempts += 1
                if attempts >= max_retries:
                    raise
                time.sleep(retry_sleep * attempts)
        if not raw_rows:
            return total
        rows = parse_binance_klines(pair, interval, raw_rows)
        upsert_klines(engine, rows)
        total += len(rows)
        cursor = rows[-1]["open_time_ms"] + step
        if end_ms is not None and cursor >= end_ms:
            return total
