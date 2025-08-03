#!/usr/bin/env python3
"""
Model training script for AI Forecasting API
"""

import asyncio
import sys
import os
import argparse
from typing import List

# Add the app directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.model_service import ModelService
from app.services.data_service import DataService
from app.core.config import settings
import structlog

logger = structlog.get_logger()

async def train_models(symbols: List[str], model_types: List[str] = None):
    """Train models for specified symbols"""
    try:
        model_service = ModelService()
        data_service = DataService()
        
        if model_types is None:
            model_types = ["xgboost", "lightgbm", "catboost"]
        
        for symbol in symbols:
            logger.info(f"Training models for {symbol}")
            
            # Get data for symbol
            data = await data_service.get_historical_data(symbol)
            
            if data.empty:
                logger.warning(f"No data available for {symbol}")
                continue
            
            # Train each model type
            for model_type in model_types:
                try:
                    logger.info(f"Training {model_type} model for {symbol}")
                    
                    result = await model_service.train_model(
                        symbol=symbol,
                        model_type=model_type,
                        test_size=0.2,
                        retrain_existing=True
                    )
                    
                    logger.info(f"{model_type} model trained successfully for {symbol}", 
                               performance=result.get("performance"))
                    
                except Exception as e:
                    logger.error(f"Failed to train {model_type} model for {symbol}: {e}")
                    continue
        
        logger.info("Model training completed")
        
    except Exception as e:
        logger.error(f"Model training failed: {e}")
        raise

async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Train ML models for stock forecasting")
    parser.add_argument("--symbols", nargs="+", required=True, help="Stock symbols to train models for")
    parser.add_argument("--models", nargs="+", choices=["xgboost", "lightgbm", "catboost", "lstm"], 
                       help="Model types to train")
    parser.add_argument("--all", action="store_true", help="Train all available models")
    
    args = parser.parse_args()
    
    try:
        if args.all:
            # Get all available symbols
            data_service = DataService()
            symbols = await data_service.get_available_symbols()
            if not symbols:
                logger.warning("No symbols available for training")
                return
        else:
            symbols = args.symbols
        
        await train_models(symbols, args.models)
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 