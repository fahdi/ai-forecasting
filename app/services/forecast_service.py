"""
Forecast service for orchestrating ML models and generating predictions
"""

import os
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import structlog

from app.core.config import settings, MODEL_CONFIG, FEATURE_CONFIG
from app.models.feature_engineer import FeatureEngineer
from app.models.model_manager import ModelManager
from app.models.ensemble_model import EnsembleModel
from app.core.monitoring import record_forecast_duration

logger = structlog.get_logger()

class ForecastService:
    """Service for generating forecasts using ML models"""
    
    def __init__(self):
        self.model_manager = ModelManager()
        self.feature_engineer = FeatureEngineer()
        self.ensemble_model = EnsembleModel()
        self.results_path = "results"
        os.makedirs(self.results_path, exist_ok=True)
    
    async def forecast(
        self,
        data: pd.DataFrame,
        symbol: str,
        horizon: int,
        model_type: str = "ensemble",
        include_confidence: bool = True,
        include_features: bool = False
    ) -> Dict[str, Any]:
        """
        Generate forecast for a symbol
        
        Args:
            data: Historical OHLCV data
            symbol: Stock symbol
            horizon: Forecast horizon in days
            model_type: Type of model to use
            include_confidence: Include confidence intervals
            include_features: Include feature importance
        
        Returns:
            Forecast results
        """
        start_time = datetime.utcnow()
        
        try:
            logger.info(f"Starting forecast for {symbol}", model_type=model_type, horizon=horizon)
            
            # Validate data
            if data.empty:
                raise ValueError("Empty dataset provided")
            
            if len(data) < settings.MIN_HISTORICAL_DATA_DAYS:
                raise ValueError(f"Insufficient historical data. Need at least {settings.MIN_HISTORICAL_DATA_DAYS} days")
            
            # Engineer features
            features_data = await self.feature_engineer.engineer_features(data)
            
            # Prepare data for forecasting
            X, y = self._prepare_forecast_data(features_data, horizon)
            
            # Generate forecast
            if model_type == "ensemble":
                forecast_result = await self._ensemble_forecast(
                    X, y, horizon, include_confidence, include_features
                )
            else:
                forecast_result = await self._single_model_forecast(
                    X, y, horizon, model_type, include_confidence, include_features
                )
            
            # Calculate performance metrics
            performance_metrics = self._calculate_performance_metrics(y, forecast_result["predictions"])
            
            # Prepare response
            result = {
                "metadata": {
                    "symbol": symbol,
                    "forecast_date": datetime.utcnow().isoformat(),
                    "model_used": model_type,
                    "horizon": horizon,
                    "data_points_used": len(data),
                    "confidence": forecast_result.get("confidence", 0.0)
                },
                "predictions": forecast_result["predictions"],
                "performance_metrics": performance_metrics
            }
            
            if include_features and "feature_importance" in forecast_result:
                result["feature_importance"] = forecast_result["feature_importance"]
            
            # Record metrics
            duration = (datetime.utcnow() - start_time).total_seconds()
            record_forecast_duration(model_type, symbol, duration)
            
            logger.info(
                "Forecast completed",
                symbol=symbol,
                model_type=model_type,
                duration=duration,
                mape=performance_metrics.get("mape")
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating forecast for {symbol}: {e}")
            raise
    
    def _prepare_forecast_data(
        self,
        data: pd.DataFrame,
        horizon: int
    ) -> tuple:
        """Prepare data for forecasting"""
        try:
            # Remove any rows with NaN values
            data = data.dropna()
            
            # Create target variable (future price)
            data['target'] = data['close'].shift(-horizon)
            
            # Remove rows where we don't have target values
            data = data.dropna()
            
            # Separate features and target
            feature_columns = [col for col in data.columns if col not in ['target', 'symbol']]
            X = data[feature_columns]
            y = data['target']
            
            return X, y
            
        except Exception as e:
            logger.error(f"Error preparing forecast data: {e}")
            raise
    
    async def _ensemble_forecast(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        horizon: int,
        include_confidence: bool,
        include_features: bool
    ) -> Dict[str, Any]:
        """Generate ensemble forecast"""
        try:
            # Train ensemble model
            ensemble_result = await self.ensemble_model.train_and_predict(
                X, y, horizon, include_confidence, include_features
            )
            
            return ensemble_result
            
        except Exception as e:
            logger.error(f"Error in ensemble forecast: {e}")
            raise
    
    async def _single_model_forecast(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        horizon: int,
        model_type: str,
        include_confidence: bool,
        include_features: bool
    ) -> Dict[str, Any]:
        """Generate forecast using single model"""
        try:
            # Load or train model
            model = await self.model_manager.get_or_train_model(
                model_type, X, y, symbol="generic"
            )
            
            # Generate predictions
            predictions = model.predict(X.tail(horizon))
            
            # Calculate confidence intervals if requested
            confidence_intervals = None
            if include_confidence:
                confidence_intervals = self._calculate_confidence_intervals(predictions, model_type)
            
            # Get feature importance if requested
            feature_importance = None
            if include_features and hasattr(model, 'feature_importances_'):
                feature_importance = dict(zip(X.columns, model.feature_importances_))
            
            # Format predictions
            formatted_predictions = []
            for i, pred in enumerate(predictions):
                prediction_data = {
                    "date": (datetime.now() + timedelta(days=i+1)).strftime('%Y-%m-%d'),
                    "predicted_price": float(pred),
                    "probability_up": 0.5  # Placeholder
                }
                
                if confidence_intervals:
                    prediction_data.update({
                        "confidence_lower": float(confidence_intervals[i][0]),
                        "confidence_upper": float(confidence_intervals[i][1])
                    })
                
                formatted_predictions.append(prediction_data)
            
            return {
                "predictions": formatted_predictions,
                "confidence": 0.8,  # Placeholder
                "feature_importance": feature_importance
            }
            
        except Exception as e:
            logger.error(f"Error in single model forecast: {e}")
            raise
    
    def _calculate_confidence_intervals(
        self,
        predictions: np.ndarray,
        model_type: str
    ) -> List[tuple]:
        """Calculate confidence intervals for predictions"""
        try:
            # Simple confidence interval calculation
            # In practice, this would use more sophisticated methods
            std_dev = np.std(predictions) * 0.1  # 10% of std dev
            
            confidence_intervals = []
            for pred in predictions:
                lower = max(0, pred - 1.96 * std_dev)  # 95% confidence
                upper = pred + 1.96 * std_dev
                confidence_intervals.append((lower, upper))
            
            return confidence_intervals
            
        except Exception as e:
            logger.error(f"Error calculating confidence intervals: {e}")
            return [(pred * 0.9, pred * 1.1) for pred in predictions]  # Fallback
    
    def _calculate_performance_metrics(
        self,
        actual: pd.Series,
        predictions: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Calculate performance metrics"""
        try:
            if len(actual) < len(predictions):
                actual = actual.tail(len(predictions))
            elif len(actual) > len(predictions):
                actual = actual.head(len(predictions))
            
            pred_values = [p["predicted_price"] for p in predictions]
            
            # Calculate metrics
            mae = np.mean(np.abs(np.array(pred_values) - actual.values))
            mape = np.mean(np.abs((np.array(pred_values) - actual.values) / actual.values)) * 100
            rmse = np.sqrt(np.mean((np.array(pred_values) - actual.values) ** 2))
            
            # Directional accuracy
            actual_direction = np.diff(actual.values) > 0
            pred_direction = np.diff(pred_values) > 0
            directional_accuracy = np.mean(actual_direction == pred_direction) * 100
            
            return {
                "mae": float(mae),
                "mape": float(mape),
                "rmse": float(rmse),
                "directional_accuracy": float(directional_accuracy)
            }
            
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return {
                "mae": 0.0,
                "mape": 0.0,
                "rmse": 0.0,
                "directional_accuracy": 0.0
            }
    
    async def save_forecast_result(
        self,
        result: Dict[str, Any],
        job_id: str
    ) -> str:
        """Save forecast result to storage"""
        try:
            import json
            
            # Save as JSON
            result_path = f"{self.results_path}/{job_id}.json"
            with open(result_path, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            
            logger.info(f"Forecast result saved", job_id=job_id, path=result_path)
            return result_path
            
        except Exception as e:
            logger.error(f"Error saving forecast result: {e}")
            raise
    
    async def load_forecast_result(self, job_id: str) -> Dict[str, Any]:
        """Load forecast result from storage"""
        try:
            import json
            
            result_path = f"{self.results_path}/{job_id}.json"
            
            if not os.path.exists(result_path):
                raise FileNotFoundError(f"Forecast result not found: {job_id}")
            
            with open(result_path, 'r') as f:
                result = json.load(f)
            
            return result
            
        except Exception as e:
            logger.error(f"Error loading forecast result: {e}")
            raise
    
    async def batch_forecast(
        self,
        symbols: List[str],
        data_dict: Dict[str, pd.DataFrame],
        horizon: int,
        model_type: str = "ensemble",
        include_confidence: bool = True,
        include_features: bool = False
    ) -> Dict[str, Any]:
        """Generate batch forecasts for multiple symbols"""
        try:
            results = {}
            
            for symbol in symbols:
                try:
                    data = data_dict.get(symbol)
                    if data is not None and not data.empty:
                        result = await self.forecast(
                            data=data,
                            symbol=symbol,
                            horizon=horizon,
                            model_type=model_type,
                            include_confidence=include_confidence,
                            include_features=include_features
                        )
                        results[symbol] = result
                    else:
                        logger.warning(f"No data available for {symbol}")
                        results[symbol] = {"error": "No data available"}
                        
                except Exception as e:
                    logger.error(f"Error forecasting {symbol}: {e}")
                    results[symbol] = {"error": str(e)}
            
            return {
                "results": results,
                "total_symbols": len(symbols),
                "successful_forecasts": len([r for r in results.values() if "error" not in r])
            }
            
        except Exception as e:
            logger.error(f"Error in batch forecast: {e}")
            raise 