"""
Model health: prediction logging, outcome resolution, rolling accuracy and
calibration (issue #8, PRD §4.1 R6).

Every signal is recorded; once its horizon elapses, the outcome resolves
against stored klines. Accuracy counts a prediction correct when a long call
saw the price rise over the horizon, or a flat call saw it not rise.
"""

from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    Integer,
    String,
    Table,
    select,
    update,
)
from sqlalchemy.engine import Engine

from app.services.kline_store import klines_table, metadata

DAY_MS = 24 * 3_600_000

CALIBRATION_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.001)]

prediction_log = Table(
    "prediction_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("pair", String(20), nullable=False),
    Column("interval", String(8), nullable=False),
    Column("model_version", String(64), nullable=False),
    Column("predicted_at_ms", BigInteger, nullable=False),
    Column("direction", String(8), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("horizon_ms", BigInteger, nullable=False),
    Column("price", Float, nullable=False),
    Column("realized", Integer, nullable=True),      # 1 price rose, 0 it did not
    Column("realized_at_ms", BigInteger, nullable=True),
)


def record_prediction(
    engine: Engine,
    pair: str,
    interval: str,
    model_version: str,
    predicted_at_ms: int,
    direction: str,
    confidence: float,
    horizon_ms: int,
    price: float,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            prediction_log.insert().values(
                pair=pair,
                interval=interval,
                model_version=model_version,
                predicted_at_ms=predicted_at_ms,
                direction=direction,
                confidence=confidence,
                horizon_ms=horizon_ms,
                price=price,
            )
        )


def _close_at_or_after(conn, pair: str, interval: str, at_ms: int) -> Optional[float]:
    row = conn.execute(
        select(klines_table.c.close)
        .where(
            klines_table.c.pair == pair,
            klines_table.c.interval == interval,
            klines_table.c.open_time_ms >= at_ms,
        )
        .order_by(klines_table.c.open_time_ms)
        .limit(1)
    ).first()
    return None if row is None else float(row[0])


def resolve_predictions(engine: Engine, now: pd.Timestamp) -> int:
    """Resolve predictions whose horizon has elapsed. Returns count resolved."""
    now_ms = int(now.timestamp() * 1000)
    resolved = 0
    with engine.begin() as conn:
        pending = conn.execute(
            select(prediction_log).where(
                prediction_log.c.realized.is_(None),
                prediction_log.c.predicted_at_ms + prediction_log.c.horizon_ms
                <= now_ms,
            )
        ).mappings().all()
        for row in pending:
            target_ms = row["predicted_at_ms"] + row["horizon_ms"]
            close_after = _close_at_or_after(conn, row["pair"], row["interval"],
                                             target_ms)
            if close_after is None:
                continue  # no candle yet; stays pending
            conn.execute(
                update(prediction_log)
                .where(prediction_log.c.id == row["id"])
                .values(realized=int(close_after > row["price"]),
                        realized_at_ms=now_ms)
            )
            resolved += 1
    return resolved


def _accuracy(rows: List[dict]) -> Optional[float]:
    resolved = [r for r in rows if r["realized"] is not None]
    if not resolved:
        return None
    correct = sum(
        1
        for r in resolved
        if (r["direction"] == "long") == bool(r["realized"])
    )
    return correct / len(resolved)


def _calibration(rows: List[dict]) -> List[Dict]:
    resolved = [r for r in rows if r["realized"] is not None]
    buckets = []
    for low, high in CALIBRATION_BUCKETS:
        members = []
        for r in resolved:
            prob_long = r["confidence"] if r["direction"] == "long" else 1 - r["confidence"]
            if low <= prob_long < high:
                members.append((prob_long, r["realized"]))
        if not members:
            continue
        buckets.append(
            {
                "bucket_low": low,
                "bucket_high": min(high, 1.0),
                "predicted_mean": sum(m[0] for m in members) / len(members),
                "realized_hit_rate": sum(m[1] for m in members) / len(members),
                "count": len(members),
            }
        )
    return buckets


def health_summary(engine: Engine, now: pd.Timestamp) -> Dict:
    """The /api/v1/models/health contract consumed by the dashboard."""
    from app.services.signal_service import UNIVERSE

    now_ms = int(now.timestamp() * 1000)
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(select(prediction_log)).mappings()]

    pairs = []
    for symbol in sorted({r["pair"] for r in rows}):
        symbol_rows = [r for r in rows if r["pair"] == symbol]
        window_7d = [r for r in symbol_rows
                     if r["predicted_at_ms"] >= now_ms - 7 * DAY_MS]
        window_30d = [r for r in symbol_rows
                      if r["predicted_at_ms"] >= now_ms - 30 * DAY_MS]
        pairs.append(
            {
                "pair": UNIVERSE.get(symbol, symbol),
                "directional_accuracy_7d": _accuracy(window_7d),
                "directional_accuracy_30d": _accuracy(window_30d),
                "n_predictions": len(symbol_rows),
                "calibration": _calibration(window_30d),
            }
        )
    return {"pairs": pairs}
