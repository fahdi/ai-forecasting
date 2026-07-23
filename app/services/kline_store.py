"""
Candle (kline) storage (issue #2, PRD §4.1 R4).

SQLAlchemy Core against PostgreSQL in production; the same code runs on
SQLite in tests. Upserts are idempotent on (pair, interval, open_time).
"""

from typing import List, Tuple

import pandas as pd
from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    MetaData,
    String,
    Table,
    func,
    select,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

klines_table = Table(
    "klines",
    metadata,
    Column("pair", String(20), primary_key=True),
    Column("interval", String(8), primary_key=True),
    Column("open_time_ms", BigInteger, primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
)

INTERVAL_MS = {
    "1h": 3_600_000,
    "4h": 4 * 3_600_000,
    "1d": 24 * 3_600_000,
}


def create_tables(engine: Engine) -> None:
    metadata.create_all(engine)


def upsert_klines(engine: Engine, rows: List[dict]) -> None:
    """Idempotent insert: existing (pair, interval, open_time) rows are kept."""
    if not rows:
        return
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(klines_table).on_conflict_do_nothing(
        index_elements=["pair", "interval", "open_time_ms"]
    )
    with engine.begin() as conn:
        conn.execute(statement, rows)


def count_klines(engine: Engine, pair: str, interval: str) -> int:
    query = (
        select(func.count())
        .select_from(klines_table)
        .where(klines_table.c.pair == pair, klines_table.c.interval == interval)
    )
    with engine.connect() as conn:
        return conn.execute(query).scalar_one()


def load_klines(engine: Engine, pair: str, interval: str) -> pd.DataFrame:
    """OHLCV frame ordered by open_time — the shape compute_features expects."""
    query = (
        select(
            klines_table.c.open_time_ms,
            klines_table.c.open,
            klines_table.c.high,
            klines_table.c.low,
            klines_table.c.close,
            klines_table.c.volume,
        )
        .where(klines_table.c.pair == pair, klines_table.c.interval == interval)
        .order_by(klines_table.c.open_time_ms)
    )
    with engine.connect() as conn:
        frame = pd.DataFrame(conn.execute(query).fetchall(),
                             columns=["open_time_ms", "open", "high", "low",
                                      "close", "volume"])
    frame["open_time"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
    return frame[["open_time", "open", "high", "low", "close", "volume"]]


def find_gaps(engine: Engine, pair: str, interval: str) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Report (gap_start, gap_end) open_time bounds where candles are missing."""
    step = INTERVAL_MS[interval]
    query = (
        select(klines_table.c.open_time_ms)
        .where(klines_table.c.pair == pair, klines_table.c.interval == interval)
        .order_by(klines_table.c.open_time_ms)
    )
    with engine.connect() as conn:
        times = [row[0] for row in conn.execute(query)]
    gaps = []
    for previous, current in zip(times, times[1:]):
        if current - previous > step:
            gaps.append(
                (
                    pd.Timestamp(previous + step, unit="ms", tz="UTC"),
                    pd.Timestamp(current, unit="ms", tz="UTC"),
                )
            )
    return gaps
