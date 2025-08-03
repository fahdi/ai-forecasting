"""
Configuration settings for the AI Forecasting API
"""

import os
from typing import List, Optional, Dict, Any
from pydantic import Field, validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings"""
    
    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "AI-Based Stock Forecasting API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Comprehensive AI-powered stock forecasting system"
    
    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True
    
    # CORS Settings
    ALLOWED_HOSTS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins"
    )
    
    # Database Settings
    DATABASE_URL: str = Field(
        default="postgresql://user:password@localhost:5432/ai_forecasting",
        description="PostgreSQL database URL"
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for caching"
    )
    
    # Storage Settings
    MINIO_ENDPOINT: str = Field(default="localhost:9000", description="MinIO endpoint")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin", description="MinIO access key")
    MINIO_SECRET_KEY: str = Field(default="minioadmin", description="MinIO secret key")
    MINIO_BUCKET: str = Field(default="ai-forecasting", description="MinIO bucket name")
    MINIO_SECURE: bool = Field(default=False, description="Use HTTPS for MinIO")
    
    # Authentication Settings
    SECRET_KEY: str = Field(
        default="your-secret-key-change-in-production",
        description="JWT secret key"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    
    # Model Settings
    MODEL_STORAGE_PATH: str = Field(
        default="./models",
        description="Path to store trained models"
    )
    MODEL_CACHE_SIZE: int = Field(
        default=10,
        description="Number of models to keep in memory"
    )
    
    # Data Settings
    DATA_STORAGE_PATH: str = Field(
        default="./data",
        description="Path to store data files"
    )
    MAX_FILE_SIZE: int = Field(
        default=100 * 1024 * 1024,  # 100MB
        description="Maximum file upload size"
    )
    
    # Forecasting Settings
    DEFAULT_FORECAST_HORIZON: int = Field(
        default=7,
        description="Default forecast horizon in days"
    )
    MAX_FORECAST_HORIZON: int = Field(
        default=90,
        description="Maximum forecast horizon in days"
    )
    MIN_HISTORICAL_DATA_DAYS: int = Field(
        default=252,
        description="Minimum historical data required for forecasting"
    )
    
    # Model Parameters
    XGBOOST_PARAMS: Dict[str, Any] = Field(
        default={
            "n_estimators": 1000,
            "max_depth": 6,
            "learning_rate": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42
        },
        description="XGBoost model parameters"
    )
    
    LIGHTGBM_PARAMS: Dict[str, Any] = Field(
        default={
            "n_estimators": 1000,
            "max_depth": 6,
            "learning_rate": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42
        },
        description="LightGBM model parameters"
    )
    
    CATBOOST_PARAMS: Dict[str, Any] = Field(
        default={
            "iterations": 1000,
            "depth": 6,
            "learning_rate": 0.1,
            "random_state": 42
        },
        description="CatBoost model parameters"
    )
    
    LSTM_PARAMS: Dict[str, Any] = Field(
        default={
            "units": 50,
            "layers": 2,
            "dropout": 0.2,
            "batch_size": 32,
            "epochs": 100,
            "validation_split": 0.2
        },
        description="LSTM model parameters"
    )
    
    # Feature Engineering Settings
    TECHNICAL_INDICATORS: List[str] = Field(
        default=[
            "sma", "ema", "rsi", "macd", "bollinger_bands",
            "stochastic", "williams_r", "cci", "adx"
        ],
        description="Technical indicators to calculate"
    )
    
    LAG_FEATURES: List[int] = Field(
        default=[1, 2, 3, 5, 10, 20, 50, 100, 200],
        description="Lag periods for feature engineering"
    )
    
    ROLLING_WINDOWS: List[int] = Field(
        default=[5, 10, 20, 50, 100, 200],
        description="Rolling window sizes for statistics"
    )
    
    # Data Sources
    YAHOO_FINANCE_ENABLED: bool = Field(
        default=True,
        description="Enable Yahoo Finance data source"
    )
    ALPHA_VANTAGE_ENABLED: bool = Field(
        default=False,
        description="Enable Alpha Vantage data source"
    )
    ALPHA_VANTAGE_API_KEY: Optional[str] = Field(
        default=None,
        description="Alpha Vantage API key"
    )
    
    # Logging Settings
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: str = Field(
        default="json",
        description="Log format (json or text)"
    )
    
    # Monitoring Settings
    SENTRY_DSN: Optional[str] = Field(
        default=None,
        description="Sentry DSN for error tracking"
    )
    PROMETHEUS_ENABLED: bool = Field(
        default=True,
        description="Enable Prometheus metrics"
    )
    
    # Background Tasks
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker URL"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend URL"
    )
    
    # Google Sheets Integration
    GOOGLE_SHEETS_CREDENTIALS_FILE: Optional[str] = Field(
        default=None,
        description="Path to Google Sheets credentials file"
    )
    GOOGLE_SHEETS_SCOPES: List[str] = Field(
        default=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ],
        description="Google Sheets API scopes"
    )
    
    @validator("ALLOWED_HOSTS", pre=True)
    def assemble_cors_origins(cls, v):
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Create settings instance
settings = Settings()

# Model configuration
MODEL_CONFIG = {
    "xgboost": settings.XGBOOST_PARAMS,
    "lightgbm": settings.LIGHTGBM_PARAMS,
    "catboost": settings.CATBOOST_PARAMS,
    "lstm": settings.LSTM_PARAMS,
}

# Feature engineering configuration
FEATURE_CONFIG = {
    "technical_indicators": settings.TECHNICAL_INDICATORS,
    "lag_features": settings.LAG_FEATURES,
    "rolling_windows": settings.ROLLING_WINDOWS,
} 