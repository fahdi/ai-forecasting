"""
Monitoring setup for the AI Forecasting API
"""

import os
import sys
from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge, Summary
from structlog import get_logger
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings

logger = get_logger()

# Prometheus metrics
FORECAST_REQUESTS = Counter(
    'forecast_requests_total',
    'Total forecast requests',
    ['model_type', 'symbol', 'status']
)

FORECAST_DURATION = Histogram(
    'forecast_duration_seconds',
    'Forecast processing duration',
    ['model_type', 'symbol']
)

MODEL_TRAINING_DURATION = Histogram(
    'model_training_duration_seconds',
    'Model training duration',
    ['model_type', 'symbol']
)

MODEL_ACCURACY = Gauge(
    'model_accuracy',
    'Model accuracy metrics',
    ['model_type', 'symbol', 'metric']
)

ACTIVE_JOBS = Gauge(
    'active_jobs',
    'Number of active forecast jobs',
    ['status']
)

DATA_POINTS_PROCESSED = Counter(
    'data_points_processed_total',
    'Total data points processed',
    ['source', 'symbol']
)

API_ERRORS = Counter(
    'api_errors_total',
    'Total API errors',
    ['endpoint', 'error_type']
)

def setup_monitoring():
    """Setup monitoring and observability"""
    
    # Setup Sentry if DSN is provided
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
        )
        logger.info("Sentry monitoring initialized")
    
    # Setup structured logging
    setup_structured_logging()
    
    logger.info("Monitoring setup completed")

def setup_structured_logging():
    """Setup structured logging with correlation IDs"""
    
    import structlog
    from structlog.stdlib import LoggerFactory
    from structlog.processors import JSONRenderer, TimeStamper
    
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            JSONRenderer()
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

def record_forecast_request(model_type: str, symbol: str, status: str):
    """Record forecast request metric"""
    FORECAST_REQUESTS.labels(
        model_type=model_type,
        symbol=symbol,
        status=status
    ).inc()

def record_forecast_duration(model_type: str, symbol: str, duration: float):
    """Record forecast duration metric"""
    FORECAST_DURATION.labels(
        model_type=model_type,
        symbol=symbol
    ).observe(duration)

def record_model_training_duration(model_type: str, symbol: str, duration: float):
    """Record model training duration metric"""
    MODEL_TRAINING_DURATION.labels(
        model_type=model_type,
        symbol=symbol
    ).observe(duration)

def record_model_accuracy(model_type: str, symbol: str, metric: str, value: float):
    """Record model accuracy metric"""
    MODEL_ACCURACY.labels(
        model_type=model_type,
        symbol=symbol,
        metric=metric
    ).set(value)

def update_active_jobs(status: str, count: int):
    """Update active jobs metric"""
    ACTIVE_JOBS.labels(status=status).set(count)

def record_data_points_processed(source: str, symbol: str, count: int):
    """Record data points processed metric"""
    DATA_POINTS_PROCESSED.labels(
        source=source,
        symbol=symbol
    ).inc(count)

def record_api_error(endpoint: str, error_type: str):
    """Record API error metric"""
    API_ERRORS.labels(
        endpoint=endpoint,
        error_type=error_type
    ).inc()

class MetricsCollector:
    """Collector for custom metrics"""
    
    def __init__(self):
        self.metrics: Dict[str, Any] = {}
    
    def record_prediction_accuracy(self, model_type: str, symbol: str, mape: float, mae: float, rmse: float):
        """Record prediction accuracy metrics"""
        record_model_accuracy(model_type, symbol, "mape", mape)
        record_model_accuracy(model_type, symbol, "mae", mae)
        record_model_accuracy(model_type, symbol, "rmse", rmse)
    
    def record_data_processing(self, source: str, symbol: str, data_points: int):
        """Record data processing metrics"""
        record_data_points_processed(source, symbol, data_points)
    
    def record_job_status(self, status: str, count: int):
        """Record job status metrics"""
        update_active_jobs(status, count)
    
    def record_error(self, endpoint: str, error_type: str):
        """Record error metrics"""
        record_api_error(endpoint, error_type)

# Global metrics collector
metrics_collector = MetricsCollector()

def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector"""
    return metrics_collector 