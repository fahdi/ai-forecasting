# AI-Based Stock Forecasting API System

A comprehensive AI-powered stock forecasting system that provides accurate, multi-timeframe predictions for financial instruments and macroeconomic indicators.

## 🚀 Features

- **Multi-Model Forecasting**: XGBoost, LSTM, TFT, LightGBM, CatBoost, and hybrid models
- **Real-time API**: FastAPI backend with RESTful endpoints
- **Google Sheets Integration**: Direct plugin for spreadsheet access
- **Multi-format Output**: Parquet, CSV, JSON, Excel exports
- **Advanced Analytics**: Confidence intervals, feature importance, performance metrics
- **Scalable Architecture**: Modular design for easy extension

## 📊 Model Performance Targets

- **MAPE**: < 5% for 7-day forecasts
- **MAE**: < 3% of average price
- **RMSE**: < 4% of average price
- **Directional Accuracy**: > 60% for price movement prediction

## 🏗️ Architecture

```
ai-forecasting/
├── app/                    # FastAPI application
│   ├── api/               # API endpoints
│   ├── core/              # Core business logic
│   ├── models/            # ML model implementations
│   ├── services/          # Business services
│   └── utils/             # Utility functions
├── data/                  # Data storage and processing
├── models/                # Trained model storage
├── tests/                 # Test suite
├── docs/                  # Documentation
├── scripts/               # Utility scripts
└── config/                # Configuration files
```

## 🛠️ Technology Stack

- **Backend**: FastAPI, Uvicorn
- **ML**: scikit-learn, XGBoost, LightGBM, CatBoost, TensorFlow, PyTorch
- **Data**: pandas, numpy, polars, statsmodels
- **Database**: PostgreSQL, Redis
- **Storage**: MinIO/S3
- **Monitoring**: Prometheus, Sentry

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- PostgreSQL 14+
- Redis 7+

### Installation

1. **Clone and setup environment**:
```bash
git clone <repository-url>
cd ai-forecasting
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment**:
```bash
cp .env.example .env
# Edit .env with your database and API credentials
```

3. **Initialize database**:
```bash
python scripts/init_db.py
```

4. **Start the API server**:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. **Access the API**:
- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

## 📚 API Documentation

### Core Endpoints

- `POST /forecast/single` - Single asset prediction
- `POST /forecast/batch` - Multiple asset predictions
- `GET /forecast/status/{job_id}` - Prediction job status
- `GET /forecast/results/{job_id}` - Retrieve prediction results
- `POST /models/train` - Trigger model retraining
- `GET /models/performance` - Model evaluation metrics
- `POST /data/upload` - Upload custom datasets

### Example Usage

```python
import requests

# Single forecast
response = requests.post("http://localhost:8000/forecast/single", json={
    "symbol": "AAPL",
    "forecast_horizon": 7,
    "include_confidence": True
})

# Batch forecast
response = requests.post("http://localhost:8000/forecast/batch", json={
    "symbols": ["AAPL", "GOOGL", "MSFT"],
    "forecast_horizon": 30
})
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```

## 📈 Model Training

```bash
# Train all models
python scripts/train_models.py

# Train specific model
python scripts/train_models.py --model xgboost

# Evaluate model performance
python scripts/evaluate_models.py
```

## 🔧 Configuration

Key configuration options in `config/settings.py`:

- `MODEL_PARAMS`: Model hyperparameters
- `DATA_SOURCES`: Data source configurations
- `API_SETTINGS`: API rate limits and authentication
- `STORAGE_CONFIG`: Database and object storage settings

## 📊 Performance Monitoring

- **Metrics**: Prometheus metrics available at `/metrics`
- **Logging**: Structured logs with correlation IDs
- **Health Checks**: Comprehensive health monitoring
- **Error Tracking**: Sentry integration for error monitoring

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue in the repository
- Check the documentation in `/docs`
- Review the API documentation at `/docs`

---

**Built with ❤️ using modern Python development practices and AI/ML best practices.** 