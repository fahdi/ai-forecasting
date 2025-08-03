# AI-Based Stock Forecasting API System

A comprehensive AI-powered stock forecasting system that provides accurate, multi-timeframe predictions for financial instruments and macroeconomic indicators. Features a modern web dashboard for real-time monitoring and forecasting.

## 🚀 Features

### Core Forecasting Engine
- **Multi-Model Forecasting**: XGBoost, LSTM, TFT, LightGBM, CatBoost, and hybrid models
- **Multi-timeframe Predictions**: 7, 30, 90-day forecast horizons
- **Ensemble Predictions**: Combined model outputs for improved accuracy
- **Confidence Intervals**: Statistical uncertainty quantification
- **Feature Importance**: Model interpretability and insights

### Web Dashboard
- **Real-time Monitoring**: Live API status and system health
- **Interactive Charts**: Beautiful data visualization with Recharts
- **Forecast Generation**: Create predictions directly from the UI
- **Model Management**: Monitor model performance and training status
- **Data Management**: Upload and manage data sources
- **Analytics Dashboard**: System performance metrics and insights
- **Responsive Design**: Works on desktop, tablet, and mobile

### API & Integration
- **RESTful API**: FastAPI backend with comprehensive endpoints
- **Real-time Processing**: Asynchronous job processing with Celery
- **Multi-format Output**: Parquet, CSV, JSON, Excel exports
- **Google Sheets Integration**: Direct plugin for spreadsheet access
- **Authentication**: API key-based security
- **Rate Limiting**: Configurable request throttling

### Data Processing
- **Real-time Data Ingestion**: Stock prices, macroeconomic data, sentiment
- **Advanced Feature Engineering**: Technical indicators, lag features, volatility measures
- **Data Preprocessing**: Missing data handling, outlier detection, normalization
- **Multiple Data Sources**: Yahoo Finance, Alpha Vantage, custom uploads

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
├── frontend/              # Next.js web dashboard
│   ├── src/
│   │   ├── app/          # Next.js app router
│   │   ├── components/   # React components
│   │   └── lib/          # Utilities and API client
├── data/                  # Data storage and processing
├── models/                # Trained model storage
├── tests/                 # Test suite
├── docs/                  # Documentation
├── scripts/               # Utility scripts
└── config/                # Configuration files
```

## 🛠️ Technology Stack

### Backend
- **Framework**: FastAPI, Uvicorn
- **ML Libraries**: scikit-learn, XGBoost, LightGBM, CatBoost, TensorFlow, PyTorch
- **Data Processing**: pandas, numpy, polars, statsmodels
- **Database**: PostgreSQL, Redis
- **Storage**: MinIO/S3
- **Background Tasks**: Celery with Redis
- **Monitoring**: Prometheus, Sentry

### Frontend
- **Framework**: Next.js 14 with React 18
- **UI Library**: shadcn/ui components
- **Styling**: Tailwind CSS
- **Charts**: Recharts for data visualization
- **Icons**: Lucide React
- **Notifications**: Sonner toast notifications

### Infrastructure
- **Containerization**: Docker & Docker Compose
- **Development**: Hot reload for both frontend and backend
- **Production**: Optimized builds and deployment ready

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for local development)
- Python 3.9+ (for local development)

### Using Docker (Recommended)

1. **Clone and start the system**:
```bash
git clone <repository-url>
cd ai-forecasting
docker-compose up -d
```

2. **Access the applications**:
- **Web Dashboard**: http://localhost:3001
- **API Documentation**: http://localhost:8000/docs
- **API Health Check**: http://localhost:8000/health

### Local Development

1. **Backend Setup**:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. **Frontend Setup**:
```bash
cd frontend
npm install
npm run dev
```

## 🌐 Web Dashboard

### Features
- **Real-time API Status**: Live connection monitoring
- **Forecast Generation**: Create predictions with stock symbols
- **Model Performance**: View training status and metrics
- **Data Management**: Upload and manage datasets
- **System Analytics**: Performance monitoring and health checks
- **Settings**: Configure system preferences

### Navigation
- **Dashboard**: Overview with charts and system status
- **Forecasts**: Generate and view predictions
- **Models**: Monitor ML model performance
- **Data**: Manage data sources and uploads
- **Analytics**: System performance metrics
- **Settings**: Configuration and preferences

## 📚 API Documentation

### Core Endpoints

- `POST /api/v1/forecast/single` - Single asset prediction
- `POST /api/v1/forecast/batch` - Multiple asset predictions
- `GET /api/v1/forecast/status/{job_id}` - Prediction job status
- `GET /api/v1/forecast/results/{job_id}` - Retrieve prediction results
- `POST /api/v1/models/train` - Trigger model retraining
- `GET /api/v1/models/performance` - Model evaluation metrics
- `POST /api/v1/data/upload` - Upload custom datasets
- `GET /health` - System health check
- `GET /metrics` - Prometheus metrics

### Example Usage

```python
import requests

# Single forecast
response = requests.post("http://localhost:8000/api/v1/forecast/single", json={
    "symbol": "AAPL",
    "forecast_horizon": 7,
    "model_type": "ensemble",
    "include_confidence": True,
    "include_features": False
})

# Check forecast status
status = requests.get("http://localhost:8000/api/v1/forecast/status/{job_id}")

# Get results
results = requests.get("http://localhost:8000/api/v1/forecast/results/{job_id}")
```

## 🧪 Testing

```bash
# Run backend tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run frontend tests
cd frontend
npm test

# Run all tests with Docker
docker-compose exec api pytest
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

### Environment Variables
Key configuration options in `app/core/config.py`:

- `ALLOWED_HOSTS`: CORS origins for web dashboard
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection for caching
- `MINIO_ENDPOINT`: Object storage configuration
- `MODEL_STORAGE_PATH`: Path for trained models
- `RATE_LIMIT_PER_MINUTE`: API rate limiting

### Docker Configuration
- **API Service**: Port 8000
- **Frontend Service**: Port 3001
- **PostgreSQL**: Port 5432
- **Redis**: Port 6379
- **MinIO**: Ports 9000-9001

## 📊 Performance Monitoring

- **Metrics**: Prometheus metrics available at `/metrics`
- **Logging**: Structured logs with correlation IDs
- **Health Checks**: Comprehensive health monitoring
- **Error Tracking**: Sentry integration for error monitoring
- **Real-time Dashboard**: Live system status and metrics

## 🚀 Deployment

### Production Setup
1. Configure environment variables
2. Set up SSL certificates
3. Configure reverse proxy (nginx)
4. Set up monitoring and alerting
5. Configure backup strategies

### Docker Production
```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Deploy with production config
docker-compose -f docker-compose.prod.yml up -d
```

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
- Access the web dashboard for system status

---

**Built with ❤️ using modern Python development practices, React/Next.js, and AI/ML best practices.** 