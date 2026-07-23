"""
GET /api/v1/signal/{pair} — trade signal endpoint (PRD §4.1 R3, issue #7).
"""

from enum import Enum
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from structlog import get_logger

from app.api.v1.endpoints.models import get_health_engine
from app.services.kline_store import INTERVAL_MS
from app.services.signal_service import (
    CANDLE_LIMIT,
    INTERVAL,
    CandleSource,
    InsufficientDataError,
    generate_signal,
    get_candle_source,
    get_predictor,
    normalize_pair,
)

logger = get_logger()
router = APIRouter()


class Direction(str, Enum):
    """Spot-only: the bot is long or flat, never short."""

    long = "long"
    flat = "flat"


class SignalResponse(BaseModel):
    pair: str
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: str
    model_votes: Dict[str, str]
    top_features: List[Dict[str, Any]]
    model_version: str
    generated_at: str
    stale: bool


@router.get("/{pair:path}", response_model=SignalResponse)
async def get_signal(
    pair: str,
    source: CandleSource = Depends(get_candle_source),
    predictor=Depends(get_predictor),
    health_engine=Depends(get_health_engine),
) -> SignalResponse:
    symbol = normalize_pair(pair)
    if symbol is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown pair '{pair}': not in the configured trading universe",
        )

    candles = source.get_recent_candles(symbol, INTERVAL, CANDLE_LIMIT)
    try:
        signal = generate_signal(symbol, candles, predictor=predictor)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if health_engine is not None:
        # R6: persist every served signal; never fail the request over logging.
        try:
            import time

            from app.services.model_health import record_prediction

            record_prediction(
                health_engine,
                pair=symbol,
                interval=INTERVAL,
                model_version=signal.model_version,
                predicted_at_ms=int(time.time() * 1000),
                direction=signal.direction,
                confidence=signal.confidence,
                horizon_ms=INTERVAL_MS[INTERVAL],
                price=float(candles["close"].iloc[-1]),
            )
        except Exception as exc:
            logger.warning("Failed to record prediction", error=str(exc))

    return SignalResponse(**signal.__dict__)
