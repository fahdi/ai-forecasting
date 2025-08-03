"""
Middleware for request logging, rate limiting, and authentication
"""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from structlog import get_logger
import redis.asyncio as redis
from app.core.config import settings

logger = get_logger()

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for structured request logging"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Add request ID to request state
        request.state.request_id = request_id
        
        # Log request start
        start_time = time.time()
        
        logger.info(
            "Request started",
            request_id=request_id,
            method=request.method,
            url=str(request.url),
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate response time
            response_time = time.time() - start_time
            
            # Log successful response
            logger.info(
                "Request completed",
                request_id=request_id,
                status_code=response.status_code,
                response_time=response_time,
            )
            
            # Add response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = str(response_time)
            
            return response
            
        except Exception as e:
            # Log error
            response_time = time.time() - start_time
            logger.error(
                "Request failed",
                request_id=request_id,
                error=str(e),
                response_time=response_time,
            )
            raise

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting"""
    
    def __init__(self, app, redis_client: redis.Redis):
        super().__init__(app)
        self.redis = redis_client
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Check rate limit
        rate_limit_key = f"rate_limit:{client_ip}"
        
        try:
            # Get current request count
            current_count = await self.redis.get(rate_limit_key)
            current_count = int(current_count) if current_count else 0
            
            # Check if limit exceeded
            if current_count >= settings.RATE_LIMIT_PER_MINUTE:
                logger.warning(
                    "Rate limit exceeded",
                    client_ip=client_ip,
                    current_count=current_count,
                )
                return Response(
                    content="Rate limit exceeded",
                    status_code=429,
                    headers={"Retry-After": "60"}
                )
            
            # Increment counter
            await self.redis.incr(rate_limit_key)
            await self.redis.expire(rate_limit_key, 60)  # 1 minute window
            
            # Process request
            response = await call_next(request)
            
            # Add rate limit headers
            response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_PER_MINUTE)
            response.headers["X-RateLimit-Remaining"] = str(settings.RATE_LIMIT_PER_MINUTE - current_count - 1)
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Continue without rate limiting if Redis is unavailable
            return await call_next(request)

class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware for API key authentication"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip authentication for health check and docs
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json", "/metrics"]:
            return await call_next(request)
        
        # Get API key from header
        api_key = request.headers.get("X-API-Key")
        
        if not api_key:
            logger.warning("Missing API key", path=request.url.path)
            return Response(
                content="API key required",
                status_code=401,
                headers={"WWW-Authenticate": "ApiKey"}
            )
        
        # TODO: Validate API key against database
        # For now, accept any non-empty API key
        if not api_key.strip():
            logger.warning("Invalid API key", path=request.url.path)
            return Response(
                content="Invalid API key",
                status_code=401,
                headers={"WWW-Authenticate": "ApiKey"}
            )
        
        # Add user info to request state
        request.state.user_id = None  # TODO: Get from database
        request.state.api_key = api_key
        
        return await call_next(request)

class CORSMiddleware(BaseHTTPMiddleware):
    """Custom CORS middleware with additional headers"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Add CORS headers
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        
        return response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        return response 