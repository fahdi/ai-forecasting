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

from app.core.database import get_db, create_forecast_job, update_forecast_job, get_forecast_job
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
        description="Model type: xgboost, lightgbm, catboost, lstm, ensemble"
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
        description="Model type: xgboost, lightgbm, catboost, lstm, ensemble"
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
            metadata={
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
        
        # TODO: Load results from storage
        # For now, return a placeholder
        return {
            "job_id": job.job_id,
            "status": job.status,
            "result_path": job.result_path,
            "metadata": job.metadata
        }
        
    except Exception as e:
        logger.error(f"Error getting forecast results: {e}")
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
        
        # Initialize services
        data_service = DataService()
        forecast_service = ForecastService()
        
        # Get historical data
        historical_data = await data_service.get_historical_data(symbol)
        
        if historical_data.empty:
            raise ValueError(f"No historical data available for {symbol}")
        
        # Perform forecast
        forecast_result = await forecast_service.forecast(
            data=historical_data,
            symbol=symbol,
            horizon=forecast_horizon,
            model_type=model_type,
            include_confidence=include_confidence,
            include_features=include_features
        )
        
        # Save results
        result_path = f"results/{job_id}.json"
        # TODO: Save forecast_result to storage
        
        # Update job status to completed
        async with AsyncSessionLocal() as db:
            await update_forecast_job(db, job_id, "completed", result_path=result_path)
        
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
        
        # Initialize services
        data_service = DataService()
        forecast_service = ForecastService()
        
        results = {}
        
        # Process each symbol
        for symbol in symbols:
            try:
                # Get historical data
                historical_data = await data_service.get_historical_data(symbol)
                
                if historical_data.empty:
                    logger.warning(f"No historical data available for {symbol}")
                    continue
                
                # Perform forecast
                forecast_result = await forecast_service.forecast(
                    data=historical_data,
                    symbol=symbol,
                    horizon=forecast_horizon,
                    model_type=model_type,
                    include_confidence=include_confidence,
                    include_features=include_features
                )
                
                results[symbol] = forecast_result
                
                # Record metrics
                record_forecast_request(model_type, symbol, "completed")
                
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                record_forecast_request(model_type, symbol, "failed")
        
        # Save batch results
        result_path = f"results/{job_id}.json"
        # TODO: Save results to storage
        
        # Update job status to completed
        async with AsyncSessionLocal() as db:
            await update_forecast_job(db, job_id, "completed", result_path=result_path)
        
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