"""
Feature engineering for stock forecasting
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List
import structlog
from datetime import datetime, timedelta

from app.core.config import FEATURE_CONFIG

logger = structlog.get_logger()

class FeatureEngineer:
    """Feature engineering for stock data"""
    
    def __init__(self):
        self.technical_indicators = FEATURE_CONFIG["technical_indicators"]
        self.lag_features = FEATURE_CONFIG["lag_features"]
        self.rolling_windows = FEATURE_CONFIG["rolling_windows"]
    
    async def engineer_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Engineer features from OHLCV data
        
        Args:
            data: DataFrame with OHLCV data
        
        Returns:
            DataFrame with engineered features
        """
        try:
            # Make a copy to avoid modifying original data
            df = data.copy()
            
            # Ensure we have required columns
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            df.columns = [col.lower() for col in df.columns]
            
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")
            
            # Add technical indicators
            df = self._add_technical_indicators(df)
            
            # Add lag features
            df = self._add_lag_features(df)
            
            # Add rolling statistics
            df = self._add_rolling_statistics(df)
            
            # Add calendar features
            df = self._add_calendar_features(df)
            
            # Add volatility features
            df = self._add_volatility_features(df)
            
            # Add price-based features
            df = self._add_price_features(df)
            
            # Add volume features
            df = self._add_volume_features(df)
            
            # Remove any remaining NaN values
            df = df.dropna()
            
            logger.info(f"Feature engineering completed", original_features=len(data.columns), new_features=len(df.columns))
            
            return df
            
        except Exception as e:
            logger.error(f"Error in feature engineering: {e}")
            raise
    
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators"""
        try:
            # Simple Moving Averages
            if 'sma' in self.technical_indicators:
                for window in [5, 10, 20, 50, 100, 200]:
                    df[f'sma_{window}'] = df['close'].rolling(window=window).mean()
                    df[f'price_sma_{window}_ratio'] = df['close'] / df[f'sma_{window}']
            
            # Exponential Moving Averages
            if 'ema' in self.technical_indicators:
                for window in [5, 10, 20, 50, 100]:
                    df[f'ema_{window}'] = df['close'].ewm(span=window).mean()
                    df[f'price_ema_{window}_ratio'] = df['close'] / df[f'ema_{window}']
            
            # RSI (Relative Strength Index)
            if 'rsi' in self.technical_indicators:
                df['rsi'] = self._calculate_rsi(df['close'])
            
            # MACD (Moving Average Convergence Divergence)
            if 'macd' in self.technical_indicators:
                macd_data = self._calculate_macd(df['close'])
                df['macd'] = macd_data['macd']
                df['macd_signal'] = macd_data['signal']
                df['macd_histogram'] = macd_data['histogram']
            
            # Bollinger Bands
            if 'bollinger_bands' in self.technical_indicators:
                bb_data = self._calculate_bollinger_bands(df['close'])
                df['bb_upper'] = bb_data['upper']
                df['bb_lower'] = bb_data['lower']
                df['bb_middle'] = bb_data['middle']
                df['bb_width'] = bb_data['width']
                df['bb_position'] = bb_data['position']
            
            # Stochastic Oscillator
            if 'stochastic' in self.technical_indicators:
                stoch_data = self._calculate_stochastic(df)
                df['stoch_k'] = stoch_data['k']
                df['stoch_d'] = stoch_data['d']
            
            # Williams %R
            if 'williams_r' in self.technical_indicators:
                df['williams_r'] = self._calculate_williams_r(df)
            
            # CCI (Commodity Channel Index)
            if 'cci' in self.technical_indicators:
                df['cci'] = self._calculate_cci(df)
            
            # ADX (Average Directional Index)
            if 'adx' in self.technical_indicators:
                df['adx'] = self._calculate_adx(df)
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding technical indicators: {e}")
            return df
    
    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add lag features"""
        try:
            for lag in self.lag_features:
                df[f'close_lag_{lag}'] = df['close'].shift(lag)
                df[f'volume_lag_{lag}'] = df['volume'].shift(lag)
                df[f'return_lag_{lag}'] = df['close'].pct_change(lag)
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding lag features: {e}")
            return df
    
    def _add_rolling_statistics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add rolling statistics"""
        try:
            for window in self.rolling_windows:
                # Price statistics
                df[f'close_rolling_mean_{window}'] = df['close'].rolling(window=window).mean()
                df[f'close_rolling_std_{window}'] = df['close'].rolling(window=window).std()
                df[f'close_rolling_min_{window}'] = df['close'].rolling(window=window).min()
                df[f'close_rolling_max_{window}'] = df['close'].rolling(window=window).max()
                
                # Volume statistics
                df[f'volume_rolling_mean_{window}'] = df['volume'].rolling(window=window).mean()
                df[f'volume_rolling_std_{window}'] = df['volume'].rolling(window=window).std()
                
                # Volatility (rolling standard deviation of returns)
                returns = df['close'].pct_change()
                df[f'volatility_{window}'] = returns.rolling(window=window).std()
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding rolling statistics: {e}")
            return df
    
    def _add_calendar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add calendar-based features"""
        try:
            # Convert index to datetime if it's not already
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            
            # Day of week (0=Monday, 6=Sunday)
            df['day_of_week'] = df.index.dayofweek
            
            # Day of month
            df['day_of_month'] = df.index.day
            
            # Month
            df['month'] = df.index.month
            
            # Quarter
            df['quarter'] = df.index.quarter
            
            # Year
            df['year'] = df.index.year
            
            # Is month end
            df['is_month_end'] = df.index.is_month_end.astype(int)
            
            # Is quarter end
            df['is_quarter_end'] = df.index.is_quarter_end.astype(int)
            
            # Is year end
            df['is_year_end'] = df.index.is_year_end.astype(int)
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding calendar features: {e}")
            return df
    
    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volatility features"""
        try:
            # Calculate returns
            returns = df['close'].pct_change()
            
            # Realized volatility (rolling standard deviation)
            for window in [5, 10, 20, 50]:
                df[f'realized_volatility_{window}'] = returns.rolling(window=window).std()
            
            # Parkinson volatility (using high-low range) - TODO: Fix syntax error
            # parkinson_factor = 1 / (4 * np.log(2))
            # high_low_log_squared = (np.log(df['high'] / df['low']) ** 2
            # df['parkinson_volatility'] = np.sqrt(
            #     parkinson_factor * high_low_log_squared.rolling(window=20).mean()
            # )
            
            # Garman-Klass volatility - TODO: Fix syntax error
            # high_low_squared = (np.log(df['high'] / df['low']) ** 2
            # open_close_squared = (np.log(df['close'] / df['open']) ** 2
            # gk_vol = (0.5 * high_low_squared) - ((2 * np.log(2) - 1) * open_close_squared)
            # df['garman_klass_volatility'] = np.sqrt(gk_vol).rolling(window=20).mean()
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding volatility features: {e}")
            return df
    
    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add price-based features"""
        try:
            # Price changes
            df['price_change'] = df['close'].diff()
            df['price_change_pct'] = df['close'].pct_change()
            
            # High-Low spread
            df['hl_spread'] = df['high'] - df['low']
            df['hl_spread_pct'] = df['hl_spread'] / df['close']
            
            # Open-Close spread
            df['oc_spread'] = df['close'] - df['open']
            df['oc_spread_pct'] = df['oc_spread'] / df['open']
            
            # Price position within day's range
            df['price_position'] = (df['close'] - df['low']) / (df['high'] - df['low'])
            
            # Price momentum
            for period in [1, 3, 5, 10, 20]:
                df[f'momentum_{period}'] = df['close'] / df['close'].shift(period) - 1
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding price features: {e}")
            return df
    
    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume-based features"""
        try:
            # Volume changes
            df['volume_change'] = df['volume'].diff()
            df['volume_change_pct'] = df['volume'].pct_change()
            
            # Volume moving averages
            for window in [5, 10, 20, 50]:
                df[f'volume_sma_{window}'] = df['volume'].rolling(window=window).mean()
                df[f'volume_ratio_{window}'] = df['volume'] / df[f'volume_sma_{window}']
            
            # Volume-price trend
            df['volume_price_trend'] = (df['volume'] * df['price_change_pct']).cumsum()
            
            # On-balance volume
            df['obv'] = self._calculate_obv(df)
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding volume features: {e}")
            return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """Calculate MACD"""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal).mean()
        histogram = macd - signal_line
        
        return {
            'macd': macd,
            'signal': signal_line,
            'histogram': histogram
        }
    
    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20, std_dev: int = 2) -> Dict[str, pd.Series]:
        """Calculate Bollinger Bands"""
        middle = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        width = (upper - lower) / middle
        position = (prices - lower) / (upper - lower)
        
        return {
            'upper': upper,
            'lower': lower,
            'middle': middle,
            'width': width,
            'position': position
        }
    
    def _calculate_stochastic(self, df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> Dict[str, pd.Series]:
        """Calculate Stochastic Oscillator"""
        lowest_low = df['low'].rolling(window=k_period).min()
        highest_high = df['high'].rolling(window=k_period).max()
        k = 100 * ((df['close'] - lowest_low) / (highest_high - lowest_low))
        d = k.rolling(window=d_period).mean()
        
        return {
            'k': k,
            'd': d
        }
    
    def _calculate_williams_r(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Williams %R"""
        highest_high = df['high'].rolling(window=period).max()
        lowest_low = df['low'].rolling(window=period).min()
        williams_r = -100 * ((highest_high - df['close']) / (highest_high - lowest_low))
        return williams_r
    
    def _calculate_cci(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Calculate CCI (Commodity Channel Index)"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        sma = typical_price.rolling(window=period).mean()
        mad = typical_price.rolling(window=period).apply(lambda x: np.mean(np.abs(x - x.mean())))
        cci = (typical_price - sma) / (0.015 * mad)
        return cci
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ADX (Average Directional Index)"""
        # Simplified ADX calculation
        high_diff = df['high'].diff()
        low_diff = df['low'].diff()
        
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
        
        tr = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                np.abs(df['high'] - df['close'].shift(1)),
                np.abs(df['low'] - df['close'].shift(1))
            )
        )
        
        # Simplified ADX (in practice, this would be more complex)
        adx = pd.Series(tr).rolling(window=period).mean()
        return adx
    
    def _calculate_obv(self, df: pd.DataFrame) -> pd.Series:
        """Calculate On-Balance Volume"""
        obv = pd.Series(index=df.index, dtype=float)
        obv.iloc[0] = df['volume'].iloc[0]
        
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + df['volume'].iloc[i]
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - df['volume'].iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]
        
        return obv 