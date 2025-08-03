"""
Database configuration and models for the AI Forecasting API
"""

import asyncio
from typing import AsyncGenerator
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime
import structlog

from app.core.config import settings

logger = structlog.get_logger()

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Create base class for models
Base = declarative_base()

class ForecastJob(Base):
    """Model for forecast job tracking"""
    __tablename__ = "forecast_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(255), unique=True, index=True, nullable=False)
    symbol = Column(String(50), nullable=False)
    forecast_horizon = Column(Integer, nullable=False)
    model_type = Column(String(50), nullable=False)
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    result_path = Column(String(500), nullable=True)
    job_metadata = Column(JSON, nullable=True)

class ModelPerformance(Base):
    """Model for tracking model performance metrics"""
    __tablename__ = "model_performance"
    
    id = Column(Integer, primary_key=True, index=True)
    model_type = Column(String(50), nullable=False)
    symbol = Column(String(50), nullable=False)
    version = Column(String(50), nullable=False)
    mape = Column(Float, nullable=True)
    mae = Column(Float, nullable=True)
    rmse = Column(Float, nullable=True)
    directional_accuracy = Column(Float, nullable=True)
    training_date = Column(DateTime, default=datetime.utcnow)
    test_start_date = Column(DateTime, nullable=True)
    test_end_date = Column(DateTime, nullable=True)
    model_metadata = Column(JSON, nullable=True)

class DataSource(Base):
    """Model for tracking data sources"""
    __tablename__ = "data_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False)
    source = Column(String(50), nullable=False)  # yahoo, alpha_vantage, custom
    last_updated = Column(DateTime, default=datetime.utcnow)
    data_points = Column(Integer, default=0)
    status = Column(String(50), default="active")  # active, inactive, error
    data_metadata = Column(JSON, nullable=True)

class User(Base):
    """Model for user management"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    api_key = Column(String(255), unique=True, nullable=True)
    rate_limit = Column(Integer, default=1000)

class APILog(Base):
    """Model for API request logging"""
    __tablename__ = "api_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time = Column(Float, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    request_data = Column(JSON, nullable=True)
    response_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

async def init_db():
    """Initialize database tables"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()

async def close_db():
    """Close database connections"""
    await engine.dispose()
    logger.info("Database connections closed")

# Database utility functions
async def create_forecast_job(
    db: AsyncSession,
    job_id: str,
    symbol: str,
    forecast_horizon: int,
    model_type: str,
    job_metadata: dict = None
) -> ForecastJob:
    """Create a new forecast job"""
    job = ForecastJob(
        job_id=job_id,
        symbol=symbol,
        forecast_horizon=forecast_horizon,
        model_type=model_type,
        metadata=metadata
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job

async def update_forecast_job(
    db: AsyncSession,
    job_id: str,
    status: str,
    result_path: str = None,
    error_message: str = None
) -> ForecastJob:
    """Update forecast job status"""
    job = await db.get(ForecastJob, job_id)
    if job:
        job.status = status
        job.updated_at = datetime.utcnow()
        if status == "completed":
            job.completed_at = datetime.utcnow()
            job.result_path = result_path
        elif status == "failed":
            job.error_message = error_message
        await db.commit()
        await db.refresh(job)
    return job

async def get_forecast_job(db: AsyncSession, job_id: str) -> ForecastJob:
    """Get forecast job by ID"""
    return await db.get(ForecastJob, job_id)

async def save_model_performance(
    db: AsyncSession,
    model_type: str,
    symbol: str,
    version: str,
    mape: float = None,
    mae: float = None,
    rmse: float = None,
    directional_accuracy: float = None,
    model_metadata: dict = None
) -> ModelPerformance:
    """Save model performance metrics"""
    performance = ModelPerformance(
        model_type=model_type,
        symbol=symbol,
        version=version,
        mape=mape,
        mae=mae,
        rmse=rmse,
        directional_accuracy=directional_accuracy,
        metadata=metadata
    )
    db.add(performance)
    await db.commit()
    await db.refresh(performance)
    return performance

async def log_api_request(
    db: AsyncSession,
    endpoint: str,
    method: str,
    status_code: int,
    response_time: float = None,
    user_id: int = None,
    ip_address: str = None,
    user_agent: str = None,
    request_data: dict = None,
    response_data: dict = None
) -> APILog:
    """Log API request"""
    log = APILog(
        user_id=user_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        response_time=response_time,
        ip_address=ip_address,
        user_agent=user_agent,
        request_data=request_data,
        response_data=response_data
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log 