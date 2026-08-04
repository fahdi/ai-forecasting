"""
Database configuration and models for the AI Forecasting API
"""

import asyncio
from typing import AsyncGenerator
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime
import structlog

from app.core.config import settings

logger = structlog.get_logger()

def _async_url(url: str) -> str:
    """Map a driverless URL to its async driver (postgres in production,
    sqlite in the test suite)."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    return url


# Create async engine
engine = create_async_engine(
    _async_url(settings.DATABASE_URL),
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
    result_json = Column(JSON, nullable=True)
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
            # Micro-migration: result_json was added after first deploys.
            # create_all never alters existing tables, so patch Postgres here.
            if engine.dialect.name == "postgresql":
                from sqlalchemy import text
                await conn.execute(text(
                    "ALTER TABLE forecast_jobs ADD COLUMN IF NOT EXISTS result_json JSON"
                ))
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
        job_metadata=job_metadata
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
    error_message: str = None,
    result_json: dict = None
) -> ForecastJob:
    """Update forecast job status"""
    job = await get_forecast_job(db, job_id)
    if job:
        job.status = status
        job.updated_at = datetime.utcnow()
        if status == "completed":
            job.completed_at = datetime.utcnow()
            job.result_path = result_path
            job.result_json = result_json
        elif status == "failed":
            job.error_message = error_message
        await db.commit()
        await db.refresh(job)
    return job

async def get_forecast_job(db: AsyncSession, job_id: str) -> ForecastJob:
    """Get forecast job by its job_id (the primary key is the integer id,
    so a Session.get PK lookup would never match)."""
    result = await db.execute(select(ForecastJob).where(ForecastJob.job_id == job_id))
    return result.scalar_one_or_none()

async def find_reusable_forecast_job(
    db: AsyncSession,
    symbol: str,
    forecast_horizon: int,
    model_type: str,
    max_age_minutes: int,
):
    """Newest completed job with stored results for the same request shape,
    completed within the freshness window. Lets the API serve repeat
    requests instantly instead of retraining."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    result = await db.execute(
        select(ForecastJob)
        .where(
            ForecastJob.symbol == symbol,
            ForecastJob.forecast_horizon == forecast_horizon,
            ForecastJob.model_type == model_type,
            ForecastJob.status == "completed",
            ForecastJob.result_json.isnot(None),
            ForecastJob.completed_at >= cutoff,
        )
        .order_by(ForecastJob.completed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

async def count_active_forecast_jobs(db: AsyncSession) -> int:
    """Number of jobs currently pending or running."""
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).select_from(ForecastJob).where(
            ForecastJob.status.in_(("pending", "running"))
        )
    )
    return int(result.scalar() or 0)

async def fail_orphaned_forecast_jobs(db: AsyncSession) -> int:
    """Fail jobs still pending/running from a previous process. Background
    tasks die with the process, so these can never complete — leaving them
    would show perpetually-running rows and make clients poll until timeout."""
    result = await db.execute(
        select(ForecastJob).where(ForecastJob.status.in_(("pending", "running")))
    )
    jobs = list(result.scalars().all())
    for job in jobs:
        job.status = "failed"
        job.error_message = "Interrupted by service restart; re-run the forecast"
        job.updated_at = datetime.utcnow()
    if jobs:
        await db.commit()
    return len(jobs)

async def get_recent_forecast_jobs(db: AsyncSession, limit: int = 20) -> list:
    """Most recent forecast jobs, newest first (dashboard feed)."""
    result = await db.execute(
        select(ForecastJob).order_by(ForecastJob.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())

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
        model_metadata=model_metadata
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