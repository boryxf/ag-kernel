#!/usr/bin/env python3
"""
Benchmark C analytics modules vs Python/NumPy implementations.
"""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import numpy as np

# Try to import C implementations
try:
    import _ag_core
    C_AVAILABLE = True
except ImportError as e:
    print(f"C module not available: {e}")
    C_AVAILABLE = False


def benchmark_candles(n_ticks: int = 10_000_000):
    """Benchmark candle aggregation."""
    print(f"\n{'='*60}")
    print(f"CANDLE AGGREGATION BENCHMARK ({n_ticks:,} ticks)")
    print('='*60)

    # Generate test data
    np.random.seed(42)
    timestamps = np.arange(n_ticks, dtype=np.int64) * 100  # 100ms intervals
    price_ticks = (42000 + np.cumsum(np.random.randn(n_ticks) * 5)).astype(np.int64)
    qtys = np.abs(np.random.randn(n_ticks) * 0.1 + 0.05)
    sides = np.random.randint(0, 2, n_ticks, dtype=np.uint8)

    interval_ms = 60000  # 1 minute candles

    results = {}

    # Python/NumPy implementation
    print("\n>>> Python/NumPy (pandas-like)...")
    start = time.perf_counter()
    bucket_idx = timestamps // interval_ms
    unique_buckets = np.unique(bucket_idx)
    py_candles = []
    for b in unique_buckets[:1000]:  # Sample for speed
        mask = bucket_idx == b
        py_candles.append({
            'open': price_ticks[mask][0],
            'high': price_ticks[mask].max(),
            'low': price_ticks[mask].min(),
            'close': price_ticks[mask][-1],
            'volume': qtys[mask].sum(),
        })
    elapsed = time.perf_counter() - start
    py_rate = 1000 / elapsed  # Extrapolate from 1000 candles
    results['python_candles'] = py_rate * (n_ticks / len(unique_buckets))
    print(f"    Python rate: {results['python_candles']:,.0f} ticks/sec")

    # C implementation
    if C_AVAILABLE and hasattr(_ag_core, 'aggregate_candles'):
        print("\n>>> C implementation...")
        start = time.perf_counter()
        candles = _ag_core.aggregate_candles(timestamps, price_ticks, qtys, sides, interval_ms)
        elapsed = time.perf_counter() - start
        results['c_candles'] = n_ticks / elapsed
        results['c_candles_count'] = len(candles['ts_ms'])
        print(f"    C rate: {results['c_candles']:,.0f} ticks/sec")
        print(f"    Candles generated: {results['c_candles_count']:,}")
        if results['python_candles'] > 0:
            print(f"    Speedup: {results['c_candles']/results['python_candles']:.1f}x")

    return results


def benchmark_vwap(n_ticks: int = 10_000_000):
    """Benchmark VWAP calculation."""
    print(f"\n{'='*60}")
    print(f"VWAP BENCHMARK ({n_ticks:,} ticks)")
    print('='*60)

    np.random.seed(42)
    timestamps = np.arange(n_ticks, dtype=np.int64) * 100
    price_ticks = (42000 + np.cumsum(np.random.randn(n_ticks) * 5)).astype(np.int64)
    qtys = np.abs(np.random.randn(n_ticks) * 0.1 + 0.05)
    tick_size = 0.01

    results = {}

    # Python/NumPy
    print("\n>>> Python/NumPy...")
    prices = price_ticks * tick_size
    start = time.perf_counter()
    cum_pv = np.cumsum(prices * qtys)
    cum_vol = np.cumsum(qtys)
    vwap_py = cum_pv / cum_vol
    elapsed = time.perf_counter() - start
    results['python_vwap'] = n_ticks / elapsed
    print(f"    Python rate: {results['python_vwap']:,.0f} ticks/sec")

    # C implementation
    if C_AVAILABLE and hasattr(_ag_core, 'calculate_vwap'):
        print("\n>>> C implementation...")
        start = time.perf_counter()
        vwap_c = _ag_core.calculate_vwap(timestamps, price_ticks, qtys, tick_size)
        elapsed = time.perf_counter() - start
        results['c_vwap'] = n_ticks / elapsed
        print(f"    C rate: {results['c_vwap']:,.0f} ticks/sec")
        print(f"    Speedup: {results['c_vwap']/results['python_vwap']:.1f}x")

        # Verify correctness
        if np.allclose(vwap_py, vwap_c, rtol=1e-6):
            print("    ✓ Results match")
        else:
            print("    ✗ Results differ!")

    return results


def benchmark_volatility(n_candles: int = 1_000_000):
    """Benchmark volatility calculations."""
    print(f"\n{'='*60}")
    print(f"VOLATILITY BENCHMARK ({n_candles:,} candles)")
    print('='*60)

    np.random.seed(42)
    # Generate OHLC data
    close = 42000 + np.cumsum(np.random.randn(n_candles) * 100)
    high = close + np.abs(np.random.randn(n_candles) * 50)
    low = close - np.abs(np.random.randn(n_candles) * 50)
    open_ = close + np.random.randn(n_candles) * 20

    # Convert to int64 ticks
    open_ticks = open_.astype(np.int64)
    high_ticks = high.astype(np.int64)
    low_ticks = low.astype(np.int64)
    close_ticks = close.astype(np.int64)

    window = 20
    results = {}

    # Python realized volatility
    print("\n>>> Python realized volatility...")
    start = time.perf_counter()
    returns = np.diff(np.log(close))
    vol_py = np.zeros(n_candles)
    for i in range(window, n_candles):
        vol_py[i] = np.std(returns[i-window:i]) * np.sqrt(365)
    elapsed = time.perf_counter() - start
    results['python_vol'] = n_candles / elapsed
    print(f"    Python rate: {results['python_vol']:,.0f} candles/sec")

    # C implementation
    if C_AVAILABLE and hasattr(_ag_core, 'calculate_volatility'):
        for method in ['realized', 'parkinson', 'garman_klass', 'yang_zhang']:
            print(f"\n>>> C {method} volatility...")
            candles = {
                'open': open_ticks,
                'high': high_ticks,
                'low': low_ticks,
                'close': close_ticks,
            }
            start = time.perf_counter()
            vol_c = _ag_core.calculate_volatility(candles, method, window, True)
            elapsed = time.perf_counter() - start
            results[f'c_vol_{method}'] = n_candles / elapsed
            print(f"    C rate: {results[f'c_vol_{method}']:,.0f} candles/sec")
            print(f"    Speedup vs Python: {results[f'c_vol_{method}']/results['python_vol']:.1f}x")

    return results


def benchmark_volume_profile(n_ticks: int = 5_000_000):
    """Benchmark volume profile calculation."""
    print(f"\n{'='*60}")
    print(f"VOLUME PROFILE BENCHMARK ({n_ticks:,} ticks)")
    print('='*60)

    np.random.seed(42)
    price_ticks = (42000 + np.cumsum(np.random.randn(n_ticks) * 5)).astype(np.int64)
    qtys = np.abs(np.random.randn(n_ticks) * 0.1 + 0.05)
    sides = np.random.randint(0, 2, n_ticks, dtype=np.uint8)
    tick_size = 0.01

    results = {}

    # Python implementation
    print("\n>>> Python/NumPy...")
    start = time.perf_counter()
    unique_prices, indices = np.unique(price_ticks, return_inverse=True)
    volume_by_price = np.bincount(indices, weights=qtys, minlength=len(unique_prices))
    poc_idx = np.argmax(volume_by_price)
    elapsed = time.perf_counter() - start
    results['python_profile'] = n_ticks / elapsed
    print(f"    Python rate: {results['python_profile']:,.0f} ticks/sec")

    # C implementation
    if C_AVAILABLE and hasattr(_ag_core, 'build_volume_profile'):
        print("\n>>> C implementation...")
        start = time.perf_counter()
        profile = _ag_core.build_volume_profile(price_ticks, qtys, sides, tick_size, 100)
        elapsed = time.perf_counter() - start
        results['c_profile'] = n_ticks / elapsed
        print(f"    C rate: {results['c_profile']:,.0f} ticks/sec")
        if 'poc_price' in profile:
            print(f"    POC: {profile['poc_price']:.2f}")
        print(f"    Speedup: {results['c_profile']/results['python_profile']:.1f}x")

    return results


def benchmark_cumulative_delta(n_ticks: int = 10_000_000):
    """Benchmark cumulative delta calculation."""
    print(f"\n{'='*60}")
    print(f"CUMULATIVE DELTA BENCHMARK ({n_ticks:,} ticks)")
    print('='*60)

    np.random.seed(42)
    qtys = np.abs(np.random.randn(n_ticks) * 0.1 + 0.05)
    sides = np.random.randint(0, 2, n_ticks, dtype=np.uint8)

    results = {}

    # Python
    print("\n>>> Python/NumPy...")
    start = time.perf_counter()
    buy_vol = qtys * (1 - sides)
    sell_vol = qtys * sides
    delta_py = np.cumsum(buy_vol - sell_vol)
    elapsed = time.perf_counter() - start
    results['python_delta'] = n_ticks / elapsed
    print(f"    Python rate: {results['python_delta']:,.0f} ticks/sec")

    # C implementation
    if C_AVAILABLE and hasattr(_ag_core, 'calculate_cumulative_delta'):
        print("\n>>> C implementation...")
        start = time.perf_counter()
        delta_c = _ag_core.calculate_cumulative_delta(qtys, sides)
        elapsed = time.perf_counter() - start
        results['c_delta'] = n_ticks / elapsed
        print(f"    C rate: {results['c_delta']:,.0f} ticks/sec")
        print(f"    Speedup: {results['c_delta']/results['python_delta']:.1f}x")

    return results


def print_summary(all_results: dict):
    """Print summary table."""
    print(f"\n{'='*60}")
    print("SUMMARY: C vs Python Performance")
    print('='*60)
    print(f"{'Metric':<30} {'Python':<15} {'C':<15} {'Speedup':<10}")
    print('-'*60)

    comparisons = [
        ('Candle aggregation', 'python_candles', 'c_candles'),
        ('VWAP calculation', 'python_vwap', 'c_vwap'),
        ('Realized volatility', 'python_vol', 'c_vol_realized'),
        ('Parkinson volatility', 'python_vol', 'c_vol_parkinson'),
        ('Garman-Klass vol', 'python_vol', 'c_vol_garman_klass'),
        ('Yang-Zhang vol', 'python_vol', 'c_vol_yang_zhang'),
        ('Volume profile', 'python_profile', 'c_profile'),
        ('Cumulative delta', 'python_delta', 'c_delta'),
    ]

    for name, py_key, c_key in comparisons:
        py_val = all_results.get(py_key, 0)
        c_val = all_results.get(c_key, 0)
        if py_val > 0 and c_val > 0:
            speedup = c_val / py_val
            print(f"{name:<30} {py_val:>12,.0f}/s {c_val:>12,.0f}/s {speedup:>8.1f}x")


if __name__ == '__main__':
    all_results = {}

    all_results.update(benchmark_candles(10_000_000))
    all_results.update(benchmark_vwap(10_000_000))
    all_results.update(benchmark_volatility(1_000_000))
    all_results.update(benchmark_volume_profile(5_000_000))
    all_results.update(benchmark_cumulative_delta(10_000_000))

    print_summary(all_results)
