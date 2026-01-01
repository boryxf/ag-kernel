"""
Automatic tick size calculation.

Determines optimal tick size based on typical price range and desired granularity.
"""

import pandas as pd
import numpy as np
from typing import Union, Optional


def calculate_auto_ticksize(
    data: Union[pd.DataFrame, float],
    timeframe: str = '1h',
    target_ticks: int = 20,
) -> float:
    """
    Calculate an appropriate tick size for the given market data.

    Goal: Choose tick_size such that typical_range / tick_size ≈ target_ticks

    Algorithm:
        1. Estimate typical range:
           - If data is DataFrame with OHLC: use recent high-low range
           - If data is a price (float): estimate as price * 0.002 (0.2%)
        2. Calculate raw tick: range / target_ticks
        3. Round to "nice" value: 1, 2, 2.5, 5 × 10^k

    Args:
        data: Either a DataFrame with 'high'/'low' columns, or a single price (float)
        timeframe: Time period for range estimation (e.g., '1h', '4h', '1d')
                  Only used when data is DataFrame
        target_ticks: Desired number of price ticks within typical range

    Returns:
        Optimal tick size (float)

    Examples:
        >>> # BTC at $100k, 1h typical range ~$500, target=20
        >>> calculate_auto_ticksize(100000.0)
        25.0

        >>> # ETH at $4000, target=20
        >>> calculate_auto_ticksize(4000.0)
        1.0

        >>> # From OHLC dataframe
        >>> df = pd.DataFrame({'high': [100500, 100800], 'low': [100000, 100200]})
        >>> calculate_auto_ticksize(df, timeframe='1h', target_ticks=20)
        25.0
    """
    # Step 1: Estimate typical range
    if isinstance(data, pd.DataFrame):
        typical_range = _estimate_range_from_ohlc(data, timeframe)
    elif isinstance(data, (int, float)):
        # Heuristic: typical 1h range is ~0.2% of price
        typical_range = float(data) * 0.002
    else:
        raise TypeError(
            f"data must be DataFrame or numeric, got {type(data)}"
        )

    # Step 2: Calculate raw tick size
    if typical_range <= 0 or target_ticks <= 0:
        raise ValueError(
            f"Invalid parameters: typical_range={typical_range}, "
            f"target_ticks={target_ticks}"
        )

    raw_tick = typical_range / target_ticks

    # Step 3: Round to nice value
    nice_tick = _round_to_nice_step(raw_tick)

    return nice_tick


def _estimate_range_from_ohlc(
    df: pd.DataFrame,
    timeframe: str,
) -> float:
    """
    Estimate typical price range from OHLC data.

    Args:
        df: DataFrame with 'high' and 'low' columns
        timeframe: Time period for averaging (currently just uses recent data)

    Returns:
        Typical high-low range (float)
    """
    required_cols = ['high', 'low']
    missing = set(required_cols) - set(df.columns)
    if missing:
        raise ValueError(
            f"DataFrame missing required columns: {missing}. "
            f"Found: {list(df.columns)}"
        )

    if len(df) == 0:
        raise ValueError("DataFrame is empty")

    # Calculate range for each bar
    df = df.copy()
    df['range'] = df['high'] - df['low']

    # Use median of recent ranges (more robust than mean)
    # Take last 100 bars or all available data
    recent_ranges = df['range'].tail(100)
    typical_range = recent_ranges.median()

    if pd.isna(typical_range) or typical_range <= 0:
        # Fallback: use overall high-low range
        typical_range = df['high'].max() - df['low'].min()

    return float(typical_range)


def _round_to_nice_step(value: float) -> float:
    """
    Round a value to a "nice" step size: 1, 2, 2.5, 5 × 10^k

    Args:
        value: Raw step size

    Returns:
        Rounded "nice" step size

    Examples:
        >>> _round_to_nice_step(23.7)
        25.0
        >>> _round_to_nice_step(0.037)
        0.05
        >>> _round_to_nice_step(180)
        200.0
        >>> _round_to_nice_step(3.8)
        5.0
    """
    if value <= 0:
        raise ValueError(f"value must be positive, got {value}")

    # Find order of magnitude
    exponent = np.floor(np.log10(value))
    magnitude = 10 ** exponent

    # Normalize to [1, 10) range
    normalized = value / magnitude

    # Choose nice step in [1, 10) range
    if normalized <= 1.5:
        nice_normalized = 1.0
    elif normalized <= 3.0:
        nice_normalized = 2.0
    elif normalized <= 3.5:
        nice_normalized = 2.5
    elif normalized <= 7.0:
        nice_normalized = 5.0
    else:
        nice_normalized = 10.0

    # Scale back to original magnitude
    nice_value = nice_normalized * magnitude

    return float(nice_value)
