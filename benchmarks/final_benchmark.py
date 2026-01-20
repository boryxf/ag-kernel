#!/usr/bin/env python3
"""
Final benchmark script for ag-kernel v0.3.0 performance testing.
Run AFTER all optimizations to measure improvements.
"""

import time
import sys
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import numpy as np
import pandas as pd

# Try imports
try:
    import polars as pl
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False

try:
    from ag_backtester import Engine, EngineConfig, SIDE_BUY, SIDE_SELL
    from ag_backtester.engine import Tick, Order
    RUST_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Rust engine not available: {e}")
    RUST_AVAILABLE = False

# Try to import new optimized functions
try:
    from ag_backtester.data.fast_aggregator import aggregate_ticks_polars, aggregate_to_numpy
    FAST_AGG_AVAILABLE = True
except ImportError:
    FAST_AGG_AVAILABLE = False

try:
    from ag_backtester.data.aggtrades import AggTradesFeed
    AGGTRADES_AVAILABLE = True
except ImportError:
    AGGTRADES_AVAILABLE = False

try:
    from ag_backtester.analytics.candles import ticks_to_candles
    from ag_backtester.analytics.volume import calculate_vwap, calculate_volume_profile
    from ag_backtester.analytics.volatility import calculate_realized_volatility
    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False


def benchmark_data_loading(csv_path: str, n_rows: int = 1_000_000) -> dict:
    """Benchmark data loading methods"""
    results = {}

    # 1. Pandas read_csv baseline
    start = time.perf_counter()
    df = pd.read_csv(csv_path, nrows=n_rows)
    results['pandas_read_csv_sec'] = time.perf_counter() - start
    results['rows_loaded'] = len(df)

    # 2. Vectorized numpy (optimized)
    start = time.perf_counter()
    # Handle both column name formats
    ts_col = 'transact_time' if 'transact_time' in df.columns else 'timestamp'
    qty_col = 'quantity' if 'quantity' in df.columns else 'qty'

    timestamps = df[ts_col].values.astype(np.int64)
    prices = df['price'].values
    qtys = df[qty_col].values.astype(np.float64)
    sides = df['is_buyer_maker'].values.astype(np.uint8)
    price_ticks = np.round(prices / 0.1).astype(np.int64)
    results['vectorized_load_sec'] = time.perf_counter() - start
    results['vectorized_rows_per_sec'] = n_rows / results['vectorized_load_sec']

    # 3. Polars read (if available)
    if POLARS_AVAILABLE:
        start = time.perf_counter()
        df_pl = pl.read_csv(csv_path, n_rows=n_rows)
        results['polars_read_sec'] = time.perf_counter() - start
        results['polars_rows_per_sec'] = n_rows / results['polars_read_sec']

    return results


def benchmark_aggregation(csv_path: str, n_rows: int = 1_000_000) -> dict:
    """Benchmark aggregation methods"""
    results = {}
    bucket_ms = 1000
    tick_size = 0.1

    # Load data once
    df = pd.read_csv(csv_path, nrows=n_rows)
    ts_col = 'transact_time' if 'transact_time' in df.columns else 'timestamp'
    qty_col = 'quantity' if 'quantity' in df.columns else 'qty'

    # 1. Python dict (baseline - slow)
    start = time.perf_counter()
    buckets = {}
    sample_size = min(len(df), 50000)  # Smaller sample for slow method
    for i in range(sample_size):
        row = df.iloc[i]
        ts = int(row[ts_col])
        bucket_ts = (ts // bucket_ms) * bucket_ms
        price_tick = round(row['price'] / tick_size)
        side = 'SELL' if row['is_buyer_maker'] else 'BUY'
        key = (bucket_ts, price_tick, side)
        buckets[key] = buckets.get(key, 0) + row[qty_col]
    elapsed = time.perf_counter() - start
    results['python_dict_per_sec'] = sample_size / elapsed

    # 2. Pandas groupby
    df['bucket_ts'] = (df[ts_col] // bucket_ms) * bucket_ms
    df['price_tick'] = (df['price'] / tick_size).round().astype(int)
    df['side'] = np.where(df['is_buyer_maker'], 1, 0)

    start = time.perf_counter()
    agg = df.groupby(['bucket_ts', 'price_tick', 'side'])[qty_col].sum()
    results['pandas_groupby_sec'] = time.perf_counter() - start
    results['pandas_groupby_per_sec'] = n_rows / results['pandas_groupby_sec']

    # 3. Polars (if available)
    if POLARS_AVAILABLE:
        start = time.perf_counter()
        df_pl = pl.read_csv(csv_path, n_rows=n_rows)

        # Detect column names
        ts_col_pl = 'transact_time' if 'transact_time' in df_pl.columns else 'timestamp'
        qty_col_pl = 'quantity' if 'quantity' in df_pl.columns else 'qty'

        result = (
            df_pl
            .with_columns([
                ((pl.col(ts_col_pl) // bucket_ms) * bucket_ms).alias('bucket_ts'),
                (pl.col('price') / tick_size).round().cast(pl.Int64).alias('price_tick'),
                pl.col('is_buyer_maker').cast(pl.UInt8).alias('side'),
            ])
            .group_by(['bucket_ts', 'price_tick', 'side'])
            .agg(pl.col(qty_col_pl).sum().alias('qty'))
        )
        results['polars_groupby_sec'] = time.perf_counter() - start
        results['polars_groupby_per_sec'] = n_rows / results['polars_groupby_sec']
        results['polars_unique_buckets'] = len(result)

    # 4. Fast aggregator (if available)
    if FAST_AGG_AVAILABLE:
        start = time.perf_counter()
        agg_result = aggregate_ticks_polars(csv_path, bucket_ms, tick_size)
        results['fast_agg_sec'] = time.perf_counter() - start
        # Note: this processes full file, not n_rows

    return results


def benchmark_tick_processing(n_ticks: int = 1_000_000) -> dict:
    """Benchmark engine tick processing"""
    if not RUST_AVAILABLE:
        return {'error': 'Rust engine not available'}

    results = {}

    # Generate synthetic data
    np.random.seed(42)
    timestamps = np.arange(n_ticks, dtype=np.int64) * 100
    price_ticks = (42000 + np.cumsum(np.random.randn(n_ticks) * 10)).astype(np.int64)
    qtys = np.abs(np.random.randn(n_ticks) * 0.1 + 0.05)
    sides = np.random.randint(0, 2, n_ticks, dtype=np.uint8)

    config = EngineConfig(
        initial_cash=100_000.0,
        maker_fee=0.0001,
        taker_fee=0.0002,
        tick_size=0.1
    )

    # 1. Single tick mode (sample for speed)
    engine = Engine(config)
    sample_ticks = 10000
    start = time.perf_counter()
    for i in range(sample_ticks):
        tick = Tick(
            ts_ms=int(timestamps[i]),
            price_tick_i64=int(price_ticks[i]),
            qty=float(qtys[i]),
            side='BUY' if sides[i] == 0 else 'SELL'
        )
        engine.step_tick(tick)
    elapsed = time.perf_counter() - start
    results['single_tick_per_sec'] = sample_ticks / elapsed

    # 2. Batch mode (full)
    engine = Engine(config)
    start = time.perf_counter()
    engine.step_batch(
        timestamps.tolist(),
        price_ticks.tolist(),
        qtys.tolist(),
        sides.tolist()
    )
    elapsed = time.perf_counter() - start
    results['batch_ticks_per_sec'] = n_ticks / elapsed
    results['batch_total_sec'] = elapsed
    results['batch_ticks_processed'] = n_ticks

    # 3. Batch with periodic orders
    engine = Engine(config)
    order_interval = 10000
    start = time.perf_counter()
    for i in range(0, n_ticks, order_interval):
        chunk_end = min(i + order_interval, n_ticks)
        engine.step_batch(
            timestamps[i:chunk_end].tolist(),
            price_ticks[i:chunk_end].tolist(),
            qtys[i:chunk_end].tolist(),
            sides[i:chunk_end].tolist()
        )
        if i + order_interval < n_ticks:
            engine.place_order(Order(order_type='MARKET', side='BUY', qty=0.001))
    elapsed = time.perf_counter() - start
    results['batch_with_orders_per_sec'] = n_ticks / elapsed

    # 4. Try numpy batch if available
    try:
        engine = Engine(config)
        if hasattr(engine._core, 'step_batch_numpy'):
            start = time.perf_counter()
            engine._core.step_batch_numpy(timestamps, price_ticks, qtys, sides)
            elapsed = time.perf_counter() - start
            results['numpy_batch_per_sec'] = n_ticks / elapsed
    except Exception:
        pass

    # Final state
    snap = engine.get_snapshot()
    # Handle both dict (raw Rust) and Snapshot (wrapped) access
    results['final_equity'] = snap.equity if hasattr(snap, 'equity') else snap['equity']

    return results


def benchmark_analytics(n_ticks: int = 500_000) -> dict:
    """Benchmark analytics functions"""
    if not ANALYTICS_AVAILABLE:
        return {'error': 'Analytics module not available'}

    results = {}

    # Generate test data
    np.random.seed(42)
    timestamps = np.arange(n_ticks, dtype=np.int64) * 100
    prices = 42000 + np.cumsum(np.random.randn(n_ticks) * 10)
    price_ticks = prices.astype(np.int64)
    qtys = np.abs(np.random.randn(n_ticks) * 0.1 + 0.05)
    sides = np.random.randint(0, 2, n_ticks, dtype=np.uint8)

    # 1. Candle generation
    start = time.perf_counter()
    candles = ticks_to_candles(timestamps, price_ticks, qtys, sides, tick_size=1.0, interval_ms=60000)
    results['candles_generation_sec'] = time.perf_counter() - start
    results['candles_generated'] = len(candles['ts_open'])
    results['candles_per_sec'] = n_ticks / results['candles_generation_sec']

    # 2. VWAP calculation
    start = time.perf_counter()
    vwap = calculate_vwap(prices, qtys)
    results['vwap_calculation_sec'] = time.perf_counter() - start

    # 3. Volume profile
    start = time.perf_counter()
    profile = calculate_volume_profile(price_ticks, qtys, sides, n_bins=100)
    results['volume_profile_sec'] = time.perf_counter() - start

    # 4. Realized volatility
    start = time.perf_counter()
    vol = calculate_realized_volatility(prices, window=100)
    results['volatility_calculation_sec'] = time.perf_counter() - start

    return results


def run_all_benchmarks(data_path: str, output_path: str, baseline_path: Optional[str] = None):
    """Run all benchmarks and save results"""

    print("=" * 70)
    print("AG-KERNEL v0.3.0 PERFORMANCE BENCHMARK")
    print("=" * 70)
    print(f"Data: {data_path}")
    print(f"Time: {datetime.now().isoformat()}")
    print()

    # Load baseline for comparison
    baseline = None
    if baseline_path and Path(baseline_path).exists():
        with open(baseline_path) as f:
            baseline = json.load(f)
        print(f"Baseline loaded from: {baseline_path}")
        print()

    results = {
        'timestamp': datetime.now().isoformat(),
        'data_file': data_path,
        'version': 'v0.3.0-optimized',
    }

    # Data loading benchmarks
    print(">>> Benchmarking data loading...")
    try:
        results['data_loading'] = benchmark_data_loading(data_path, n_rows=1_000_000)
        print(f"    Pandas read: {results['data_loading']['pandas_read_csv_sec']:.2f}s")
        print(f"    Vectorized: {results['data_loading']['vectorized_rows_per_sec']:.0f} rows/sec")
        if 'polars_rows_per_sec' in results['data_loading']:
            print(f"    Polars: {results['data_loading']['polars_rows_per_sec']:.0f} rows/sec")
    except Exception as e:
        results['data_loading'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Aggregation benchmarks
    print(">>> Benchmarking aggregation...")
    try:
        results['aggregation'] = benchmark_aggregation(data_path, n_rows=1_000_000)
        print(f"    Python dict: {results['aggregation']['python_dict_per_sec']:.0f} rows/sec")
        print(f"    Pandas groupby: {results['aggregation']['pandas_groupby_per_sec']:.0f} rows/sec")
        if 'polars_groupby_per_sec' in results['aggregation']:
            print(f"    Polars groupby: {results['aggregation']['polars_groupby_per_sec']:.0f} rows/sec")

        # Show improvement
        if baseline and 'aggregation' in baseline:
            old_pandas = baseline['aggregation'].get('pandas_groupby_per_sec', 0)
            new_pandas = results['aggregation'].get('pandas_groupby_per_sec', 0)
            if old_pandas > 0:
                print(f"    Pandas improvement: {new_pandas/old_pandas:.1f}x")
    except Exception as e:
        results['aggregation'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Tick processing benchmarks
    print(">>> Benchmarking tick processing (1M ticks)...")
    try:
        results['tick_processing'] = benchmark_tick_processing(n_ticks=1_000_000)
        if 'error' not in results['tick_processing']:
            print(f"    Single tick: {results['tick_processing']['single_tick_per_sec']:.0f} ticks/sec")
            print(f"    Batch mode: {results['tick_processing']['batch_ticks_per_sec']:.0f} ticks/sec")
            print(f"    Batch+orders: {results['tick_processing']['batch_with_orders_per_sec']:.0f} ticks/sec")
            if 'numpy_batch_per_sec' in results['tick_processing']:
                print(f"    NumPy batch: {results['tick_processing']['numpy_batch_per_sec']:.0f} ticks/sec")

            # Million ticks per second?
            batch_speed = results['tick_processing']['batch_ticks_per_sec']
            if batch_speed >= 1_000_000:
                print(f"    🚀 {batch_speed/1_000_000:.1f}M ticks/sec achieved!")
        else:
            print(f"    SKIPPED: {results['tick_processing']['error']}")
    except Exception as e:
        results['tick_processing'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Analytics benchmarks
    print(">>> Benchmarking analytics...")
    try:
        results['analytics'] = benchmark_analytics(n_ticks=500_000)
        if 'error' not in results['analytics']:
            print(f"    Candle generation: {results['analytics']['candles_per_sec']:.0f} ticks/sec")
            print(f"    VWAP: {results['analytics']['vwap_calculation_sec']*1000:.1f}ms for 500k ticks")
            print(f"    Volume profile: {results['analytics']['volume_profile_sec']*1000:.1f}ms")
            print(f"    Volatility: {results['analytics']['volatility_calculation_sec']*1000:.1f}ms")
        else:
            print(f"    SKIPPED: {results['analytics']['error']}")
    except Exception as e:
        results['analytics'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Summary comparison with baseline
    if baseline:
        print("=" * 70)
        print("IMPROVEMENT SUMMARY (vs baseline)")
        print("=" * 70)

        # Tick processing improvement
        if 'tick_processing' in baseline and 'error' not in baseline['tick_processing']:
            if 'tick_processing' in results and 'error' not in results['tick_processing']:
                old_batch = baseline['tick_processing'].get('batch_ticks_per_sec', 1)
                new_batch = results['tick_processing'].get('batch_ticks_per_sec', 1)
                print(f"    Batch processing: {new_batch/old_batch:.1f}x faster")

        # Aggregation improvement
        if 'aggregation' in baseline:
            old_dict = baseline['aggregation'].get('python_dict_agg_per_sec', 1)
            new_polars = results['aggregation'].get('polars_groupby_per_sec', 1)
            print(f"    Aggregation: {new_polars/old_dict:.1f}x faster (Polars vs Python dict)")

        print()

    # Save results
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print("=" * 70)
    print(f"Results saved to: {output_path}")
    print("=" * 70)

    return results


if __name__ == '__main__':
    data_path = str(Path(__file__).parent.parent / "benchmark_data" / "BTCUSDT-aggTrades-2024-01.csv")
    output_path = str(Path(__file__).parent / "results" / "final.json")
    baseline_path = str(Path(__file__).parent / "results" / "baseline.json")

    if not Path(data_path).exists():
        print(f"Data file not found: {data_path}")
        print("Please download from https://data.binance.vision/")
        sys.exit(1)

    run_all_benchmarks(data_path, output_path, baseline_path)
