"""
Ensemble model for combining predictions from multiple models
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import structlog

from app.models.model_manager import ModelManager

logger = structlog.get_logger()

class EnsembleModel:
    """Ensemble model combining multiple ML models"""
    
    def __init__(self):
        self.model_manager = ModelManager()
        self.models = {}
        self.weights = {}
    
    async def train_and_predict(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        horizon: int,
        include_confidence: bool = True,
        include_features: bool = False
    ) -> Dict[str, Any]:
        """
        Train ensemble model and make predictions
        
        Args:
            X: Feature matrix
            y: Target values
            horizon: Forecast horizon
            include_confidence: Include confidence intervals
            include_features: Include feature importance
        
        Returns:
            Ensemble prediction results
        """
        try:
            logger.info("Training ensemble model")
            
            # Train individual models
            models_to_train = ["xgboost", "lightgbm", "catboost"]
            
            for model_type in models_to_train:
                try:
                    model = await self.model_manager.train_model(
                        model_type=model_type,
                        X_train=X,
                        y_train=y,
                        symbol="ensemble"
                    )
                    self.models[model_type] = model
                    
                    # Calculate model weight based on performance
                    y_pred = self.model_manager.predict(model, X)
                    mse = np.mean((y_pred - y.values) ** 2)
                    self.weights[model_type] = 1.0 / (mse + 1e-8)  # Avoid division by zero
                    
                except Exception as e:
                    logger.warning(f"Failed to train {model_type}: {e}")
                    continue
            
            # Normalize weights
            total_weight = sum(self.weights.values())
            if total_weight > 0:
                self.weights = {k: v / total_weight for k, v in self.weights.items()}
            else:
                # Equal weights if all models failed
                self.weights = {k: 1.0 / len(self.models) for k in self.models.keys()}
            
            # Make ensemble predictions
            predictions = await self._make_ensemble_predictions(
                X.tail(horizon), horizon, include_confidence
            )
            
            # Calculate ensemble confidence
            confidence = self._calculate_ensemble_confidence()
            
            # Get feature importance if requested
            feature_importance = None
            if include_features:
                feature_importance = self._get_ensemble_feature_importance(X.columns)
            
            logger.info("Ensemble model training completed", 
                       models=len(self.models), 
                       weights=self.weights)
            
            return {
                "predictions": predictions,
                "confidence": confidence,
                "feature_importance": feature_importance,
                "models_used": list(self.models.keys()),
                "weights": self.weights
            }
            
        except Exception as e:
            logger.error(f"Error in ensemble training: {e}")
            raise
    
    async def _make_ensemble_predictions(
        self,
        X: pd.DataFrame,
        horizon: int,
        include_confidence: bool
    ) -> List[Dict[str, Any]]:
        """Make ensemble predictions"""
        try:
            # Get predictions from each model
            model_predictions = {}
            
            for model_type, model in self.models.items():
                try:
                    pred = self.model_manager.predict(model, X)
                    model_predictions[model_type] = pred
                except Exception as e:
                    logger.warning(f"Failed to get predictions from {model_type}: {e}")
                    continue
            
            if not model_predictions:
                raise ValueError("No models available for prediction")
            
            # Calculate weighted ensemble predictions
            ensemble_predictions = []
            
            for i in range(horizon):
                # Get predictions for this timestep
                step_predictions = []
                weights = []
                
                for model_type, preds in model_predictions.items():
                    if i < len(preds):
                        step_predictions.append(preds[i])
                        weights.append(self.weights.get(model_type, 0.0))
                
                if step_predictions:
                    # Calculate weighted average
                    weighted_pred = np.average(step_predictions, weights=weights)
                    
                    # Calculate confidence interval if requested
                    confidence_interval = None
                    if include_confidence and len(step_predictions) > 1:
                        confidence_interval = self._calculate_prediction_confidence(
                            step_predictions, weights
                        )
                    
                    prediction_data = {
                        "date": (datetime.now() + timedelta(days=i+1)).strftime('%Y-%m-%d'),
                        "predicted_price": float(weighted_pred),
                        "probability_up": 0.5  # Placeholder
                    }
                    
                    if confidence_interval:
                        prediction_data.update({
                            "confidence_lower": float(confidence_interval[0]),
                            "confidence_upper": float(confidence_interval[1])
                        })
                    
                    ensemble_predictions.append(prediction_data)
            
            return ensemble_predictions
            
        except Exception as e:
            logger.error(f"Error making ensemble predictions: {e}")
            raise
    
    def _calculate_prediction_confidence(
        self,
        predictions: List[float],
        weights: List[float]
    ) -> tuple:
        """Calculate confidence interval for ensemble prediction"""
        try:
            # Calculate weighted standard deviation
            weighted_mean = np.average(predictions, weights=weights)
            weighted_variance = np.average(
                [(p - weighted_mean) ** 2 for p in predictions], 
                weights=weights
            )
            weighted_std = np.sqrt(weighted_variance)
            
            # 95% confidence interval
            confidence_level = 1.96
            margin_of_error = confidence_level * weighted_std
            
            lower_bound = max(0, weighted_mean - margin_of_error)
            upper_bound = weighted_mean + margin_of_error
            
            return (lower_bound, upper_bound)
            
        except Exception as e:
            logger.error(f"Error calculating prediction confidence: {e}")
            # Fallback to simple range
            return (min(predictions), max(predictions))
    
    def _calculate_ensemble_confidence(self) -> float:
        """Calculate overall ensemble confidence"""
        try:
            # Simple confidence based on number of models and weight distribution
            num_models = len(self.models)
            weight_entropy = -sum(w * np.log(w + 1e-8) for w in self.weights.values())
            max_entropy = np.log(num_models) if num_models > 0 else 0
            
            # Normalize entropy to [0, 1] confidence
            if max_entropy > 0:
                confidence = 1 - (weight_entropy / max_entropy)
            else:
                confidence = 1.0
            
            return min(1.0, max(0.0, confidence))
            
        except Exception as e:
            logger.error(f"Error calculating ensemble confidence: {e}")
            return 0.8  # Default confidence
    
    def _get_ensemble_feature_importance(self, feature_names: list) -> Dict[str, float]:
        """Get ensemble feature importance"""
        try:
            ensemble_importance = {}
            
            for model_type, model in self.models.items():
                weight = self.weights.get(model_type, 0.0)
                
                # Get feature importance from individual model
                model_importance = self.model_manager.get_feature_importance(model, feature_names)
                
                # Weight the importance
                for feature, importance in model_importance.items():
                    if feature not in ensemble_importance:
                        ensemble_importance[feature] = 0.0
                    ensemble_importance[feature] += importance * weight
            
            # Sort by importance
            return dict(sorted(ensemble_importance.items(), key=lambda x: x[1], reverse=True))
            
        except Exception as e:
            logger.error(f"Error getting ensemble feature importance: {e}")
            return {}
    
    def get_model_performance(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, float]:
        """Get performance metrics for each model in ensemble"""
        try:
            performance = {}
            
            for model_type, model in self.models.items():
                try:
                    y_pred = self.model_manager.predict(model, X)
                    
                    # Calculate metrics
                    mae = np.mean(np.abs(y_pred - y.values))
                    mape = np.mean(np.abs((y_pred - y.values) / y.values)) * 100
                    rmse = np.sqrt(np.mean((y_pred - y.values) ** 2))
                    
                    performance[model_type] = {
                        "mae": float(mae),
                        "mape": float(mape),
                        "rmse": float(rmse),
                        "weight": self.weights.get(model_type, 0.0)
                    }
                    
                except Exception as e:
                    logger.warning(f"Error calculating performance for {model_type}: {e}")
                    performance[model_type] = {
                        "mae": float('inf'),
                        "mape": float('inf'),
                        "rmse": float('inf'),
                        "weight": 0.0
                    }
            
            return performance
            
        except Exception as e:
            logger.error(f"Error getting model performance: {e}")
            return {}
    
    def update_weights(self, X: pd.DataFrame, y: pd.Series):
        """Update model weights based on recent performance"""
        try:
            performance = self.get_model_performance(X, y)
            
            # Update weights based on RMSE
            total_weight = 0
            for model_type, metrics in performance.items():
                rmse = metrics["rmse"]
                if rmse < float('inf'):
                    weight = 1.0 / (rmse + 1e-8)
                    self.weights[model_type] = weight
                    total_weight += weight
            
            # Normalize weights
            if total_weight > 0:
                self.weights = {k: v / total_weight for k, v in self.weights.items()}
            
            logger.info("Model weights updated", weights=self.weights)
            
        except Exception as e:
            logger.error(f"Error updating weights: {e}")
    
    def get_ensemble_info(self) -> Dict[str, Any]:
        """Get information about the ensemble model"""
        return {
            "models": list(self.models.keys()),
            "weights": self.weights,
            "total_models": len(self.models),
            "confidence": self._calculate_ensemble_confidence()
        } 