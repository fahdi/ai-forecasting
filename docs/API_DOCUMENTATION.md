# AI-Based Stock Forecasting API Documentation

## Overview

The AI-Based Stock Forecasting API is a comprehensive system that provides accurate, multi-timeframe predictions for financial instruments using advanced machine learning models. The API supports multiple forecasting models including XGBoost, LightGBM, CatBoost, LSTM, and ensemble models.

## Base URL

```
http://localhost:8000
```

## Authentication

The API uses API key authentication. Include your API key in the request headers:

```
X-API-Key: your-api-key-here
```

## Rate Limiting

- **Per Minute**: 60 requests
- **Per Hour**: 1000 requests

Rate limit headers are included in responses:
- `X-RateLimit-Limit`: Request limit
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Reset time

## Endpoints

### Health Check

#### GET /health

Basic health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "version": "1.0.0",
  "service": "ai-forecasting-api"
}
```

#### GET /health/detailed

Detailed health check with component status.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "version": "1.0.0",
  "service": "ai-forecasting-api",
  "components": {
    "database": {
      "status": "healthy",
      "message": "Database connection successful"
    },
    "redis": {
      "status": "healthy",
      "message": "Redis connection successful"
    },
    "storage": {
      "status": "healthy",
      "message": "Storage path accessible"
    },
    "ml_libraries": {
      "status": "healthy",
      "message": "All ML libraries available",
      "versions": {
        "pandas": "2.0.0",
        "numpy": "1.24.0",
        "xgboost": "1.7.0",
        "lightgbm": "4.0.0",
        "catboost": "1.2.0"
      }
    }
  }
}
```

### Forecasting

#### POST /api/v1/forecast/single

Create a single asset forecast.

**Request Body:**
```json
{
  "symbol": "AAPL",
  "forecast_horizon": 7,
  "model_type": "ensemble",
  "include_confidence": true,
  "include_features": false
}
```

**Parameters:**
- `symbol` (string, required): Stock symbol (e.g., "AAPL")
- `forecast_horizon` (integer, optional): Forecast horizon in days (1-90, default: 7)
- `model_type` (string, optional): Model type ("xgboost", "lightgbm", "catboost", "lstm", "ensemble", default: "ensemble")
- `include_confidence` (boolean, optional): Include confidence intervals (default: true)
- `include_features` (boolean, optional): Include feature importance (default: false)

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Forecast job created successfully",
  "estimated_completion": "2024-01-15T10:35:00.000Z"
}
```

#### POST /api/v1/forecast/batch

Create batch forecasts for multiple assets.

**Request Body:**
```json
{
  "symbols": ["AAPL", "GOOGL", "MSFT"],
  "forecast_horizon": 30,
  "model_type": "ensemble",
  "include_confidence": true,
  "include_features": false
}
```

**Parameters:**
- `symbols` (array, required): List of stock symbols (max 100)
- `forecast_horizon` (integer, optional): Forecast horizon in days (1-90, default: 7)
- `model_type` (string, optional): Model type (default: "ensemble")
- `include_confidence` (boolean, optional): Include confidence intervals (default: true)
- `include_features` (boolean, optional): Include feature importance (default: false)

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "pending",
  "message": "Batch forecast job created for 3 symbols",
  "estimated_completion": "2024-01-15T10:40:00.000Z"
}
```

#### GET /api/v1/forecast/status/{job_id}

Get the status of a forecast job.

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "symbol": "AAPL",
  "forecast_horizon": 7,
  "model_type": "ensemble",
  "created_at": "2024-01-15T10:30:00.000Z",
  "updated_at": "2024-01-15T10:32:00.000Z",
  "completed_at": "2024-01-15T10:32:00.000Z",
  "error_message": null
}
```

#### GET /api/v1/forecast/results/{job_id}

Get the results of a completed forecast job.

**Response:**
```json
{
  "metadata": {
    "symbol": "AAPL",
    "forecast_date": "2024-01-15T10:32:00.000Z",
    "model_used": "ensemble",
    "horizon": 7,
    "data_points_used": 252,
    "confidence": 0.85
  },
  "predictions": [
    {
      "date": "2024-01-16",
      "predicted_price": 185.42,
      "confidence_lower": 182.15,
      "confidence_upper": 188.69,
      "probability_up": 0.65
    },
    {
      "date": "2024-01-17",
      "predicted_price": 186.78,
      "confidence_lower": 183.45,
      "confidence_upper": 190.11,
      "probability_up": 0.58
    }
  ],
  "performance_metrics": {
    "mape": 2.3,
    "mae": 1.87,
    "rmse": 2.94,
    "directional_accuracy": 62.5
  },
  "feature_importance": {
    "close_lag_1": 0.15,
    "rsi": 0.12,
    "sma_20": 0.10
  }
}
```

### Model Management

#### POST /api/v1/models/train

Train a new model or retrain existing model.

**Request Body:**
```json
{
  "symbol": "AAPL",
  "model_type": "xgboost",
  "test_size": 0.2,
  "retrain_existing": false
}
```

**Parameters:**
- `symbol` (string, required): Stock symbol to train model for
- `model_type` (string, optional): Model type (default: "ensemble")
- `test_size` (float, optional): Test set size as fraction of data (0.1-0.5, default: 0.2)
- `retrain_existing` (boolean, optional): Retrain existing model (default: false)

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440002",
  "status": "pending",
  "message": "Model training started for AAPL",
  "model_type": "xgboost",
  "estimated_completion": "2024-01-15T10:35:00.000Z"
}
```

#### GET /api/v1/models/performance

Get model performance metrics.

**Query Parameters:**
- `symbol` (string, optional): Filter by symbol
- `model_type` (string, optional): Filter by model type
- `limit` (integer, optional): Maximum number of results (default: 100)

**Response:**
```json
{
  "performances": [
    {
      "model_type": "xgboost",
      "symbol": "AAPL",
      "version": "20240115_103000",
      "mape": 2.3,
      "mae": 1.87,
      "rmse": 2.94,
      "directional_accuracy": 62.5,
      "training_date": "2024-01-15T10:30:00.000Z",
      "test_start_date": "2024-01-01T00:00:00.000Z",
      "test_end_date": "2024-01-15T00:00:00.000Z"
    }
  ],
  "total_count": 1
}
```

#### GET /api/v1/models/list

List available trained models.

**Query Parameters:**
- `symbol` (string, optional): Filter by symbol
- `model_type` (string, optional): Filter by model type

**Response:**
```json
{
  "models": [
    {
      "model_type": "xgboost",
      "symbol": "AAPL",
      "version": "20240115_103000",
      "last_trained": "2024-01-15T10:30:00.000Z",
      "performance": {
        "mape": 2.3,
        "mae": 1.87,
        "rmse": 2.94
      },
      "file_size": 1024000
    }
  ],
  "total_count": 1
}
```

#### DELETE /api/v1/models/{model_type}/{symbol}

Delete a trained model.

**Path Parameters:**
- `model_type` (string): Model type
- `symbol` (string): Stock symbol

**Query Parameters:**
- `version` (string, optional): Specific model version to delete

**Response:**
```json
{
  "message": "Model xgboost/AAPL deleted successfully"
}
```

#### GET /api/v1/models/{model_type}/{symbol}/info

Get detailed information about a specific model.

**Path Parameters:**
- `model_type` (string): Model type
- `symbol` (string): Stock symbol

**Query Parameters:**
- `version` (string, optional): Specific model version

**Response:**
```json
{
  "model_type": "xgboost",
  "symbol": "AAPL",
  "version": "20240115_103000",
  "last_trained": "2024-01-15T10:30:00.000Z",
  "file_size": 1024000,
  "performance": {
    "mape": 2.3,
    "mae": 1.87,
    "rmse": 2.94
  },
  "path": "/app/models/AAPL_xgboost_20240115_103000.pkl"
}
```

### Data Management

#### POST /api/v1/data/upload

Upload custom data file.

**Request:**
- Content-Type: `multipart/form-data`
- Body:
  - `file`: Data file (CSV, JSON, Parquet, Excel)
  - `symbol`: Stock symbol
  - `source`: Data source (default: "custom")

**Response:**
```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440003",
  "filename": "data.csv",
  "symbol": "AAPL",
  "rows_processed": 1000,
  "status": "success",
  "message": "Data uploaded and processed successfully"
}
```

#### GET /api/v1/data/symbols

Get list of available symbols.

**Query Parameters:**
- `source` (string, optional): Filter by data source

**Response:**
```json
{
  "symbols": ["AAPL", "GOOGL", "MSFT"],
  "total_count": 3
}
```

#### GET /api/v1/data/info/{symbol}

Get information about available data for a symbol.

**Response:**
```json
{
  "symbol": "AAPL",
  "source": "yahoo",
  "last_updated": "2024-01-15T10:30:00.000Z",
  "data_points": 252,
  "date_range": {
    "start": "2023-01-15",
    "end": "2024-01-15"
  },
  "columns": ["open", "high", "low", "close", "volume"]
}
```

#### GET /api/v1/data/download/{symbol}

Download data for a symbol.

**Query Parameters:**
- `start_date` (string, optional): Start date (YYYY-MM-DD)
- `end_date` (string, optional): End date (YYYY-MM-DD)
- `format` (string, optional): Output format ("csv", "json", "parquet", default: "csv")

**Response:**
- File download with appropriate Content-Type

#### POST /api/v1/data/refresh/{symbol}

Refresh data for a symbol from external source.

**Query Parameters:**
- `source` (string, optional): Data source (default: "yahoo")

**Response:**
```json
{
  "symbol": "AAPL",
  "source": "yahoo",
  "status": "success",
  "new_data_points": 5,
  "last_updated": "2024-01-15T10:30:00.000Z"
}
```

#### DELETE /api/v1/data/{symbol}

Delete data for a symbol.

**Query Parameters:**
- `source` (string, optional): Specific data source to delete

**Response:**
```json
{
  "message": "Data for AAPL deleted successfully"
}
```

#### GET /api/v1/data/sources

Get available data sources.

**Response:**
```json
{
  "sources": [
    {
      "name": "yahoo",
      "description": "Yahoo Finance",
      "enabled": true,
      "features": ["OHLCV", "dividends", "splits"]
    },
    {
      "name": "alpha_vantage",
      "description": "Alpha Vantage",
      "enabled": false,
      "features": ["OHLCV", "indicators", "fundamentals"]
    },
    {
      "name": "custom",
      "description": "Custom uploaded data",
      "enabled": true,
      "features": ["CSV", "JSON", "Parquet", "Excel"]
    }
  ]
}
```

#### GET /api/v1/data/stats

Get data statistics.

**Response:**
```json
{
  "total_symbols": 50,
  "total_data_points": 12600,
  "data_sources": {
    "yahoo": 45,
    "custom": 5
  },
  "last_updated": "2024-01-15T10:30:00.000Z",
  "storage_size": 104857600
}
```

## Error Responses

All endpoints return consistent error responses:

```json
{
  "error": "Error message",
  "detail": "Detailed error description",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

Common HTTP status codes:
- `200`: Success
- `400`: Bad Request
- `401`: Unauthorized
- `404`: Not Found
- `429`: Rate Limit Exceeded
- `500`: Internal Server Error

## Model Types

### XGBoost
- **Type**: Gradient Boosting
- **Best for**: Non-linear patterns, feature importance
- **Parameters**: n_estimators, max_depth, learning_rate

### LightGBM
- **Type**: Gradient Boosting
- **Best for**: Large datasets, fast training
- **Parameters**: n_estimators, max_depth, learning_rate

### CatBoost
- **Type**: Gradient Boosting
- **Best for**: Categorical features, robust predictions
- **Parameters**: iterations, depth, learning_rate

### LSTM
- **Type**: Deep Learning
- **Best for**: Sequential patterns, time series
- **Parameters**: units, layers, dropout, epochs

### Ensemble
- **Type**: Model Combination
- **Best for**: Robust predictions, reduced overfitting
- **Parameters**: Combines multiple models with weighted averaging

## Performance Metrics

### MAPE (Mean Absolute Percentage Error)
- Measures prediction accuracy as percentage
- Target: < 5% for 7-day forecasts

### MAE (Mean Absolute Error)
- Measures absolute prediction error
- Target: < 3% of average price

### RMSE (Root Mean Square Error)
- Measures prediction error with higher penalty for large errors
- Target: < 4% of average price

### Directional Accuracy
- Measures percentage of correct price direction predictions
- Target: > 60%

## Data Sources

### Yahoo Finance
- **Enabled by default**
- **Features**: OHLCV data, dividends, splits
- **Limitations**: Rate limits, data availability

### Alpha Vantage
- **Requires API key**
- **Features**: OHLCV, technical indicators, fundamentals
- **Limitations**: API call limits

### Custom Upload
- **Supported formats**: CSV, JSON, Parquet, Excel
- **Required columns**: open, high, low, close, volume
- **Max file size**: 100MB

## Rate Limits

### Free Tier
- **Per Minute**: 60 requests
- **Per Hour**: 1000 requests
- **Daily**: 10,000 requests

### Premium Tier
- **Per Minute**: 300 requests
- **Per Hour**: 10,000 requests
- **Daily**: 100,000 requests

## Best Practices

### Forecasting
1. Use ensemble models for best accuracy
2. Include confidence intervals for risk assessment
3. Monitor model performance regularly
4. Retrain models periodically with new data

### Data Management
1. Upload high-quality, clean data
2. Use consistent date formats
3. Include all required OHLCV columns
4. Validate data before uploading

### API Usage
1. Implement proper error handling
2. Use rate limiting in your applications
3. Cache results when appropriate
4. Monitor API response times

## Support

For API support and questions:
- **Documentation**: `/docs` (Swagger UI)
- **Health Check**: `/health`
- **Metrics**: `/metrics`

## Versioning

API versioning is handled through the URL path:
- Current version: `/api/v1/`
- Future versions: `/api/v2/`, etc.

Breaking changes will be communicated through:
- API documentation updates
- Email notifications
- Deprecation warnings in responses 