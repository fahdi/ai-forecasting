"""
Health check endpoints
"""

import asyncio
from typing import Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
import structlog

from app.core.database import get_db
from app.core.config import settings

logger = structlog.get_logger()
router = APIRouter()

@router.get("/")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "service": "ai-forecasting-api"
    }

@router.get("/detailed")
async def detailed_health_check(
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Detailed health check with component status
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "service": "ai-forecasting-api",
        "components": {}
    }
    
    # Check database
    try:
        # Test database connection (SQLAlchemy 2.x requires an executable
        # statement object, not a raw string)
        from sqlalchemy import text

        result = await db.execute(text("SELECT 1"))
        result.fetchone()
        health_status["components"]["database"] = {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "message": f"Database connection failed: {str(e)}"
        }
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        await redis_client.ping()
        await redis_client.close()
        health_status["components"]["redis"] = {
            "status": "healthy",
            "message": "Redis connection successful"
        }
    except Exception as e:
        health_status["components"]["redis"] = {
            "status": "unhealthy",
            "message": f"Redis connection failed: {str(e)}"
        }
        health_status["status"] = "degraded"
    
    # Check storage
    try:
        import os
        storage_path = settings.DATA_STORAGE_PATH
        if os.path.exists(storage_path) and os.access(storage_path, os.W_OK):
            health_status["components"]["storage"] = {
                "status": "healthy",
                "message": "Storage path accessible"
            }
        else:
            health_status["components"]["storage"] = {
                "status": "unhealthy",
                "message": "Storage path not accessible"
            }
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["storage"] = {
            "status": "unhealthy",
            "message": f"Storage check failed: {str(e)}"
        }
        health_status["status"] = "degraded"
    
    # Check model storage
    try:
        import os
        model_path = settings.MODEL_STORAGE_PATH
        if os.path.exists(model_path) and os.access(model_path, os.W_OK):
            health_status["components"]["model_storage"] = {
                "status": "healthy",
                "message": "Model storage path accessible"
            }
        else:
            health_status["components"]["model_storage"] = {
                "status": "unhealthy",
                "message": "Model storage path not accessible"
            }
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["model_storage"] = {
            "status": "unhealthy",
            "message": f"Model storage check failed: {str(e)}"
        }
        health_status["status"] = "degraded"
    
    # Check ML libraries
    try:
        import pandas as pd
        import numpy as np
        import xgboost as xgb
        import lightgbm as lgb
        import catboost as cb
        
        health_status["components"]["ml_libraries"] = {
            "status": "healthy",
            "message": "All ML libraries available",
            "versions": {
                "pandas": pd.__version__,
                "numpy": np.__version__,
                "xgboost": xgb.__version__,
                "lightgbm": lgb.__version__,
                "catboost": cb.__version__
            }
        }
    except Exception as e:
        health_status["components"]["ml_libraries"] = {
            "status": "unhealthy",
            "message": f"ML libraries check failed: {str(e)}"
        }
        health_status["status"] = "degraded"
    
    # Nightly backup freshness (BACKUP_STATUS_DIR is the mounted backup dir;
    # not_configured on hosts without backups, e.g. local dev)
    try:
        from app.services.backup_status import backup_status_from_env

        backups = backup_status_from_env()
        health_status["components"]["backups"] = backups
        if backups["status"] in ("stale", "missing"):
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["backups"] = {
            "status": "unhealthy",
            "message": f"Backup status check failed: {str(e)}"
        }

    # Market data freshness. Every other component answers "can we reach our
    # dependencies"; this one answers "is data still arriving", which is what
    # actually stopped during the 2026-08-03 Binance 451 outage while this
    # endpoint kept reporting healthy. Only staleness degrades: an empty table
    # is a fresh install, and an undeterminable answer is reported as unknown
    # rather than dressed up as healthy.
    try:
        import os

        from sqlalchemy import text as _text

        from app.services.market_data_status import market_data_status

        interval = os.environ.get("MARKET_DATA_INTERVAL", "4h")
        result = await db.execute(
            _text('SELECT MAX(open_time_ms) FROM klines WHERE "interval" = :interval'),
            {"interval": interval},
        )
        newest = result.scalar()
        market_data = market_data_status(newest, interval=interval)
        health_status["components"]["market_data"] = market_data
        if market_data["status"] == "stale":
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["market_data"] = {
            "status": "unknown",
            "message": f"Market data freshness could not be determined: {str(e)}"
        }

    return health_status

@router.get("/ready")
async def readiness_check() -> Dict[str, Any]:
    """
    Readiness check for Kubernetes
    """
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/live")
async def liveness_check() -> Dict[str, Any]:
    """
    Liveness check for Kubernetes
    """
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat()
    } 