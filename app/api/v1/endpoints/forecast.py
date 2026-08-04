"""
Forecast endpoints for single and batch predictions
"""

import uuid
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import (
    get_db,
    create_forecast_job,
    update_forecast_job,
    get_forecast_job,
    get_recent_forecast_jobs,
    count_active_forecast_jobs,
    find_reusable_forecast_job,
)
from app.services.forecast_service import ForecastService
from app.services.data_service import DataService
from app.core.monitoring import record_forecast_request, record_forecast_duration
from app.core.config import settings

logger = structlog.get_logger()
router = APIRouter()

# Pydantic models for request/response
class SingleForecastRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol (e.g., AAPL)")
    forecast_horizon: int = Field(
        default=settings.DEFAULT_FORECAST_HORIZON,
        ge=1,
        le=settings.MAX_FORECAST_HORIZON,
        description="Forecast horizon in days"
    )
    model_type: Optional[str] = Field(
        default="ensemble",
        description="Model type: xgboost, lightgbm, catboost, ensemble"
    )
    include_confidence: bool = Field(
        default=True,
        description="Include confidence intervals in response"
    )
    include_features: bool = Field(
        default=False,
        description="Include feature importance in response"
    )

class BatchForecastRequest(BaseModel):
    symbols: List[str] = Field(..., description="List of stock symbols")
    forecast_horizon: int = Field(
        default=settings.DEFAULT_FORECAST_HORIZON,
        ge=1,
        le=settings.MAX_FORECAST_HORIZON,
        description="Forecast horizon in days"
    )
    model_type: Optional[str] = Field(
        default="ensemble",
        description="Model type: xgboost, lightgbm, catboost, ensemble"
    )
    include_confidence: bool = Field(default=True)
    include_features: bool = Field(default=False)

class ForecastResponse(BaseModel):
    job_id: str
    status: str
    message: str
    estimated_completion: Optional[datetime] = None

class ForecastResult(BaseModel):
    metadata: Dict[str, Any]
    predictions: List[Dict[str, Any]]
    performance_metrics: Optional[Dict[str, float]] = None
    feature_importance: Optional[Dict[str, float]] = None

@router.post("/single", response_model=ForecastResponse)
async def create_single_forecast(
    request: SingleForecastRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a single asset forecast
    
    Returns a job ID that can be used to track the forecast progress
    """
    try:
        # Serve a fresh identical result instantly instead of retraining
        # (and instead of burning the concurrency cap on a repeat click).
        reusable = await find_reusable_forecast_job(
            db,
            request.symbol.upper(),
            request.forecast_horizon,
            request.model_type,
            max_age_minutes=settings.FORECAST_REUSE_TTL_MINUTES,
        )
        if reusable is not None:
            age_minutes = max(
                0, int((datetime.utcnow() - reusable.completed_at).total_seconds() // 60)
            )
            return ForecastResponse(
                job_id=reusable.job_id,
                status="completed",
                message=f"Reusing forecast computed {age_minutes} minute(s) ago",
            )
        
        active = await count_active_forecast_jobs(db)
        if active >= settings.MAX_CONCURRENT_FORECAST_JOBS:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"{active} forecast job(s) already in progress "
                    "(each one trains models); please try again in a minute"
                ),
            )
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Create forecast job in database
        await create_forecast_job(
            db=db,
            job_id=job_id,
            symbol=request.symbol.upper(),
            forecast_horizon=request.forecast_horizon,
            model_type=request.model_type,
            job_metadata={
                "include_confidence": request.include_confidence,
                "include_features": request.include_features
            }
        )
        
        # Record metric
        record_forecast_request(request.model_type, request.symbol, "started")
        
        # Add background task
        background_tasks.add_task(
            process_single_forecast,
            job_id=job_id,
            symbol=request.symbol.upper(),
            forecast_horizon=request.forecast_horizon,
            model_type=request.model_type,
            include_confidence=request.include_confidence,
            include_features=request.include_features
        )
        
        # Calculate estimated completion time
        estimated_completion = datetime.utcnow() + timedelta(minutes=5)
        
        logger.info(
            "Single forecast job created",
            job_id=job_id,
            symbol=request.symbol,
            model_type=request.model_type
        )
        
        return ForecastResponse(
            job_id=job_id,
            status="pending",
            message="Forecast job created successfully",
            estimated_completion=estimated_completion
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating single forecast: {e}")
        record_forecast_request(request.model_type, request.symbol, "failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch", response_model=ForecastResponse)
async def create_batch_forecast(
    request: BatchForecastRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Create batch forecasts for multiple assets
    
    Returns a job ID that can be used to track the forecast progress
    """
    try:
        active = await count_active_forecast_jobs(db)
        if active >= settings.MAX_CONCURRENT_FORECAST_JOBS:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"{active} forecast job(s) already in progress "
                    "(each one trains models); please try again in a minute"
                ),
            )
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Validate symbols
        if len(request.symbols) > 100:
            raise HTTPException(
                status_code=400,
                detail="Maximum 100 symbols allowed per batch request"
            )
        
        # Create forecast job in database
        await create_forecast_job(
            db=db,
            job_id=job_id,
            symbol=",".join(request.symbols),
            forecast_horizon=request.forecast_horizon,
            model_type=request.model_type,
            job_metadata={
                "symbols": request.symbols,
                "include_confidence": request.include_confidence,
                "include_features": request.include_features
            }
        )
        
        # Record metrics for each symbol
        for symbol in request.symbols:
            record_forecast_request(request.model_type, symbol, "started")
        
        # Add background task
        background_tasks.add_task(
            process_batch_forecast,
            job_id=job_id,
            symbols=request.symbols,
            forecast_horizon=request.forecast_horizon,
            model_type=request.model_type,
            include_confidence=request.include_confidence,
            include_features=request.include_features
        )
        
        # Calculate estimated completion time
        estimated_completion = datetime.utcnow() + timedelta(minutes=len(request.symbols) * 2)
        
        logger.info(
            "Batch forecast job created",
            job_id=job_id,
            symbol_count=len(request.symbols),
            model_type=request.model_type
        )
        
        return ForecastResponse(
            job_id=job_id,
            status="pending",
            message=f"Batch forecast job created for {len(request.symbols)} symbols",
            estimated_completion=estimated_completion
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating batch forecast: {e}")
        for symbol in request.symbols:
            record_forecast_request(request.model_type, symbol, "failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{job_id}")
async def get_forecast_status(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the status of a forecast job
    """
    try:
        job = await get_forecast_job(db, job_id)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return {
            "job_id": job.job_id,
            "status": job.status,
            "symbol": job.symbol,
            "forecast_horizon": job.forecast_horizon,
            "model_type": job.model_type,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting forecast status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/results/{job_id}")
async def get_forecast_results(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the results of a completed forecast job
    """
    try:
        job = await get_forecast_job(db, job_id)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job.status != "completed":
            raise HTTPException(
                status_code=400,
                detail=f"Job status is {job.status}, not completed"
            )
        
        if not job.result_json:
            # Jobs completed before result persistence existed have no payload.
            raise HTTPException(
                status_code=410,
                detail="Result payload not stored for this job; re-run the forecast"
            )
        
        return {
            "job_id": job.job_id,
            "status": job.status,
            **job.result_json,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting forecast results: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recent")
async def get_recent_forecasts(
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Recent forecast jobs with a compact prediction summary (dashboard feed)."""
    try:
        limit = max(1, min(limit, 100))
        jobs = await get_recent_forecast_jobs(db, limit=limit)
        payload = []
        for job in jobs:
            predictions = (job.result_json or {}).get("predictions") or []
            last = predictions[-1] if predictions else {}
            last_prediction = last.get("predicted_price", last.get("value"))
            metrics = (job.result_json or {}).get("performance_metrics") or {}
            metadata = (job.result_json or {}).get("metadata") or {}
            payload.append({
                "job_id": job.job_id,
                "symbol": job.symbol,
                "status": job.status,
                "model_type": job.model_type,
                "forecast_horizon": job.forecast_horizon,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "error_message": job.error_message,
                "last_prediction": last_prediction,
                "mape": metrics.get("mape"),
                "confidence": metadata.get("confidence"),
            })
        return {"jobs": payload}
    except Exception as e:
        logger.error(f"Error listing recent forecasts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_single_forecast(
    job_id: str,
    symbol: str,
    forecast_horizon: int,
    model_type: str,
    include_confidence: bool,
    include_features: bool
):
    """Background task to process single forecast"""
    start_time = datetime.utcnow()
    
    try:
        # Update job status to running
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await update_forecast_job(db, job_id, "running")
        
        # Fetch + train on a worker thread: the pipeline is CPU-bound and
        # would otherwise freeze the event loop (all requests, including the
        # dashboard's polling) for the duration of every training run.
        def _fetch_and_forecast():
            async def _inner():
                data_service = DataService()
                forecast_service = ForecastService()
                historical_data = await data_service.get_historical_data(symbol)
                if historical_data.empty:
                    raise ValueError(f"No historical data available for {symbol}")
                return await forecast_service.forecast(
                    data=historical_data,
                    symbol=symbol,
                    horizon=forecast_horizon,
                    model_type=model_type,
                    include_confidence=include_confidence,
                    include_features=include_features
                )
            return asyncio.run(_inner())
        
        forecast_result = await asyncio.to_thread(_fetch_and_forecast)
        
        # Persist the computed result on the job row
        result_path = f"results/{job_id}.json"
        async with AsyncSessionLocal() as db:
            await update_forecast_job(
                db, job_id, "completed",
                result_path=result_path,
                result_json=forecast_result,
            )
        
        # Record metrics
        duration = (datetime.utcnow() - start_time).total_seconds()
        record_forecast_duration(model_type, symbol, duration)
        record_forecast_request(model_type, symbol, "completed")
        
        logger.info(
            "Single forecast completed",
            job_id=job_id,
            symbol=symbol,
            duration=duration
        )
        
    except Exception as e:
        logger.error(f"Error processing single forecast: {e}")
        
        # Update job status to failed
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await update_forecast_job(db, job_id, "failed", error_message=str(e))
        
        record_forecast_request(model_type, symbol, "failed")

async def process_batch_forecast(
    job_id: str,
    symbols: List[str],
    forecast_horizon: int,
    model_type: str,
    include_confidence: bool,
    include_features: bool
):
    """Background task to process batch forecast"""
    start_time = datetime.utcnow()
    
    try:
        # Update job status to running
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await update_forecast_job(db, job_id, "running")
        
        results = {}
        first_error = None
        
        # Process each symbol (fetch + train off the event loop, see above)
        for symbol in symbols:
            try:
                def _fetch_and_forecast(sym=symbol):
                    async def _inner():
                        data_service = DataService()
                        forecast_service = ForecastService()
                        historical_data = await data_service.get_historical_data(sym)
                        if historical_data.empty:
                            return None
                        return await forecast_service.forecast(
                            data=historical_data,
                            symbol=sym,
                            horizon=forecast_horizon,
                            model_type=model_type,
                            include_confidence=include_confidence,
                            include_features=include_features
                        )
                    return asyncio.run(_inner())
                
                forecast_result = await asyncio.to_thread(_fetch_and_forecast)
                if forecast_result is None:
                    logger.warning(f"No historical data available for {symbol}")
                    continue
                
                results[symbol] = forecast_result
                
                # Record metrics
                record_forecast_request(model_type, symbol, "completed")
                
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                first_error = first_error or str(e)
                record_forecast_request(model_type, symbol, "failed")
        
        if not results:
            # "Completed" with zero results would be a lie; fail loudly with
            # the first underlying error so the dashboard shows why.
            raise RuntimeError(first_error or "No symbols produced a forecast")
        
        # Persist per-symbol results on the job row
        result_path = f"results/{job_id}.json"
        async with AsyncSessionLocal() as db:
            await update_forecast_job(
                db, job_id, "completed",
                result_path=result_path,
                result_json={"batch_results": results},
            )
        
        # Record metrics
        duration = (datetime.utcnow() - start_time).total_seconds()
        for symbol in symbols:
            record_forecast_duration(model_type, symbol, duration / len(symbols))
        
        logger.info(
            "Batch forecast completed",
            job_id=job_id,
            symbol_count=len(symbols),
            successful_count=len(results),
            duration=duration
        )
        
    except Exception as e:
        logger.error(f"Error processing batch forecast: {e}")
        
        # Update job status to failed
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await update_forecast_job(db, job_id, "failed", error_message=str(e))
        
        for symbol in symbols:
            record_forecast_request(model_type, symbol, "failed") 