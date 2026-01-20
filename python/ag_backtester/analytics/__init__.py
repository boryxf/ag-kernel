"""
Analytics module for ag-backtester.

This module provides tools for analyzing tick and candle data:
- candles: OHLCV candle construction and resampling
- volume: Volume profile, VWAP, and order flow analysis
- volatility: Realized and range-based volatility estimators
"""
from .candles import (
    ticks_to_candles,
    resample_candles,
    candles_to_dataframe,
    candles_to_pandas,
)
from .volume import (
    calculate_vwap,
    calculate_volume_profile,
    calculate_order_flow_imbalance,
    calculate_cumulative_delta,
    calculate_trade_intensity,
)
from .volatility import (
    calculate_realized_volatility,
    calculate_parkinson_volatility,
    calculate_garman_klass_volatility,
    calculate_yang_zhang_volatility,
    calculate_exponential_volatility,
)

__all__ = [
    # Candles
    'ticks_to_candles',
    'resample_candles',
    'candles_to_dataframe',
    'candles_to_pandas',
    # Volume
    'calculate_vwap',
    'calculate_volume_profile',
    'calculate_order_flow_imbalance',
    'calculate_cumulative_delta',
    'calculate_trade_intensity',
    # Volatility
    'calculate_realized_volatility',
    'calculate_parkinson_volatility',
    'calculate_garman_klass_volatility',
    'calculate_yang_zhang_volatility',
    'calculate_exponential_volatility',
]
