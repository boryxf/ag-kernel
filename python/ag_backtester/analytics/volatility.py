"""
Volatility calculation utilities.

This module provides various volatility estimators:
- Realized volatility (close-to-close)
- Parkinson volatility (high-low range)
- Garman-Klass volatility (OHLC-based)
- Yang-Zhang volatility (overnight-adjusted)
"""
import numpy as np
from typing import Optional


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """
    Calculate rolling mean using pure numpy.

    Args:
        arr: Input array
        window: Window size

    Returns:
        Rolling mean array (same length, NaN for insufficient data)
    """
    if len(arr) == 0:
        return arr.copy()

    result = np.full_like(arr, np.nan, dtype=np.float64)

    # Use cumsum for efficient rolling mean
    cumsum = np.cumsum(arr)

    # For indices >= window
    result[window:] = (cumsum[window:] - cumsum[:-window]) / window

    # For indices < window, use expanding mean
    for i in range(window):
        result[i] = cumsum[i] / (i + 1) if i > 0 else arr[0]

    return result


def _try_scipy_filter(arr: np.ndarray, window: int) -> np.ndarray:
    """
    Try to use scipy uniform_filter1d, fall back to numpy.

    Args:
        arr: Input array
        window: Window size

    Returns:
        Filtered array
    """
    try:
        from scipy.ndimage import uniform_filter1d
        return uniform_filter1d(arr, window, mode='constant', origin=-(window // 2))
    except ImportError:
        return _rolling_mean(arr, window)


def calculate_realized_volatility(
    prices: np.ndarray,
    window: int = 100,
    annualize: bool = True,
    trading_periods: int = 365 * 24 * 60,
) -> np.ndarray:
    """
    Calculate rolling realized volatility from log returns.

    Realized volatility is the standard deviation of log returns over
    a rolling window. It's the most common volatility measure.

    Args:
        prices: Array of prices (float64)
        window: Rolling window size (default: 100)
        annualize: Whether to annualize the result (default: True)
        trading_periods: Periods per year for annualization
            (default: 365 * 24 * 60 = minutes per year)

    Returns:
        Array of rolling volatility values (same length as prices,
        first value is NaN due to return calculation)

    Example:
        >>> prices = np.array([100.0, 101.0, 99.5, 100.5, 101.5])
        >>> vol = calculate_realized_volatility(prices, window=3)
        >>> print(f"Current vol: {vol[-1]:.4f}")
    """
    if len(prices) < 2:
        return np.full(len(prices), np.nan)

    # Calculate log returns
    with np.errstate(divide='ignore', invalid='ignore'):
        log_returns = np.diff(np.log(prices))

    # Replace invalid values
    log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)

    # Rolling variance of squared returns
    squared_returns = log_returns ** 2
    rolling_var = _try_scipy_filter(squared_returns, window)
    rolling_std = np.sqrt(np.maximum(rolling_var, 0))

    if annualize:
        rolling_std = rolling_std * np.sqrt(trading_periods)

    # Pad to match original length (first return is undefined)
    return np.concatenate([[np.nan], rolling_std])


def calculate_parkinson_volatility(
    highs: np.ndarray,
    lows: np.ndarray,
    window: int = 100,
    annualize: bool = True,
    trading_periods: int = 365 * 24 * 60,
) -> np.ndarray:
    """
    Parkinson volatility estimator using high-low range.

    The Parkinson estimator uses the high-low range to estimate
    volatility. It's more efficient than close-to-close volatility
    because it uses more price information.

    Formula: sigma^2 = (1 / (4 * ln(2))) * E[(ln(H/L))^2]

    Args:
        highs: Array of high prices
        lows: Array of low prices
        window: Rolling window size (default: 100)
        annualize: Whether to annualize the result (default: True)
        trading_periods: Periods per year for annualization

    Returns:
        Array of Parkinson volatility values

    Example:
        >>> candles = ticks_to_candles(...)
        >>> vol = calculate_parkinson_volatility(
        ...     candles['high'], candles['low'], window=20
        ... )
    """
    if len(highs) == 0:
        return np.array([], dtype=np.float64)

    # Parkinson constant
    factor = 1.0 / (4.0 * np.log(2))

    # Calculate log(H/L)^2
    with np.errstate(divide='ignore', invalid='ignore'):
        log_hl = np.log(highs / lows)
        log_hl = np.where(np.isfinite(log_hl), log_hl, 0.0)

    log_hl_squared = log_hl ** 2

    # Rolling mean
    rolling_var = _try_scipy_filter(log_hl_squared, window) * factor
    rolling_std = np.sqrt(np.maximum(rolling_var, 0))

    if annualize:
        rolling_std = rolling_std * np.sqrt(trading_periods)

    return rolling_std


def calculate_garman_klass_volatility(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 100,
    annualize: bool = True,
    trading_periods: int = 365 * 24 * 60,
) -> np.ndarray:
    """
    Garman-Klass volatility estimator using OHLC data.

    The Garman-Klass estimator is more efficient than both close-to-close
    and Parkinson estimators because it uses all OHLC price data.

    Formula: sigma^2 = 0.5 * (ln(H/L))^2 - (2*ln(2) - 1) * (ln(C/O))^2

    Args:
        opens: Array of opening prices
        highs: Array of high prices
        lows: Array of low prices
        closes: Array of closing prices
        window: Rolling window size (default: 100)
        annualize: Whether to annualize the result (default: True)
        trading_periods: Periods per year for annualization

    Returns:
        Array of Garman-Klass volatility values

    Example:
        >>> candles = ticks_to_candles(...)
        >>> vol = calculate_garman_klass_volatility(
        ...     candles['open'], candles['high'],
        ...     candles['low'], candles['close'],
        ...     window=20
        ... )
    """
    if len(opens) == 0:
        return np.array([], dtype=np.float64)

    # Calculate components
    with np.errstate(divide='ignore', invalid='ignore'):
        log_hl = np.log(highs / lows)
        log_co = np.log(closes / opens)

        log_hl = np.where(np.isfinite(log_hl), log_hl, 0.0)
        log_co = np.where(np.isfinite(log_co), log_co, 0.0)

    # Garman-Klass formula
    gk = 0.5 * (log_hl ** 2) - (2 * np.log(2) - 1) * (log_co ** 2)

    # Rolling mean
    rolling_var = _try_scipy_filter(gk, window)
    rolling_std = np.sqrt(np.maximum(rolling_var, 0))

    if annualize:
        rolling_std = rolling_std * np.sqrt(trading_periods)

    return rolling_std


def calculate_yang_zhang_volatility(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 100,
    annualize: bool = True,
    trading_periods: int = 365 * 24 * 60,
) -> np.ndarray:
    """
    Yang-Zhang volatility estimator with overnight adjustment.

    The Yang-Zhang estimator combines overnight volatility (close-to-open)
    with intraday volatility for a more complete picture. It handles
    opening gaps better than other estimators.

    Args:
        opens: Array of opening prices
        highs: Array of high prices
        lows: Array of low prices
        closes: Array of closing prices
        window: Rolling window size (default: 100)
        annualize: Whether to annualize the result (default: True)
        trading_periods: Periods per year for annualization

    Returns:
        Array of Yang-Zhang volatility values
    """
    if len(opens) < 2:
        return np.full(len(opens), np.nan)

    # Overnight returns (close-to-open)
    with np.errstate(divide='ignore', invalid='ignore'):
        log_co = np.log(opens[1:] / closes[:-1])
        log_co = np.where(np.isfinite(log_co), log_co, 0.0)

    # Open-to-close returns
    with np.errstate(divide='ignore', invalid='ignore'):
        log_oc = np.log(closes / opens)
        log_oc = np.where(np.isfinite(log_oc), log_oc, 0.0)

    # Rogers-Satchell volatility (intraday component)
    with np.errstate(divide='ignore', invalid='ignore'):
        log_ho = np.log(highs / opens)
        log_lo = np.log(lows / opens)
        log_hc = np.log(highs / closes)
        log_lc = np.log(lows / closes)

        log_ho = np.where(np.isfinite(log_ho), log_ho, 0.0)
        log_lo = np.where(np.isfinite(log_lo), log_lo, 0.0)
        log_hc = np.where(np.isfinite(log_hc), log_hc, 0.0)
        log_lc = np.where(np.isfinite(log_lc), log_lc, 0.0)

    rs = log_ho * log_hc + log_lo * log_lc

    # Calculate rolling components
    k = 0.34 / (1.34 + (window + 1) / (window - 1))

    # Overnight variance
    overnight_var = _try_scipy_filter(log_co ** 2, window - 1)
    overnight_var = np.concatenate([[np.nan], overnight_var])

    # Open-to-close variance
    oc_var = _try_scipy_filter(log_oc ** 2, window)

    # Rogers-Satchell variance
    rs_var = _try_scipy_filter(rs, window)

    # Yang-Zhang combination
    yz_var = overnight_var * k + oc_var * (1 - k) + rs_var

    rolling_std = np.sqrt(np.maximum(yz_var, 0))

    if annualize:
        rolling_std = rolling_std * np.sqrt(trading_periods)

    return rolling_std


def calculate_exponential_volatility(
    prices: np.ndarray,
    span: int = 20,
    annualize: bool = True,
    trading_periods: int = 365 * 24 * 60,
) -> np.ndarray:
    """
    Calculate exponentially weighted moving average (EWMA) volatility.

    EWMA volatility gives more weight to recent observations, making it
    more responsive to recent market conditions.

    Args:
        prices: Array of prices
        span: EWMA span (similar to window, default: 20)
        annualize: Whether to annualize the result
        trading_periods: Periods per year for annualization

    Returns:
        Array of EWMA volatility values
    """
    if len(prices) < 2:
        return np.full(len(prices), np.nan)

    # Calculate log returns
    with np.errstate(divide='ignore', invalid='ignore'):
        log_returns = np.diff(np.log(prices))
        log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)

    # EWMA decay factor
    alpha = 2.0 / (span + 1)

    # Initialize
    squared_returns = log_returns ** 2
    ewma_var = np.zeros(len(squared_returns))
    ewma_var[0] = squared_returns[0]

    # EWMA calculation
    for i in range(1, len(squared_returns)):
        ewma_var[i] = alpha * squared_returns[i] + (1 - alpha) * ewma_var[i - 1]

    ewma_std = np.sqrt(ewma_var)

    if annualize:
        ewma_std = ewma_std * np.sqrt(trading_periods)

    # Pad to match original length
    return np.concatenate([[np.nan], ewma_std])


__all__ = [
    'calculate_realized_volatility',
    'calculate_parkinson_volatility',
    'calculate_garman_klass_volatility',
    'calculate_yang_zhang_volatility',
    'calculate_exponential_volatility',
]
