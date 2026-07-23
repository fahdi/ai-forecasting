"""
GET /api/v1/signal/{pair} — trade signal endpoint (PRD §4.1 R3, issue #7).
"""

from enum import Enum
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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

    return SignalResponse(**signal.__dict__)
