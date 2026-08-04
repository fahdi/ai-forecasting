"""
Data service for handling data ingestion, processing, and management
"""

import os
import time
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf
import structlog
from fastapi import UploadFile
import aiofiles

from app.core.config import settings
from app.core.monitoring import record_data_points_processed

logger = structlog.get_logger()

# Friendly names people actually type -> Yahoo Finance tickers. Anything not
# in the map passes through unchanged (uppercased), so real tickers still work.
SYMBOL_ALIASES = {
    "XAU": "GC=F",      # gold spot -> COMEX gold futures
    "GOLD": "GC=F",
    "XAG": "SI=F",      # silver
    "SILVER": "SI=F",
    "OIL": "CL=F",      # WTI crude
    "WTI": "CL=F",
    "BRENT": "BZ=F",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "BNB": "BNB-USD",
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJI": "^DJI",
}

def normalize_symbol(symbol: str) -> str:
    """Map a user-facing symbol to its data-source ticker.

    Also accepts common USD-pair spellings of aliased assets ("XAU/USD",
    "XAUUSD") by resolving the base asset through the alias map. Unknown
    symbols pass through unchanged so real tickers keep working.
    """
    cleaned = symbol.strip().upper()
    if cleaned in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[cleaned]
    for suffix in ("/USD", "USD"):
        if cleaned.endswith(suffix):
            base = cleaned[: -len(suffix)]
            if base in SYMBOL_ALIASES:
                return SYMBOL_ALIASES[base]
    return cleaned

class DataService:
    """Service for data management and processing"""
    
    def __init__(self):
        self.data_path = settings.DATA_STORAGE_PATH
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure required directories exist"""
        os.makedirs(self.data_path, exist_ok=True)
        os.makedirs(f"{self.data_path}/raw", exist_ok=True)
        os.makedirs(f"{self.data_path}/processed", exist_ok=True)
        os.makedirs(f"{self.data_path}/temp", exist_ok=True)
    
    async def get_historical_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: str = "yahoo"
    ) -> pd.DataFrame:
        """
        Get historical data for a symbol
        
        Args:
            symbol: Stock symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            source: Data source (yahoo, alpha_vantage, custom)
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            symbol = normalize_symbol(symbol)
            if source not in ("yahoo", "alpha_vantage"):
                raise ValueError(f"Unsupported data source: {source}")

            def _windowed(frame: pd.DataFrame) -> pd.DataFrame:
                if start_date:
                    frame = frame[frame.index >= start_date]
                if end_date:
                    frame = frame[frame.index <= end_date]
                return frame

            cached_data = await self._load_cached_data(symbol, source)
            age = self._cache_age_seconds(symbol, source)
            ttl_seconds = settings.DATA_CACHE_TTL_HOURS * 3600
            # age is None when there is no cache file on disk; if a loader
            # nevertheless produced data (tests stub it), treat it as fresh.
            cache_fresh = cached_data is not None and (age is None or age <= ttl_seconds)

            if cache_fresh:
                windowed = _windowed(cached_data)
                if not windowed.empty:
                    logger.info(f"Loaded cached data for {symbol}", rows=len(windowed))
                    return windowed

            # Fetch fresh data; a stale cache is kept as an availability
            # fallback so an upstream outage does not kill forecasts.
            try:
                if source == "yahoo":
                    data = await self._fetch_yahoo_data(symbol, start_date, end_date)
                else:
                    data = await self._fetch_alpha_vantage_data(symbol, start_date, end_date)
            except Exception as fetch_error:
                if cached_data is not None:
                    logger.warning(
                        f"Fetch failed for {symbol}; serving stale cache",
                        age_seconds=age,
                        error=str(fetch_error),
                    )
                    return _windowed(cached_data)
                raise
            
            if data is not None and not data.empty:
                # Cache the data
                await self._cache_data(symbol, data, source)
                
                # Record metrics
                record_data_points_processed(source, symbol, len(data))
                
                return data
            if cached_data is not None:
                logger.warning(
                    f"Empty fetch for {symbol}; serving stale cache", age_seconds=age
                )
                return _windowed(cached_data)
            logger.warning(f"No data found for {symbol} from {source}")
            return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Error getting historical data for {symbol}: {e}")
            raise
    
    async def _fetch_yahoo_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Fetch data from Yahoo Finance"""
        try:
            ticker = yf.Ticker(symbol)
            
            # Set date range
            if start_date is None:
                start_date = (datetime.now() - timedelta(days=365*2)).strftime('%Y-%m-%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y-%m-%d')
            
            # Download data
            data = ticker.history(start=start_date, end=end_date)
            
            if data.empty:
                return pd.DataFrame()
            
            # Standardize column names
            data.columns = [col.lower() for col in data.columns]
            
            # Add symbol column
            data['symbol'] = symbol
            
            logger.info(f"Fetched Yahoo data for {symbol}", rows=len(data))
            return data
            
        except Exception as e:
            logger.error(f"Error fetching Yahoo data for {symbol}: {e}")
            return pd.DataFrame()
    
    async def _fetch_alpha_vantage_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Fetch data from Alpha Vantage"""
        try:
            if not settings.ALPHA_VANTAGE_API_KEY:
                logger.warning("Alpha Vantage API key not configured")
                return pd.DataFrame()
            
            # TODO: Implement Alpha Vantage API calls
            # For now, return empty DataFrame
            logger.warning("Alpha Vantage not implemented yet")
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching Alpha Vantage data for {symbol}: {e}")
            return pd.DataFrame()
    
    def _cache_age_seconds(self, symbol: str, source: str) -> Optional[float]:
        """Age of the on-disk cache file, or None if there is no file."""
        cache_file = f"{self.data_path}/processed/{symbol}_{source}.parquet"
        try:
            return time.time() - os.path.getmtime(cache_file)
        except OSError:
            return None

    async def _load_cached_data(self, symbol: str, source: str) -> Optional[pd.DataFrame]:
        """Load cached data from disk"""
        try:
            cache_file = f"{self.data_path}/processed/{symbol}_{source}.parquet"
            
            if os.path.exists(cache_file):
                data = pd.read_parquet(cache_file)
                logger.info(f"Loaded cached data for {symbol}", rows=len(data))
                return data
            
            return None
            
        except Exception as e:
            logger.error(f"Error loading cached data for {symbol}: {e}")
            return None
    
    async def _cache_data(self, symbol: str, data: pd.DataFrame, source: str):
        """Cache data to disk"""
        try:
            cache_file = f"{self.data_path}/processed/{symbol}_{source}.parquet"
            data.to_parquet(cache_file)
            logger.info(f"Cached data for {symbol}", rows=len(data))
            
        except Exception as e:
            logger.error(f"Error caching data for {symbol}: {e}")
    
    async def process_uploaded_file(
        self,
        file: UploadFile,
        symbol: str,
        source: str = "custom"
    ) -> Dict[str, Any]:
        """
        Process uploaded data file
        
        Args:
            file: Uploaded file
            symbol: Stock symbol
            source: Data source
        
        Returns:
            Processing result
        """
        try:
            file_id = str(uuid.uuid4())
            file_extension = os.path.splitext(file.filename)[1].lower()
            
            # Save uploaded file
            temp_path = f"{self.data_path}/temp/{file_id}{file_extension}"
            async with aiofiles.open(temp_path, 'wb') as f:
                content = await file.read()
                await f.write(content)
            
            # Read data based on file type
            if file_extension == '.csv':
                data = pd.read_csv(temp_path, index_col=0, parse_dates=True)
            elif file_extension == '.json':
                data = pd.read_json(temp_path, orient='records')
                if 'date' in data.columns:
                    data.set_index('date', inplace=True)
            elif file_extension == '.parquet':
                data = pd.read_parquet(temp_path)
            elif file_extension == '.xlsx':
                data = pd.read_excel(temp_path, index_col=0, parse_dates=True)
            else:
                raise ValueError(f"Unsupported file type: {file_extension}")
            
            # Validate data
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            data.columns = [col.lower() for col in data.columns]
            
            missing_columns = [col for col in required_columns if col not in data.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")
            
            # Add symbol column
            data['symbol'] = symbol
            
            # Save processed data
            processed_path = f"{self.data_path}/processed/{symbol}_{source}.parquet"
            data.to_parquet(processed_path)
            
            # Clean up temp file
            os.remove(temp_path)
            
            # Record metrics
            record_data_points_processed(source, symbol, len(data))
            
            logger.info(
                "File processed successfully",
                file_id=file_id,
                symbol=symbol,
                rows=len(data)
            )
            
            return {
                "file_id": file_id,
                "rows_processed": len(data),
                "symbol": symbol,
                "source": source
            }
            
        except Exception as e:
            logger.error(f"Error processing uploaded file: {e}")
            raise
    
    async def get_available_symbols(self, source: Optional[str] = None) -> List[str]:
        """Get list of available symbols"""
        try:
            symbols = []
            processed_dir = f"{self.data_path}/processed"
            
            if os.path.exists(processed_dir):
                for file in os.listdir(processed_dir):
                    if file.endswith('.parquet'):
                        # Extract symbol from filename
                        symbol = file.split('_')[0]
                        file_source = file.split('_')[1].split('.')[0]
                        
                        if source is None or file_source == source:
                            symbols.append(symbol)
            
            return list(set(symbols))  # Remove duplicates
            
        except Exception as e:
            logger.error(f"Error getting available symbols: {e}")
            return []
    
    async def get_data_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get information about data for a symbol"""
        try:
            # Check for cached data
            for source in ['yahoo', 'alpha_vantage', 'custom']:
                cache_file = f"{self.data_path}/processed/{symbol}_{source}.parquet"
                
                if os.path.exists(cache_file):
                    data = pd.read_parquet(cache_file)
                    
                    return {
                        "symbol": symbol,
                        "source": source,
                        "last_updated": datetime.fromtimestamp(os.path.getmtime(cache_file)),
                        "data_points": len(data),
                        "date_range": {
                            "start": data.index.min().strftime('%Y-%m-%d'),
                            "end": data.index.max().strftime('%Y-%m-%d')
                        },
                        "columns": list(data.columns)
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting data info for {symbol}: {e}")
            return None
    
    async def refresh_data(self, symbol: str, source: str = "yahoo") -> Dict[str, Any]:
        """Refresh data for a symbol"""
        try:
            # Get existing data
            existing_data = await self._load_cached_data(symbol, source)
            
            # Fetch new data
            new_data = await self.get_historical_data(symbol, source=source)
            
            if new_data.empty:
                return {
                    "new_points": 0,
                    "last_updated": None
                }
            
            if existing_data is not None and not existing_data.empty:
                # Merge with existing data
                combined_data = pd.concat([existing_data, new_data])
                combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                combined_data = combined_data.sort_index()
                
                new_points = len(combined_data) - len(existing_data)
            else:
                combined_data = new_data
                new_points = len(new_data)
            
            # Cache updated data
            await self._cache_data(symbol, combined_data, source)
            
            return {
                "new_points": new_points,
                "last_updated": datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Error refreshing data for {symbol}: {e}")
            raise
    
    async def delete_data(self, symbol: str, source: Optional[str] = None) -> bool:
        """Delete data for a symbol"""
        try:
            deleted = False
            
            if source:
                cache_file = f"{self.data_path}/processed/{symbol}_{source}.parquet"
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                    deleted = True
            else:
                # Delete all sources for symbol
                for source_name in ['yahoo', 'alpha_vantage', 'custom']:
                    cache_file = f"{self.data_path}/processed/{symbol}_{source_name}.parquet"
                    if os.path.exists(cache_file):
                        os.remove(cache_file)
                        deleted = True
            
            return deleted
            
        except Exception as e:
            logger.error(f"Error deleting data for {symbol}: {e}")
            return False
    
    async def get_data_stats(self) -> Dict[str, Any]:
        """Get data statistics"""
        try:
            stats = {
                "total_symbols": 0,
                "total_data_points": 0,
                "data_sources": {},
                "last_updated": None,
                "storage_size": 0
            }
            
            processed_dir = f"{self.data_path}/processed"
            
            if os.path.exists(processed_dir):
                symbols = set()
                total_points = 0
                sources = {}
                last_updated = None
                storage_size = 0
                
                for file in os.listdir(processed_dir):
                    if file.endswith('.parquet'):
                        file_path = os.path.join(processed_dir, file)
                        
                        # Get file stats
                        file_stats = os.stat(file_path)
                        storage_size += file_stats.st_size
                        
                        if last_updated is None or file_stats.st_mtime > last_updated:
                            last_updated = file_stats.st_mtime
                        
                        # Parse filename
                        parts = file.split('_')
                        if len(parts) >= 2:
                            symbol = parts[0]
                            source = parts[1].split('.')[0]
                            
                            symbols.add(symbol)
                            
                            if source not in sources:
                                sources[source] = 0
                            sources[source] += 1
                            
                            # Count data points
                            try:
                                data = pd.read_parquet(file_path)
                                total_points += len(data)
                            except:
                                pass
                
                stats["total_symbols"] = len(symbols)
                stats["total_data_points"] = total_points
                stats["data_sources"] = sources
                stats["last_updated"] = datetime.fromtimestamp(last_updated) if last_updated else None
                stats["storage_size"] = storage_size
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting data stats: {e}")
            return {
                "total_symbols": 0,
                "total_data_points": 0,
                "data_sources": {},
                "last_updated": None,
                "storage_size": 0
            } 