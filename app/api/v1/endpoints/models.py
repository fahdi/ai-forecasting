"""
Model management endpoints
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db, save_model_performance
from app.services.model_service import ModelService
from app.core.monitoring import record_model_training_duration
from app.core.config import settings

logger = structlog.get_logger()
router = APIRouter()

# Pydantic models
class ModelTrainingRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol to train model for")
    model_type: str = Field(
        default="ensemble",
        description="Model type: xgboost, lightgbm, catboost, lstm, ensemble"
    )
    test_size: float = Field(
        default=0.2,
        ge=0.1,
        le=0.5,
        description="Test set size as fraction of data"
    )
    retrain_existing: bool = Field(
        default=False,
        description="Retrain existing model if it exists"
    )

class ModelPerformanceResponse(BaseModel):
    model_type: str
    symbol: str
    version: str
    mape: Optional[float] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None
    directional_accuracy: Optional[float] = None
    training_date: datetime
    test_start_date: Optional[datetime] = None
    test_end_date: Optional[datetime] = None

class ModelInfo(BaseModel):
    model_type: str
    symbol: str
    version: str
    last_trained: datetime
    performance: Optional[Dict[str, float]] = None
    file_size: Optional[int] = None

@router.post("/train")
async def train_model(
    request: ModelTrainingRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Train a new model or retrain existing model
    """
    try:
        # Generate training job ID
        job_id = str(uuid.uuid4())
        
        # Add background task
        background_tasks.add_task(
            process_model_training,
            job_id=job_id,
            symbol=request.symbol.upper(),
            model_type=request.model_type,
            test_size=request.test_size,
            retrain_existing=request.retrain_existing
        )
        
        logger.info(
            "Model training job created",
            job_id=job_id,
            symbol=request.symbol,
            model_type=request.model_type
        )
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": f"Model training started for {request.symbol}",
            "model_type": request.model_type,
            "estimated_completion": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error creating model training job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/performance")
async def get_model_performance(
    symbol: Optional[str] = None,
    model_type: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    Get model performance metrics
    """
    try:
        from sqlalchemy import select
        from app.core.database import ModelPerformance
        
        # Build query
        query = select(ModelPerformance)
        
        if symbol:
            query = query.where(ModelPerformance.symbol == symbol.upper())
        if model_type:
            query = query.where(ModelPerformance.model_type == model_type)
        
        query = query.order_by(ModelPerformance.training_date.desc()).limit(limit)
        
        # Execute query
        result = await db.execute(query)
        performances = result.scalars().all()
        
        # Convert to response format
        response_data = []
        for perf in performances:
            response_data.append(ModelPerformanceResponse(
                model_type=perf.model_type,
                symbol=perf.symbol,
                version=perf.version,
                mape=perf.mape,
                mae=perf.mae,
                rmse=perf.rmse,
                directional_accuracy=perf.directional_accuracy,
                training_date=perf.training_date,
                test_start_date=perf.test_start_date,
                test_end_date=perf.test_end_date
            ))
        
        return {
            "performances": response_data,
            "total_count": len(response_data)
        }
        
    except Exception as e:
        logger.error(f"Error getting model performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
async def list_models(
    symbol: Optional[str] = None,
    model_type: Optional[str] = None
):
    """
    List available trained models
    """
    try:
        model_service = ModelService()
        models = await model_service.list_models(symbol=symbol, model_type=model_type)
        
        response_data = []
        for model in models:
            response_data.append(ModelInfo(
                model_type=model["model_type"],
                symbol=model["symbol"],
                version=model["version"],
                last_trained=model["last_trained"],
                performance=model.get("performance"),
                file_size=model.get("file_size")
            ))
        
        return {
            "models": response_data,
            "total_count": len(response_data)
        }
        
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{model_type}/{symbol}")
async def delete_model(
    model_type: str,
    symbol: str,
    version: Optional[str] = None
):
    """
    Delete a trained model
    """
    try:
        model_service = ModelService()
        deleted = await model_service.delete_model(
            model_type=model_type,
            symbol=symbol.upper(),
            version=version
        )
        
        if deleted:
            logger.info(f"Model deleted: {model_type}/{symbol}")
            return {"message": f"Model {model_type}/{symbol} deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Model not found")
        
    except Exception as e:
        logger.error(f"Error deleting model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{model_type}/{symbol}/info")
async def get_model_info(
    model_type: str,
    symbol: str,
    version: Optional[str] = None
):
    """
    Get detailed information about a specific model
    """
    try:
        model_service = ModelService()
        model_info = await model_service.get_model_info(
            model_type=model_type,
            symbol=symbol.upper(),
            version=version
        )
        
        if not model_info:
            raise HTTPException(status_code=404, detail="Model not found")
        
        return model_info
        
    except Exception as e:
        logger.error(f"Error getting model info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_model_training(
    job_id: str,
    symbol: str,
    model_type: str,
    test_size: float,
    retrain_existing: bool
):
    """Background task to train model"""
    start_time = datetime.utcnow()
    
    try:
        logger.info(f"Starting model training: {model_type}/{symbol}")
        
        # Initialize model service
        model_service = ModelService()
        
        # Train model
        training_result = await model_service.train_model(
            symbol=symbol,
            model_type=model_type,
            test_size=test_size,
            retrain_existing=retrain_existing
        )
        
        # Save performance metrics to database
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await save_model_performance(
                db=db,
                model_type=model_type,
                symbol=symbol,
                version=training_result["version"],
                mape=training_result.get("mape"),
                mae=training_result.get("mae"),
                rmse=training_result.get("rmse"),
                directional_accuracy=training_result.get("directional_accuracy"),
                metadata=training_result.get("metadata")
            )
        
        # Record metrics
        duration = (datetime.utcnow() - start_time).total_seconds()
        record_model_training_duration(model_type, symbol, duration)
        
        logger.info(
            "Model training completed",
            job_id=job_id,
            symbol=symbol,
            model_type=model_type,
            duration=duration,
            performance=training_result.get("performance")
        )
        
    except Exception as e:
        logger.error(f"Error training model: {e}")
        raise 