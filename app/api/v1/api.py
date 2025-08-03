"""
Main API router for v1 endpoints
"""

from fastapi import APIRouter

from app.api.v1.endpoints import forecast, models, data, health

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(forecast.router, prefix="/forecast", tags=["forecast"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(data.router, prefix="/data", tags=["data"]) 