"""
Read-only runtime configuration for the dashboard Settings tab.

Only safe-to-display values: never echo secrets (keys, DSNs, database URLs).
"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("")
def get_app_settings():
    """Safe subset of runtime configuration."""
    return {
        "version": settings.VERSION,
        "git_sha": settings.GIT_SHA,
        "rate_limit_per_minute": settings.RATE_LIMIT_PER_MINUTE,
        "rate_limit_per_hour": settings.RATE_LIMIT_PER_HOUR,
        "default_forecast_horizon": settings.DEFAULT_FORECAST_HORIZON,
        "max_forecast_horizon": settings.MAX_FORECAST_HORIZON,
        "min_historical_data_days": settings.MIN_HISTORICAL_DATA_DAYS,
        "model_cache_size": settings.MODEL_CACHE_SIZE,
        "yahoo_finance_enabled": settings.YAHOO_FINANCE_ENABLED,
        "alpha_vantage_enabled": settings.ALPHA_VANTAGE_ENABLED,
    }
