#!/usr/bin/env python3
"""
Quick start script for AI Forecasting API
"""

import asyncio
import sys
import os
import requests
import json
from datetime import datetime

# Add the app directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://localhost:8000"
API_KEY = "demo-api-key"  # Replace with your actual API key

def print_section(title):
    """Print a section header"""
    print(f"\n{'='*50}")
    print(f" {title}")
    print(f"{'='*50}")

def make_request(method, endpoint, data=None, headers=None):
    """Make HTTP request to API"""
    url = f"{BASE_URL}{endpoint}"
    
    if headers is None:
        headers = {
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        }
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        return response
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Could not connect to {BASE_URL}")
        print("Make sure the API server is running with: uvicorn app.main:app --reload")
        return None
    except Exception as e:
        print(f"❌ Error making request: {e}")
        return None

def test_health_check():
    """Test health check endpoint"""
    print_section("Health Check")
    
    response = make_request("GET", "/health")
    if response and response.status_code == 200:
        data = response.json()
        print(f"✅ API is healthy")
        print(f"   Status: {data['status']}")
        print(f"   Version: {data['version']}")
        print(f"   Timestamp: {data['timestamp']}")
        return True
    else:
        print("❌ Health check failed")
        return False

def test_data_sources():
    """Test data sources endpoint"""
    print_section("Data Sources")
    
    response = make_request("GET", "/api/v1/data/sources")
    if response and response.status_code == 200:
        data = response.json()
        print("✅ Available data sources:")
        for source in data["sources"]:
            status = "✅" if source["enabled"] else "❌"
            print(f"   {status} {source['name']}: {source['description']}")
        return True
    else:
        print("❌ Failed to get data sources")
        return False

def test_single_forecast():
    """Test single forecast endpoint"""
    print_section("Single Forecast")
    
    # Create forecast request
    forecast_data = {
        "symbol": "AAPL",
        "forecast_horizon": 7,
        "model_type": "ensemble",
        "include_confidence": True,
        "include_features": False
    }
    
    response = make_request("POST", "/api/v1/forecast/single", data=forecast_data)
    if response and response.status_code == 200:
        data = response.json()
        print("✅ Forecast job created successfully")
        print(f"   Job ID: {data['job_id']}")
        print(f"   Status: {data['status']}")
        print(f"   Message: {data['message']}")
        
        # Check job status
        job_id = data['job_id']
        status_response = make_request("GET", f"/api/v1/forecast/status/{job_id}")
        if status_response and status_response.status_code == 200:
            status_data = status_response.json()
            print(f"   Current Status: {status_data['status']}")
        
        return job_id
    else:
        print("❌ Failed to create forecast job")
        return None

def test_batch_forecast():
    """Test batch forecast endpoint"""
    print_section("Batch Forecast")
    
    # Create batch forecast request
    batch_data = {
        "symbols": ["AAPL", "GOOGL", "MSFT"],
        "forecast_horizon": 7,
        "model_type": "ensemble",
        "include_confidence": True,
        "include_features": False
    }
    
    response = make_request("POST", "/api/v1/forecast/batch", data=batch_data)
    if response and response.status_code == 200:
        data = response.json()
        print("✅ Batch forecast job created successfully")
        print(f"   Job ID: {data['job_id']}")
        print(f"   Status: {data['status']}")
        print(f"   Message: {data['message']}")
        return data['job_id']
    else:
        print("❌ Failed to create batch forecast job")
        return None

def test_model_training():
    """Test model training endpoint"""
    print_section("Model Training")
    
    # Create training request
    training_data = {
        "symbol": "AAPL",
        "model_type": "xgboost",
        "test_size": 0.2,
        "retrain_existing": False
    }
    
    response = make_request("POST", "/api/v1/models/train", data=training_data)
    if response and response.status_code == 200:
        data = response.json()
        print("✅ Model training job created successfully")
        print(f"   Job ID: {data['job_id']}")
        print(f"   Status: {data['status']}")
        print(f"   Message: {data['message']}")
        return data['job_id']
    else:
        print("❌ Failed to create training job")
        return None

def test_model_performance():
    """Test model performance endpoint"""
    print_section("Model Performance")
    
    response = make_request("GET", "/api/v1/models/performance")
    if response and response.status_code == 200:
        data = response.json()
        print(f"✅ Retrieved {data['total_count']} performance records")
        
        if data['performances']:
            perf = data['performances'][0]
            print(f"   Model: {perf['model_type']}")
            print(f"   Symbol: {perf['symbol']}")
            print(f"   MAPE: {perf.get('mape', 'N/A')}%")
            print(f"   MAE: {perf.get('mae', 'N/A')}")
            print(f"   RMSE: {perf.get('rmse', 'N/A')}")
        return True
    else:
        print("❌ Failed to get model performance")
        return False

def test_data_upload():
    """Test data upload endpoint"""
    print_section("Data Upload")
    
    # Create sample data
    sample_data = {
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "open": [150.0, 151.0, 152.0],
        "high": [155.0, 156.0, 157.0],
        "low": [149.0, 150.0, 151.0],
        "close": [153.0, 154.0, 155.0],
        "volume": [1000000, 1100000, 1200000]
    }
    
    # Save to CSV
    import pandas as pd
    df = pd.DataFrame(sample_data)
    csv_path = "sample_data.csv"
    df.to_csv(csv_path, index=False)
    
    # Upload file
    upload_url = f"{BASE_URL}/api/v1/data/upload"
    headers = {"X-API-Key": API_KEY}
    
    try:
        with open(csv_path, 'rb') as f:
            files = {'file': ('sample_data.csv', f, 'text/csv')}
            data = {'symbol': 'DEMO', 'source': 'custom'}
            response = requests.post(upload_url, files=files, data=data, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Data uploaded successfully")
            print(f"   File ID: {data['file_id']}")
            print(f"   Rows processed: {data['rows_processed']}")
            print(f"   Status: {data['status']}")
        else:
            print(f"❌ Upload failed: {response.status_code}")
            print(response.text)
        
        # Clean up
        os.remove(csv_path)
        
    except Exception as e:
        print(f"❌ Upload error: {e}")

def test_api_documentation():
    """Test API documentation endpoint"""
    print_section("API Documentation")
    
    response = make_request("GET", "/docs")
    if response and response.status_code == 200:
        print("✅ API documentation is available")
        print(f"   URL: {BASE_URL}/docs")
        print("   You can view the interactive API documentation at the URL above")
        return True
    else:
        print("❌ API documentation not available")
        return False

def main():
    """Main function"""
    print("🚀 AI Forecasting API Quick Start")
    print(f"   Base URL: {BASE_URL}")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test basic functionality
    if not test_health_check():
        return
    
    test_data_sources()
    test_api_documentation()
    
    # Test forecasting
    single_job_id = test_single_forecast()
    batch_job_id = test_batch_forecast()
    
    # Test model management
    training_job_id = test_model_training()
    test_model_performance()
    
    # Test data management
    test_data_upload()
    
    print_section("Summary")
    print("✅ Quick start completed!")
    print("\nNext steps:")
    print("1. View API documentation at http://localhost:8000/docs")
    print("2. Try the interactive endpoints in the Swagger UI")
    print("3. Check job status for any created jobs")
    print("4. Explore the different model types and data sources")
    print("\nFor more information, see the README.md file")

if __name__ == "__main__":
    main() 