#!/usr/bin/env python3
"""
Database initialization script for AI Forecasting API
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import init_db
from app.core.config import settings
import structlog

logger = structlog.get_logger()

async def main():
    """Initialize database tables"""
    try:
        logger.info("Initializing database...")
        
        # Initialize database tables
        await init_db()
        
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 