"""
Chart data endpoints: candlesticks from the kline store and the model's
prediction overlay (dense in-sample-labeled model view + logged predictions
with realized outcomes).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.endpoints.models import get_health_engine
from app.services.kline_store import INTERVAL_MS, load_klines
from app.services.signal_service import UNIVERSE, get_predictor, normalize_pair

router = APIRouter()

INTERVAL = "4h"


def get_chart_engine():
    """Same database as the health engine; separate dependency so tests can
    scope overrides independently."""
    return get_health_engine()


def _resolve_symbol(pair: str) -> str:
    symbol = normalize_pair(pair)
    if symbol is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown pair '{pair}': not in the configured trading universe",
        )
    return symbol


class Candle(BaseModel):
    time: int  # unix seconds (lightweight-charts convention)
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandlesResponse(BaseModel):
    pair: str
    interval: str
    candles: List[Candle]


@router.get("/{pair}/candles", response_model=CandlesResponse)
async def get_candles(
    pair: str,
    limit: int = Query(default=300, ge=10, le=1000),
    engine=Depends(get_chart_engine),
) -> CandlesResponse:
    symbol = _resolve_symbol(pair)
    if engine is None:
        raise HTTPException(status_code=503, detail="candle store not configured")
    frame = load_klines(engine, symbol, INTERVAL)
    if frame.empty:
        raise HTTPException(status_code=503, detail=f"no candles stored for {symbol}")
    frame = frame.tail(limit)
    candles = [
        Candle(
            time=int(row.open_time.timestamp()),
            open=row.open, high=row.high, low=row.low,
            close=row.close, volume=row.volume,
        )
        for row in frame.itertuples()
    ]
    return CandlesResponse(pair=UNIVERSE[symbol], interval=INTERVAL, candles=candles)


class ModelViewPoint(BaseModel):
    time: int
    prob_long: float = Field(ge=0.0, le=1.0)


class LoggedPrediction(BaseModel):
    time: int  # snapped to candle open, unix seconds
    direction: str
    confidence: float
    realized: Optional[int]  # 1 correct-rise, 0 no-rise, None unresolved


class PredictionsResponse(BaseModel):
    pair: str
    model_version: Optional[str]
    training_window_end: Optional[str]
    model_view: List[ModelViewPoint]
    logged: List[LoggedPrediction]


def _training_window_end() -> Optional[str]:
    """In-sample boundary of the ACTIVE registry version (independent of
    whether the predictor object loaded — the chart labels honesty either way)."""
    import json
    import os
    from pathlib import Path

    registry_path = Path(os.environ.get("MODEL_REGISTRY_PATH", "models/registry"))
    index_path = registry_path / "registry.json"
    if not index_path.exists():
        return None
    index = json.loads(index_path.read_text())
    record = index.get("versions", {}).get(index.get("active") or "", {})
    return record.get("training_window", {}).get("end")


@router.get("/{pair}/predictions", response_model=PredictionsResponse)
async def get_predictions(
    pair: str,
    limit: int = Query(default=300, ge=10, le=1000),
    engine=Depends(get_chart_engine),
    predictor=Depends(get_predictor),
) -> PredictionsResponse:
    symbol = _resolve_symbol(pair)
    if engine is None:
        raise HTTPException(status_code=503, detail="candle store not configured")

    model_view: List[ModelViewPoint] = []
    model_version = None
    if predictor is not None:
        from app.models.crypto_features import compute_features

        frame = load_klines(engine, symbol, INTERVAL).tail(limit + 50)
        if not frame.empty:
            features = compute_features(frame)
            complete = features[features["complete"]]
            if not complete.empty:
                probs = predictor.prob_long_series(complete)
                model_version = predictor.version_id
                model_view = [
                    ModelViewPoint(
                        time=int(open_time.timestamp()), prob_long=float(prob)
                    )
                    for open_time, prob in zip(complete["open_time"], probs)
                ][-limit:]

    from sqlalchemy import select

    from app.services.model_health import prediction_log

    step_ms = INTERVAL_MS[INTERVAL]
    with engine.connect() as conn:
        rows = conn.execute(
            select(prediction_log)
            .where(prediction_log.c.pair == symbol)
            .order_by(prediction_log.c.predicted_at_ms)
        ).mappings().all()
    # One entry per candle: polling logs many predictions per bar; keep the
    # latest (rows are ordered by predicted_at_ms, so later rows overwrite).
    latest_per_candle: Dict[int, Any] = {}
    for row in rows:
        candle_seconds = (row["predicted_at_ms"] // step_ms) * step_ms // 1000
        latest_per_candle[candle_seconds] = row
    logged = [
        LoggedPrediction(
            time=candle_seconds,
            direction=row["direction"],
            confidence=row["confidence"],
            realized=row["realized"],
        )
        for candle_seconds, row in sorted(latest_per_candle.items())
    ]

    return PredictionsResponse(
        pair=UNIVERSE[symbol],
        model_version=model_version,
        training_window_end=_training_window_end(),
        model_view=model_view,
        logged=logged,
    )
