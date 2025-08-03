"""
Model service for managing model training, storage, and deployment
"""

import os
import uuid
import pickle
from typing import List, Optional, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np
import structlog

from app.core.config import settings, MODEL_CONFIG
from app.models.model_manager import ModelManager
from app.models.feature_engineer import FeatureEngineer

logger = structlog.get_logger()

class ModelService:
    """Service for model management and training"""
    
    def __init__(self):
        self.model_manager = ModelManager()
        self.feature_engineer = FeatureEngineer()
        self.models_path = settings.MODEL_STORAGE_PATH
        os.makedirs(self.models_path, exist_ok=True)
    
    async def train_model(
        self,
        symbol: str,
        model_type: str,
        test_size: float = 0.2,
        retrain_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Train a model for a specific symbol
        
        Args:
            symbol: Stock symbol
            model_type: Type of model to train
            test_size: Fraction of data for testing
            retrain_existing: Whether to retrain existing model
        
        Returns:
            Training result with performance metrics
        """
        try:
            logger.info(f"Starting model training", symbol=symbol, model_type=model_type)
            
            # Check if model exists
            model_path = self._get_model_path(symbol, model_type)
            if os.path.exists(model_path) and not retrain_existing:
                logger.info(f"Model already exists for {symbol}", model_type=model_type)
                return await self.get_model_info(model_type, symbol)
            
            # Get training data
            from app.services.data_service import DataService
            data_service = DataService()
            data = await data_service.get_historical_data(symbol)
            
            if data.empty:
                raise ValueError(f"No data available for {symbol}")
            
            # Engineer features
            features_data = await self.feature_engineer.engineer_features(data)
            
            # Prepare training data
            X, y = self._prepare_training_data(features_data)
            
            # Split data
            split_idx = int(len(X) * (1 - test_size))
            X_train, X_test = X[:split_idx], X[split_idx:]
            y_train, y_test = y[:split_idx], y[split_idx:]
            
            # Train model
            model = await self.model_manager.train_model(
                model_type=model_type,
                X_train=X_train,
                y_train=y_train,
                symbol=symbol
            )
            
            # Evaluate model
            y_pred = model.predict(X_test)
            performance_metrics = self._calculate_performance_metrics(y_test, y_pred)
            
            # Save model
            version = datetime.now().strftime("%Y%m%d_%H%M%S")
            await self._save_model(model, symbol, model_type, version)
            
            # Save performance metrics
            await self._save_performance_metrics(
                symbol, model_type, version, performance_metrics
            )
            
            logger.info(
                "Model training completed",
                symbol=symbol,
                model_type=model_type,
                mape=performance_metrics.get("mape")
            )
            
            return {
                "symbol": symbol,
                "model_type": model_type,
                "version": version,
                "performance": performance_metrics,
                "training_date": datetime.now().isoformat(),
                "test_size": test_size,
                "data_points": len(data)
            }
            
        except Exception as e:
            logger.error(f"Error training model for {symbol}: {e}")
            raise
    
    def _prepare_training_data(self, data: pd.DataFrame) -> tuple:
        """Prepare data for training"""
        try:
            # Remove any rows with NaN values
            data = data.dropna()
            
            # Create target variable (next day's close price)
            data['target'] = data['close'].shift(-1)
            
            # Remove rows where we don't have target values
            data = data.dropna()
            
            # Separate features and target
            feature_columns = [col for col in data.columns if col not in ['target', 'symbol']]
            X = data[feature_columns]
            y = data['target']
            
            return X, y
            
        except Exception as e:
            logger.error(f"Error preparing training data: {e}")
            raise
    
    def _calculate_performance_metrics(
        self,
        y_true: pd.Series,
        y_pred: np.ndarray
    ) -> Dict[str, float]:
        """Calculate performance metrics"""
        try:
            # Calculate metrics
            mae = np.mean(np.abs(y_pred - y_true.values))
            mape = np.mean(np.abs((y_pred - y_true.values) / y_true.values)) * 100
            rmse = np.sqrt(np.mean((y_pred - y_true.values) ** 2))
            
            # Directional accuracy
            actual_direction = np.diff(y_true.values) > 0
            pred_direction = np.diff(y_pred) > 0
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
    
    async def _save_model(
        self,
        model: Any,
        symbol: str,
        model_type: str,
        version: str
    ):
        """Save trained model to disk"""
        try:
            model_path = self._get_model_path(symbol, model_type, version)
            
            with open(model_path, 'wb') as f:
                pickle.dump(model, f)
            
            logger.info(f"Model saved", path=model_path)
            
        except Exception as e:
            logger.error(f"Error saving model: {e}")
            raise
    
    async def _save_performance_metrics(
        self,
        symbol: str,
        model_type: str,
        version: str,
        metrics: Dict[str, float]
    ):
        """Save performance metrics"""
        try:
            metrics_path = self._get_metrics_path(symbol, model_type, version)
            
            import json
            with open(metrics_path, 'w') as f:
                json.dump(metrics, f, indent=2)
            
            logger.info(f"Performance metrics saved", path=metrics_path)
            
        except Exception as e:
            logger.error(f"Error saving performance metrics: {e}")
            raise
    
    def _get_model_path(self, symbol: str, model_type: str, version: Optional[str] = None) -> str:
        """Get model file path"""
        if version:
            return f"{self.models_path}/{symbol}_{model_type}_{version}.pkl"
        else:
            # Get latest version
            pattern = f"{symbol}_{model_type}_*.pkl"
            import glob
            files = glob.glob(f"{self.models_path}/{pattern}")
            if files:
                return max(files, key=os.path.getctime)
            else:
                return f"{self.models_path}/{symbol}_{model_type}_latest.pkl"
    
    def _get_metrics_path(self, symbol: str, model_type: str, version: str) -> str:
        """Get metrics file path"""
        return f"{self.models_path}/{symbol}_{model_type}_{version}_metrics.json"
    
    async def list_models(
        self,
        symbol: Optional[str] = None,
        model_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List available trained models"""
        try:
            models = []
            
            for file in os.listdir(self.models_path):
                if file.endswith('.pkl'):
                    # Parse filename: symbol_modeltype_version.pkl
                    parts = file.replace('.pkl', '').split('_')
                    if len(parts) >= 3:
                        file_symbol = parts[0]
                        file_model_type = parts[1]
                        version = '_'.join(parts[2:])
                        
                        # Apply filters
                        if symbol and file_symbol != symbol:
                            continue
                        if model_type and file_model_type != model_type:
                            continue
                        
                        # Get file info
                        file_path = os.path.join(self.models_path, file)
                        file_stats = os.stat(file_path)
                        
                        # Load performance metrics if available
                        metrics_path = file_path.replace('.pkl', '_metrics.json')
                        performance = None
                        if os.path.exists(metrics_path):
                            import json
                            with open(metrics_path, 'r') as f:
                                performance = json.load(f)
                        
                        models.append({
                            "model_type": file_model_type,
                            "symbol": file_symbol,
                            "version": version,
                            "last_trained": datetime.fromtimestamp(file_stats.st_mtime),
                            "file_size": file_stats.st_size,
                            "performance": performance
                        })
            
            # Sort by last trained date
            models.sort(key=lambda x: x["last_trained"], reverse=True)
            
            return models
            
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []
    
    async def get_model_info(
        self,
        model_type: str,
        symbol: str,
        version: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific model"""
        try:
            model_path = self._get_model_path(symbol, model_type, version)
            
            if not os.path.exists(model_path):
                return None
            
            file_stats = os.stat(model_path)
            
            # Load performance metrics
            metrics_path = model_path.replace('.pkl', '_metrics.json')
            performance = None
            if os.path.exists(metrics_path):
                import json
                with open(metrics_path, 'r') as f:
                    performance = json.load(f)
            
            return {
                "model_type": model_type,
                "symbol": symbol,
                "version": version or "latest",
                "last_trained": datetime.fromtimestamp(file_stats.st_mtime),
                "file_size": file_stats.st_size,
                "performance": performance,
                "path": model_path
            }
            
        except Exception as e:
            logger.error(f"Error getting model info: {e}")
            return None
    
    async def delete_model(
        self,
        model_type: str,
        symbol: str,
        version: Optional[str] = None
    ) -> bool:
        """Delete a trained model"""
        try:
            model_path = self._get_model_path(symbol, model_type, version)
            
            if os.path.exists(model_path):
                os.remove(model_path)
                
                # Also delete metrics file if it exists
                metrics_path = model_path.replace('.pkl', '_metrics.json')
                if os.path.exists(metrics_path):
                    os.remove(metrics_path)
                
                logger.info(f"Model deleted", path=model_path)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting model: {e}")
            return False
    
    async def load_model(
        self,
        model_type: str,
        symbol: str,
        version: Optional[str] = None
    ) -> Optional[Any]:
        """Load a trained model"""
        try:
            model_path = self._get_model_path(symbol, model_type, version)
            
            if not os.path.exists(model_path):
                return None
            
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
            
            logger.info(f"Model loaded", path=model_path)
            return model
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return None
    
    async def evaluate_model(
        self,
        model_type: str,
        symbol: str,
        version: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Evaluate a trained model on test data"""
        try:
            # Load model
            model = await self.load_model(model_type, symbol, version)
            if model is None:
                return None
            
            # Get test data
            from app.services.data_service import DataService
            data_service = DataService()
            data = await data_service.get_historical_data(symbol)
            
            if data.empty:
                return None
            
            # Engineer features
            features_data = await self.feature_engineer.engineer_features(data)
            
            # Prepare test data
            X, y = self._prepare_training_data(features_data)
            
            # Use last 20% for evaluation
            split_idx = int(len(X) * 0.8)
            X_test, y_test = X[split_idx:], y[split_idx:]
            
            # Make predictions
            y_pred = model.predict(X_test)
            
            # Calculate metrics
            metrics = self._calculate_performance_metrics(y_test, y_pred)
            
            return {
                "symbol": symbol,
                "model_type": model_type,
                "version": version or "latest",
                "test_size": len(X_test),
                "performance": metrics,
                "evaluation_date": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error evaluating model: {e}")
            return None 