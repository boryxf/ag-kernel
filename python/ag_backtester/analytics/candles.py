"""
OHLCV candle construction and resampling utilities.

This module provides functions to convert tick data to OHLCV candles
and resample candles to larger timeframes.
"""
import numpy as np
import polars as pl
from typing import Dict, Union, Optional


def ticks_to_candles(
    timestamps: np.ndarray,
    price_ticks: np.ndarray,
    qtys: np.ndarray,
    sides: np.ndarray,
    tick_size: float,
    interval_ms: int = 60000,
) -> Dict[str, np.ndarray]:
    """
    Convert tick data to OHLCV candles.

    This function aggregates tick-level trade data into standard OHLCV
    (Open, High, Low, Close, Volume) candles at the specified interval.
    It also tracks buy/sell volume separately for order flow analysis.

    Args:
        timestamps: Array of int64 timestamps in milliseconds (Unix epoch)
        price_ticks: Array of int64 price ticks (integer price representation)
        qtys: Array of float64 trade quantities
        sides: Array of uint8 trade sides (0=BUY, 1=SELL)
        tick_size: Price per tick (e.g., 0.01 for $0.01 increments)
        interval_ms: Candle interval in milliseconds (default: 60000 = 1 minute)

    Returns:
        Dict with numpy arrays:
        - ts_open: Candle open timestamps (ms)
        - open: Opening prices
        - high: High prices
        - low: Low prices
        - close: Closing prices
        - volume: Total volume
        - buy_volume: Buy-side volume (side=0)
        - sell_volume: Sell-side volume (side=1)
        - trade_count: Number of trades per candle

    Example:
        >>> timestamps = np.array([1000, 1500, 2000, 61000, 62000])
        >>> price_ticks = np.array([10000, 10010, 10005, 10020, 10015])
        >>> qtys = np.array([1.0, 2.0, 1.5, 0.5, 1.0])
        >>> sides = np.array([0, 1, 0, 1, 0], dtype=np.uint8)
        >>> candles = ticks_to_candles(
        ...     timestamps, price_ticks, qtys, sides,
        ...     tick_size=0.01, interval_ms=60000
        ... )
        >>> print(candles['close'])  # Closing prices per minute
    """
    # Validate inputs
    if len(timestamps) == 0:
        return {
            'ts_open': np.array([], dtype=np.int64),
            'open': np.array([], dtype=np.float64),
            'high': np.array([], dtype=np.float64),
            'low': np.array([], dtype=np.float64),
            'close': np.array([], dtype=np.float64),
            'volume': np.array([], dtype=np.float64),
            'buy_volume': np.array([], dtype=np.float64),
            'sell_volume': np.array([], dtype=np.float64),
            'trade_count': np.array([], dtype=np.int64),
        }

    # Convert price ticks to actual prices
    prices = price_ticks.astype(np.float64) * tick_size

    # Use Polars for fast groupby operations
    df = pl.DataFrame({
        'ts': timestamps,
        'price': prices,
        'qty': qtys,
        'side': sides,
    })

    candles = (
        df
        .with_columns([
            ((pl.col('ts') // interval_ms) * interval_ms).alias('ts_open'),
        ])
        .group_by('ts_open')
        .agg([
            pl.col('price').first().alias('open'),
            pl.col('price').max().alias('high'),
            pl.col('price').min().alias('low'),
            pl.col('price').last().alias('close'),
            pl.col('qty').sum().alias('volume'),
            pl.col('qty').filter(pl.col('side') == 0).sum().alias('buy_volume'),
            pl.col('qty').filter(pl.col('side') == 1).sum().alias('sell_volume'),
            pl.len().alias('trade_count'),
        ])
        .sort('ts_open')
    )

    # Handle null values in buy_volume/sell_volume (when no buys/sells in candle)
    return {
        'ts_open': candles['ts_open'].to_numpy(),
        'open': candles['open'].to_numpy(),
        'high': candles['high'].to_numpy(),
        'low': candles['low'].to_numpy(),
        'close': candles['close'].to_numpy(),
        'volume': candles['volume'].to_numpy(),
        'buy_volume': candles['buy_volume'].fill_null(0).to_numpy(),
        'sell_volume': candles['sell_volume'].fill_null(0).to_numpy(),
        'trade_count': candles['trade_count'].to_numpy(),
    }


def resample_candles(
    candles: Dict[str, np.ndarray],
    target_interval_ms: int,
    source_interval_ms: Optional[int] = None,
) -> Dict[str, np.ndarray]:
    """
    Resample candles to a larger timeframe.

    This function aggregates candles from a smaller timeframe to a larger one.
    The target interval must be a multiple of the source interval.

    Args:
        candles: Dict of candle arrays from ticks_to_candles() or previous resample
        target_interval_ms: Target candle interval in milliseconds
        source_interval_ms: Source interval (auto-detected if not provided)

    Returns:
        Dict with resampled candle arrays (same structure as input)

    Example:
        >>> # Resample 1-minute candles to 5-minute candles
        >>> candles_5m = resample_candles(candles_1m, target_interval_ms=300000)

    Raises:
        ValueError: If target_interval_ms is not larger than source interval
    """
    ts_open = candles['ts_open']

    if len(ts_open) == 0:
        return candles.copy()

    # Auto-detect source interval from timestamp differences
    if source_interval_ms is None and len(ts_open) > 1:
        diffs = np.diff(ts_open)
        source_interval_ms = int(np.min(diffs[diffs > 0])) if len(diffs[diffs > 0]) > 0 else target_interval_ms

    if source_interval_ms is not None and target_interval_ms <= source_interval_ms:
        raise ValueError(
            f"target_interval_ms ({target_interval_ms}) must be larger than "
            f"source_interval_ms ({source_interval_ms})"
        )

    # Use Polars for efficient resampling
    df = pl.DataFrame({
        'ts_open': ts_open,
        'open': candles['open'],
        'high': candles['high'],
        'low': candles['low'],
        'close': candles['close'],
        'volume': candles['volume'],
        'buy_volume': candles['buy_volume'],
        'sell_volume': candles['sell_volume'],
        'trade_count': candles['trade_count'],
    })

    resampled = (
        df
        .with_columns([
            ((pl.col('ts_open') // target_interval_ms) * target_interval_ms).alias('ts_bucket'),
        ])
        .group_by('ts_bucket')
        .agg([
            pl.col('open').first().alias('open'),
            pl.col('high').max().alias('high'),
            pl.col('low').min().alias('low'),
            pl.col('close').last().alias('close'),
            pl.col('volume').sum().alias('volume'),
            pl.col('buy_volume').sum().alias('buy_volume'),
            pl.col('sell_volume').sum().alias('sell_volume'),
            pl.col('trade_count').sum().alias('trade_count'),
        ])
        .sort('ts_bucket')
    )

    return {
        'ts_open': resampled['ts_bucket'].to_numpy(),
        'open': resampled['open'].to_numpy(),
        'high': resampled['high'].to_numpy(),
        'low': resampled['low'].to_numpy(),
        'close': resampled['close'].to_numpy(),
        'volume': resampled['volume'].to_numpy(),
        'buy_volume': resampled['buy_volume'].to_numpy(),
        'sell_volume': resampled['sell_volume'].to_numpy(),
        'trade_count': resampled['trade_count'].to_numpy(),
    }


def candles_to_dataframe(candles: Dict[str, np.ndarray]) -> pl.DataFrame:
    """
    Convert candles dict to a Polars DataFrame.

    Args:
        candles: Dict of candle arrays

    Returns:
        Polars DataFrame with candle data
    """
    return pl.DataFrame(candles)


def candles_to_pandas(candles: Dict[str, np.ndarray]):
    """
    Convert candles dict to a Pandas DataFrame.

    Args:
        candles: Dict of candle arrays

    Returns:
        Pandas DataFrame with candle data
    """
    import pandas as pd
    return pd.DataFrame(candles)


__all__ = [
    'ticks_to_candles',
    'resample_candles',
    'candles_to_dataframe',
    'candles_to_pandas',
]
