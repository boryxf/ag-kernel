"""
Volume analytics for tick and candle data.

This module provides functions for:
- VWAP (Volume Weighted Average Price) calculation
- Volume profile analysis (price distribution of volume)
- Order flow imbalance metrics
"""
import numpy as np
from typing import Dict, Optional


def calculate_vwap(
    prices: np.ndarray,
    volumes: np.ndarray,
) -> np.ndarray:
    """
    Calculate cumulative VWAP (Volume Weighted Average Price).

    VWAP is a trading benchmark that gives the average price weighted by
    volume. It's commonly used by institutional traders to assess execution
    quality.

    Args:
        prices: Array of prices (float64)
        volumes: Array of volumes (float64)

    Returns:
        Array of cumulative VWAP values (same length as input)

    Example:
        >>> prices = np.array([100.0, 101.0, 99.5, 100.5])
        >>> volumes = np.array([100.0, 50.0, 200.0, 75.0])
        >>> vwap = calculate_vwap(prices, volumes)
        >>> print(f"Final VWAP: {vwap[-1]:.2f}")
    """
    if len(prices) == 0:
        return np.array([], dtype=np.float64)

    cum_pv = np.cumsum(prices * volumes)
    cum_v = np.cumsum(volumes)

    # Avoid division by zero
    with np.errstate(divide='ignore', invalid='ignore'):
        vwap = np.where(cum_v > 0, cum_pv / cum_v, prices)

    return vwap


def calculate_volume_profile(
    price_ticks: np.ndarray,
    qtys: np.ndarray,
    sides: np.ndarray,
    n_bins: int = 50,
    tick_size: Optional[float] = None,
) -> Dict[str, np.ndarray]:
    """
    Calculate volume profile (price distribution of volume).

    Volume profile shows where volume was traded at different price levels,
    useful for identifying support/resistance levels and high-volume nodes.

    Args:
        price_ticks: Array of int64 price ticks
        qtys: Array of float64 quantities
        sides: Array of uint8 sides (0=BUY, 1=SELL)
        n_bins: Number of price bins (default: 50)
        tick_size: If provided, convert price_ticks to actual prices

    Returns:
        Dict with:
        - price_levels: Center price of each bin
        - total_volume: Total volume at each price level
        - buy_volume: Buy-side volume at each price level
        - sell_volume: Sell-side volume at each price level
        - delta: Volume delta (buy - sell) at each price level

    Example:
        >>> profile = calculate_volume_profile(price_ticks, qtys, sides)
        >>> # Find price with highest volume (POC - Point of Control)
        >>> poc_idx = np.argmax(profile['total_volume'])
        >>> poc_price = profile['price_levels'][poc_idx]
    """
    if len(price_ticks) == 0:
        return {
            'price_levels': np.array([], dtype=np.float64),
            'total_volume': np.array([], dtype=np.float64),
            'buy_volume': np.array([], dtype=np.float64),
            'sell_volume': np.array([], dtype=np.float64),
            'delta': np.array([], dtype=np.float64),
        }

    # Convert to float for calculations
    prices = price_ticks.astype(np.float64)
    if tick_size is not None:
        prices = prices * tick_size

    price_min, price_max = prices.min(), prices.max()

    # Handle case where all prices are the same
    if price_min == price_max:
        return {
            'price_levels': np.array([price_min], dtype=np.float64),
            'total_volume': np.array([qtys.sum()], dtype=np.float64),
            'buy_volume': np.array([qtys[sides == 0].sum()], dtype=np.float64),
            'sell_volume': np.array([qtys[sides == 1].sum()], dtype=np.float64),
            'delta': np.array([qtys[sides == 0].sum() - qtys[sides == 1].sum()], dtype=np.float64),
        }

    bins = np.linspace(price_min, price_max, n_bins + 1)

    # Digitize prices into bins
    bin_idx = np.digitize(prices, bins) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    # Calculate volumes per bin
    total_vol = np.zeros(n_bins, dtype=np.float64)
    buy_vol = np.zeros(n_bins, dtype=np.float64)
    sell_vol = np.zeros(n_bins, dtype=np.float64)

    np.add.at(total_vol, bin_idx, qtys)

    # Buy volume (side == 0)
    buy_mask = sides == 0
    np.add.at(buy_vol, bin_idx[buy_mask], qtys[buy_mask])

    # Sell volume (side == 1)
    sell_mask = sides == 1
    np.add.at(sell_vol, bin_idx[sell_mask], qtys[sell_mask])

    # Calculate bin centers
    price_levels = (bins[:-1] + bins[1:]) / 2

    return {
        'price_levels': price_levels,
        'total_volume': total_vol,
        'buy_volume': buy_vol,
        'sell_volume': sell_vol,
        'delta': buy_vol - sell_vol,
    }


def _rolling_sum(arr: np.ndarray, window: int) -> np.ndarray:
    """
    Calculate rolling sum using pure numpy (no scipy dependency).

    Args:
        arr: Input array
        window: Window size

    Returns:
        Rolling sum array (same length, padded at start)
    """
    if len(arr) == 0:
        return arr.copy()

    # Use cumsum for efficient rolling sum
    cumsum = np.cumsum(arr)
    result = np.zeros_like(arr, dtype=np.float64)

    # For indices >= window, subtract cumsum[i-window] from cumsum[i]
    result[window:] = cumsum[window:] - cumsum[:-window]

    # For indices < window, use cumsum directly (partial window)
    result[:window] = cumsum[:window]

    return result


def calculate_order_flow_imbalance(
    qtys: np.ndarray,
    sides: np.ndarray,
    window: int = 100,
) -> np.ndarray:
    """
    Calculate rolling order flow imbalance.

    Order Flow Imbalance (OFI) measures the relative strength of buying
    versus selling pressure over a rolling window:

        OFI = (buy_volume - sell_volume) / total_volume

    Values range from -1 (all sells) to +1 (all buys).

    Args:
        qtys: Array of float64 trade quantities
        sides: Array of uint8 trade sides (0=BUY, 1=SELL)
        window: Rolling window size (default: 100)

    Returns:
        Array of OFI values (same length as input, NaN for insufficient data)

    Example:
        >>> ofi = calculate_order_flow_imbalance(qtys, sides, window=50)
        >>> # Strong buying pressure when OFI > 0.3
        >>> buy_signals = ofi > 0.3
    """
    if len(qtys) == 0:
        return np.array([], dtype=np.float64)

    qtys = qtys.astype(np.float64)

    # Separate buy and sell volumes
    buy_vol = qtys * (1 - sides.astype(np.float64))
    sell_vol = qtys * sides.astype(np.float64)

    # Try to use scipy for better rolling calculation
    try:
        from scipy.ndimage import uniform_filter1d
        cum_buy = uniform_filter1d(buy_vol, window, mode='constant', origin=-(window // 2))
        cum_sell = uniform_filter1d(sell_vol, window, mode='constant', origin=-(window // 2))
    except ImportError:
        # Fallback to pure numpy rolling sum
        cum_buy = _rolling_sum(buy_vol, window) / window
        cum_sell = _rolling_sum(sell_vol, window) / window

    total = cum_buy + cum_sell

    # Calculate OFI, handling division by zero
    with np.errstate(divide='ignore', invalid='ignore'):
        ofi = np.where(total > 0, (cum_buy - cum_sell) / total, 0.0)

    return ofi


def calculate_cumulative_delta(
    qtys: np.ndarray,
    sides: np.ndarray,
) -> np.ndarray:
    """
    Calculate cumulative volume delta (buy volume - sell volume).

    Cumulative delta is useful for tracking overall order flow direction
    and identifying divergences between price and volume.

    Args:
        qtys: Array of float64 trade quantities
        sides: Array of uint8 trade sides (0=BUY, 1=SELL)

    Returns:
        Array of cumulative delta values

    Example:
        >>> cum_delta = calculate_cumulative_delta(qtys, sides)
        >>> # Price rising but cum_delta falling = bearish divergence
    """
    if len(qtys) == 0:
        return np.array([], dtype=np.float64)

    qtys = qtys.astype(np.float64)

    # Delta = buy volume - sell volume
    delta = qtys * (1 - 2 * sides.astype(np.float64))

    return np.cumsum(delta)


def calculate_trade_intensity(
    timestamps: np.ndarray,
    window_ms: int = 1000,
) -> np.ndarray:
    """
    Calculate rolling trade intensity (trades per time window).

    Trade intensity measures market activity and can indicate
    increased volatility or breakout potential.

    Args:
        timestamps: Array of int64 timestamps in milliseconds
        window_ms: Window size in milliseconds (default: 1000 = 1 second)

    Returns:
        Array of trade counts per window (same length as input)
    """
    if len(timestamps) == 0:
        return np.array([], dtype=np.float64)

    # Count trades in trailing window for each timestamp
    intensity = np.zeros(len(timestamps), dtype=np.float64)

    for i, ts in enumerate(timestamps):
        # Count trades in [ts - window_ms, ts]
        mask = (timestamps >= ts - window_ms) & (timestamps <= ts)
        intensity[i] = np.sum(mask)

    return intensity


__all__ = [
    'calculate_vwap',
    'calculate_volume_profile',
    'calculate_order_flow_imbalance',
    'calculate_cumulative_delta',
    'calculate_trade_intensity',
]
