"""
Model manager for handling different ML models
"""

import os
import pickle
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
import structlog

from app.core.config import MODEL_CONFIG

logger = structlog.get_logger()

class ModelManager:
    """Manager for different ML models"""
    
    def __init__(self):
        self.models_path = "models"
        os.makedirs(self.models_path, exist_ok=True)
        self.model_cache = {}
    
    async def train_model(
        self,
        model_type: str,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        symbol: str = "generic"
    ) -> Any:
        """
        Train a model of specified type
        
        Args:
            model_type: Type of model (xgboost, lightgbm, catboost, lstm)
            X_train: Training features
            y_train: Training targets
            symbol: Stock symbol for model identification
        
        Returns:
            Trained model
        """
        try:
            logger.info(f"Training {model_type} model", symbol=symbol)
            
            if model_type == "xgboost":
                model = await self._train_xgboost(X_train, y_train)
            elif model_type == "lightgbm":
                model = await self._train_lightgbm(X_train, y_train)
            elif model_type == "catboost":
                model = await self._train_catboost(X_train, y_train)
            elif model_type == "lstm":
                model = await self._train_lstm(X_train, y_train)
            else:
                raise ValueError(f"Unsupported model type: {model_type}")
            
            # Cache the model
            self.model_cache[f"{symbol}_{model_type}"] = model
            
            logger.info(f"{model_type} model trained successfully", symbol=symbol)
            return model
            
        except Exception as e:
            logger.error(f"Error training {model_type} model: {e}")
            raise
    
    async def get_or_train_model(
        self,
        model_type: str,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        symbol: str = "generic"
    ) -> Any:
        """Get existing model or train new one"""
        try:
            # Check cache first
            cache_key = f"{symbol}_{model_type}"
            if cache_key in self.model_cache:
                return self.model_cache[cache_key]
            
            # Check if model exists on disk
            model_path = f"{self.models_path}/{symbol}_{model_type}.pkl"
            if os.path.exists(model_path):
                with open(model_path, 'rb') as f:
                    model = pickle.load(f)
                self.model_cache[cache_key] = model
                return model
            
            # Train new model
            return await self.train_model(model_type, X_train, y_train, symbol)
            
        except Exception as e:
            logger.error(f"Error getting/training model: {e}")
            raise
    
    async def _train_xgboost(self, X_train: pd.DataFrame, y_train: pd.Series) -> Any:
        """Train XGBoost model"""
        try:
            import xgboost as xgb
            
            # Get model parameters
            params = MODEL_CONFIG.get("xgboost", {})
            
            # Create and train model
            model = xgb.XGBRegressor(**params)
            model.fit(X_train, y_train)
            
            return model
            
        except Exception as e:
            logger.error(f"Error training XGBoost model: {e}")
            raise
    
    async def _train_lightgbm(self, X_train: pd.DataFrame, y_train: pd.Series) -> Any:
        """Train LightGBM model"""
        try:
            import lightgbm as lgb
            
            # Get model parameters
            params = MODEL_CONFIG.get("lightgbm", {})
            
            # Create and train model
            model = lgb.LGBMRegressor(**params)
            model.fit(X_train, y_train)
            
            return model
            
        except Exception as e:
            logger.error(f"Error training LightGBM model: {e}")
            raise
    
    async def _train_catboost(self, X_train: pd.DataFrame, y_train: pd.Series) -> Any:
        """Train CatBoost model"""
        try:
            import catboost as cb
            
            # Get model parameters
            params = MODEL_CONFIG.get("catboost", {})
            
            # Create and train model
            model = cb.CatBoostRegressor(**params, verbose=False)
            model.fit(X_train, y_train)
            
            return model
            
        except Exception as e:
            logger.error(f"Error training CatBoost model: {e}")
            raise
    
    async def _train_lstm(self, X_train: pd.DataFrame, y_train: pd.Series) -> Any:
        """Train LSTM model"""
        try:
            import tensorflow as tf
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout
            
            # Get model parameters
            params = MODEL_CONFIG.get("lstm", {})
            
            # Reshape data for LSTM (samples, timesteps, features)
            # For now, we'll use a simple approach with 1 timestep
            X_reshaped = X_train.values.reshape((X_train.shape[0], 1, X_train.shape[1]))
            
            # Create model
            model = Sequential([
                LSTM(units=params.get("units", 50), 
                     return_sequences=True, 
                     input_shape=(1, X_train.shape[1])),
                Dropout(params.get("dropout", 0.2)),
                LSTM(units=params.get("units", 50), 
                     return_sequences=False),
                Dropout(params.get("dropout", 0.2)),
                Dense(1)
            ])
            
            # Compile model
            model.compile(optimizer='adam', loss='mse')
            
            # Train model
            model.fit(
                X_reshaped, y_train.values,
                epochs=params.get("epochs", 100),
                batch_size=params.get("batch_size", 32),
                validation_split=params.get("validation_split", 0.2),
                verbose=0
            )
            
            return model
            
        except Exception as e:
            logger.error(f"Error training LSTM model: {e}")
            raise
    
    def predict(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        """Make predictions using trained model"""
        try:
            if hasattr(model, 'predict'):
                return model.predict(X)
            else:
                raise ValueError("Model does not have predict method")
                
        except Exception as e:
            logger.error(f"Error making predictions: {e}")
            raise
    
    def get_feature_importance(self, model: Any, feature_names: list) -> Dict[str, float]:
        """Get feature importance from model"""
        try:
            if hasattr(model, 'feature_importances_'):
                importance_dict = dict(zip(feature_names, model.feature_importances_))
                return dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))
            else:
                logger.warning("Model does not have feature_importances_ attribute")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting feature importance: {e}")
            return {}
    
    def save_model(self, model: Any, symbol: str, model_type: str) -> str:
        """Save model to disk"""
        try:
            model_path = f"{self.models_path}/{symbol}_{model_type}.pkl"
            
            with open(model_path, 'wb') as f:
                pickle.dump(model, f)
            
            logger.info(f"Model saved", path=model_path)
            return model_path
            
        except Exception as e:
            logger.error(f"Error saving model: {e}")
            raise
    
    def load_model(self, symbol: str, model_type: str) -> Optional[Any]:
        """Load model from disk"""
        try:
            model_path = f"{self.models_path}/{symbol}_{model_type}.pkl"
            
            if not os.path.exists(model_path):
                return None
            
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
            
            logger.info(f"Model loaded", path=model_path)
            return model
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return None
    
    def delete_model(self, symbol: str, model_type: str) -> bool:
        """Delete model from disk"""
        try:
            model_path = f"{self.models_path}/{symbol}_{model_type}.pkl"
            
            if os.path.exists(model_path):
                os.remove(model_path)
                
                # Remove from cache if present
                cache_key = f"{symbol}_{model_type}"
                if cache_key in self.model_cache:
                    del self.model_cache[cache_key]
                
                logger.info(f"Model deleted", path=model_path)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting model: {e}")
            return False
    
    def list_models(self) -> list:
        """List all available models"""
        try:
            models = []
            
            for file in os.listdir(self.models_path):
                if file.endswith('.pkl'):
                    # Parse filename: symbol_modeltype.pkl
                    parts = file.replace('.pkl', '').split('_')
                    if len(parts) >= 2:
                        symbol = parts[0]
                        model_type = parts[1]
                        
                        models.append({
                            "symbol": symbol,
                            "model_type": model_type,
                            "filename": file
                        })
            
            return models
            
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []
    
    def clear_cache(self):
        """Clear model cache"""
        self.model_cache.clear()
        logger.info("Model cache cleared") 