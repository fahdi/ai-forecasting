"""
Data management endpoints
"""

import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
import pandas as pd

from app.core.database import get_db
from app.services.data_service import DataService
from app.core.config import settings

logger = structlog.get_logger()
router = APIRouter()

# Pydantic models
class DataUploadResponse(BaseModel):
    file_id: str
    filename: str
    symbol: str
    rows_processed: int
    status: str
    message: str

class DataInfo(BaseModel):
    symbol: str
    source: str
    last_updated: datetime
    data_points: int
    date_range: Dict[str, str]
    columns: List[str]

class DataRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    format: str = Field(default="json", description="Output format: json, csv, parquet")

@router.post("/upload")
async def upload_data(
    file: UploadFile = File(...),
    symbol: str = Form(...),
    source: str = Form(default="custom"),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload custom data file (CSV, JSON, Parquet)
    """
    try:
        # Validate file type
        allowed_extensions = ['.csv', '.json', '.parquet', '.xlsx']
        file_extension = os.path.splitext(file.filename)[1].lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"File type not supported. Allowed: {allowed_extensions}"
            )
        
        # Validate file size
        if file.size > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE / (1024*1024)}MB"
            )
        
        # Initialize data service
        data_service = DataService()
        
        # Process uploaded file
        result = await data_service.process_uploaded_file(
            file=file,
            symbol=symbol.upper(),
            source=source
        )
        
        logger.info(
            "Data uploaded successfully",
            filename=file.filename,
            symbol=symbol,
            rows_processed=result["rows_processed"]
        )
        
        return DataUploadResponse(
            file_id=result["file_id"],
            filename=file.filename,
            symbol=symbol.upper(),
            rows_processed=result["rows_processed"],
            status="success",
            message="Data uploaded and processed successfully"
        )
        
    except Exception as e:
        logger.error(f"Error uploading data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/symbols")
async def get_available_symbols(
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of available symbols
    """
    try:
        data_service = DataService()
        symbols = await data_service.get_available_symbols(source=source)
        
        return {
            "symbols": symbols,
            "total_count": len(symbols)
        }
        
    except Exception as e:
        logger.error(f"Error getting symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/info/{symbol}")
async def get_data_info(
    symbol: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get information about available data for a symbol
    """
    try:
        data_service = DataService()
        data_info = await data_service.get_data_info(symbol.upper())
        
        if not data_info:
            raise HTTPException(status_code=404, detail="No data found for symbol")
        
        return DataInfo(
            symbol=data_info["symbol"],
            source=data_info["source"],
            last_updated=data_info["last_updated"],
            data_points=data_info["data_points"],
            date_range=data_info["date_range"],
            columns=data_info["columns"]
        )
        
    except Exception as e:
        logger.error(f"Error getting data info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download/{symbol}")
async def download_data(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db)
):
    """
    Download data for a symbol
    """
    try:
        data_service = DataService()
        
        # Get data
        data = await data_service.get_historical_data(
            symbol=symbol.upper(),
            start_date=start_date,
            end_date=end_date
        )
        
        if data.empty:
            raise HTTPException(status_code=404, detail="No data found for symbol")
        
        # Convert to requested format
        if format.lower() == "csv":
            output_path = f"temp/{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            data.to_csv(output_path, index=True)
            return FileResponse(
                output_path,
                media_type="text/csv",
                filename=f"{symbol}_data.csv"
            )
        elif format.lower() == "json":
            output_path = f"temp/{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            data.to_json(output_path, orient="records")
            return FileResponse(
                output_path,
                media_type="application/json",
                filename=f"{symbol}_data.json"
            )
        elif format.lower() == "parquet":
            output_path = f"temp/{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
            data.to_parquet(output_path, index=True)
            return FileResponse(
                output_path,
                media_type="application/octet-stream",
                filename=f"{symbol}_data.parquet"
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported format. Use: csv, json, parquet"
            )
        
    except Exception as e:
        logger.error(f"Error downloading data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/refresh/{symbol}")
async def refresh_data(
    symbol: str,
    source: str = "yahoo",
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh data for a symbol from external source
    """
    try:
        data_service = DataService()
        
        # Refresh data
        result = await data_service.refresh_data(
            symbol=symbol.upper(),
            source=source
        )
        
        logger.info(
            "Data refreshed",
            symbol=symbol,
            source=source,
            new_points=result.get("new_points", 0)
        )
        
        return {
            "symbol": symbol.upper(),
            "source": source,
            "status": "success",
            "new_data_points": result.get("new_points", 0),
            "last_updated": result.get("last_updated")
        }
        
    except Exception as e:
        logger.error(f"Error refreshing data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{symbol}")
async def delete_data(
    symbol: str,
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete data for a symbol
    """
    try:
        data_service = DataService()
        
        deleted = await data_service.delete_data(
            symbol=symbol.upper(),
            source=source
        )
        
        if deleted:
            logger.info(f"Data deleted for symbol: {symbol}")
            return {"message": f"Data for {symbol} deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="No data found for symbol")
        
    except Exception as e:
        logger.error(f"Error deleting data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sources")
async def get_data_sources():
    """
    Get available data sources
    """
    return {
        "sources": [
            {
                "name": "yahoo",
                "description": "Yahoo Finance",
                "enabled": settings.YAHOO_FINANCE_ENABLED,
                "features": ["OHLCV", "dividends", "splits"]
            },
            {
                "name": "alpha_vantage",
                "description": "Alpha Vantage",
                "enabled": settings.ALPHA_VANTAGE_ENABLED,
                "features": ["OHLCV", "indicators", "fundamentals"]
            },
            {
                "name": "custom",
                "description": "Custom uploaded data",
                "enabled": True,
                "features": ["CSV", "JSON", "Parquet", "Excel"]
            }
        ]
    }

@router.get("/stats")
async def get_data_stats(
    db: AsyncSession = Depends(get_db)
):
    """
    Get data statistics
    """
    try:
        data_service = DataService()
        stats = await data_service.get_data_stats()
        
        return {
            "total_symbols": stats["total_symbols"],
            "total_data_points": stats["total_data_points"],
            "data_sources": stats["data_sources"],
            "last_updated": stats["last_updated"],
            "storage_size": stats["storage_size"]
        }
        
    except Exception as e:
        logger.error(f"Error getting data stats: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 