"""
Basic tests for the AI Forecasting API
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

# Import the app
from app.main import app

client = TestClient(app)

def test_health_check():
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data

def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "version" in data

def test_api_docs():
    """Test API documentation endpoint"""
    response = client.get("/docs")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_single_forecast_endpoint():
    """Test single forecast endpoint"""
    with patch('app.api.v1.endpoints.forecast.DataService') as mock_data_service, \
         patch('app.api.v1.endpoints.forecast.ForecastService') as mock_forecast_service:
        
        # Mock data service
        mock_data_service.return_value.get_historical_data.return_value = None
        
        # Mock forecast service
        mock_forecast_service.return_value.forecast.return_value = {
            "metadata": {"symbol": "AAPL"},
            "predictions": []
        }
        
        response = client.post(
            "/api/v1/forecast/single",
            json={
                "symbol": "AAPL",
                "forecast_horizon": 7,
                "model_type": "ensemble"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

def test_batch_forecast_endpoint():
    """Test batch forecast endpoint"""
    response = client.post(
        "/api/v1/forecast/batch",
        json={
            "symbols": ["AAPL", "GOOGL"],
            "forecast_horizon": 7,
            "model_type": "ensemble"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"

def test_forecast_status_endpoint():
    """Test forecast status endpoint"""
    # First create a forecast job
    response = client.post(
        "/api/v1/forecast/single",
        json={
            "symbol": "AAPL",
            "forecast_horizon": 7
        }
    )
    
    job_id = response.json()["job_id"]
    
    # Check status
    status_response = client.get(f"/api/v1/forecast/status/{job_id}")
    assert status_response.status_code == 200
    data = status_response.json()
    assert "status" in data
    assert "symbol" in data

def test_models_performance_endpoint():
    """Test models performance endpoint"""
    response = client.get("/api/v1/models/performance")
    assert response.status_code == 200
    data = response.json()
    assert "performances" in data
    assert "total_count" in data

def test_data_symbols_endpoint():
    """Test data symbols endpoint"""
    response = client.get("/api/v1/data/symbols")
    assert response.status_code == 200
    data = response.json()
    assert "symbols" in data
    assert "total_count" in data

def test_data_sources_endpoint():
    """Test data sources endpoint"""
    response = client.get("/api/v1/data/sources")
    assert response.status_code == 200
    data = response.json()
    assert "sources" in data
    assert len(data["sources"]) > 0

def test_metrics_endpoint():
    """Test metrics endpoint"""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

def test_cors_headers():
    """Test CORS headers are present"""
    response = client.options("/health")
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers

def test_rate_limiting():
    """Test rate limiting (basic check)"""
    # Make multiple requests quickly
    responses = []
    for _ in range(5):
        response = client.get("/health")
        responses.append(response.status_code)
    
    # All should succeed (rate limiting might not be enabled in tests)
    assert all(status == 200 for status in responses)

if __name__ == "__main__":
    pytest.main([__file__]) 