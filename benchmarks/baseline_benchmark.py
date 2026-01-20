#!/usr/bin/env python3
"""
Baseline benchmark script for ag-kernel performance testing.
Run BEFORE optimizations to establish baseline metrics.
"""

import time
import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import numpy as np
import pandas as pd

# Try to import the engine
try:
    from ag_backtester import Engine, EngineConfig, SIDE_BUY, SIDE_SELL
    from ag_backtester.engine import Tick, Order
    RUST_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Rust engine not available: {e}")
    RUST_AVAILABLE = False


def benchmark_data_loading(csv_path: str, n_rows: int = 1_000_000) -> dict:
    """Benchmark data loading methods"""
    results = {}

    # 1. Pandas read_csv
    start = time.perf_counter()
    df = pd.read_csv(csv_path, nrows=n_rows)
    results['pandas_read_csv_sec'] = time.perf_counter() - start
    results['rows_loaded'] = len(df)

    # 2. Pandas iterrows (sample 10k rows)
    sample_df = df.head(10000)
    start = time.perf_counter()
    count = 0
    for _, row in sample_df.iterrows():
        _ = row['price']
        count += 1
    elapsed = time.perf_counter() - start
    results['pandas_iterrows_per_sec'] = count / elapsed

    # 3. Numpy vectorized access
    start = time.perf_counter()
    prices = df['price'].values
    qtys = df['quantity'].values
    times = df['transact_time'].values
    sides = df['is_buyer_maker'].values
    results['numpy_vectorized_sec'] = time.perf_counter() - start

    # 4. Calculate ticks per second potential
    results['vectorized_rows_per_sec'] = n_rows / results['numpy_vectorized_sec']

    return results


def benchmark_tick_processing(n_ticks: int = 100_000) -> dict:
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

    # 1. Single tick mode
    engine = Engine(config)
    start = time.perf_counter()
    for i in range(min(n_ticks, 10000)):  # Sample for single tick
        tick = Tick(
            ts_ms=int(timestamps[i]),
            price_tick_i64=int(price_ticks[i]),
            qty=float(qtys[i]),
            side='BUY' if sides[i] == 0 else 'SELL'
        )
        engine.step_tick(tick)
    elapsed = time.perf_counter() - start
    results['single_tick_per_sec'] = 10000 / elapsed

    # 2. Batch mode
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

    # 3. Batch with orders (every 1000 ticks place an order)
    engine = Engine(config)
    start = time.perf_counter()
    for i in range(0, n_ticks, 1000):
        chunk_end = min(i + 1000, n_ticks)
        engine.step_batch(
            timestamps[i:chunk_end].tolist(),
            price_ticks[i:chunk_end].tolist(),
            qtys[i:chunk_end].tolist(),
            sides[i:chunk_end].tolist()
        )
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=0.001))
    elapsed = time.perf_counter() - start
    results['batch_with_orders_per_sec'] = n_ticks / elapsed

    # Get final state
    snap = engine.get_snapshot()
    results['final_equity'] = snap['equity']

    return results


def benchmark_aggregation(csv_path: str, n_rows: int = 1_000_000) -> dict:
    """Benchmark tick aggregation"""
    results = {}

    # Load data
    df = pd.read_csv(csv_path, nrows=n_rows)

    # 1. Python dict-based aggregation (current method)
    start = time.perf_counter()
    buckets = {}
    bucket_ms = 1000
    tick_size = 0.1

    for i in range(min(len(df), 100000)):  # Sample
        row = df.iloc[i]
        ts = int(row['transact_time'])
        bucket_ts = (ts // bucket_ms) * bucket_ms
        price_tick = round(row['price'] / tick_size)
        side = 'SELL' if row['is_buyer_maker'] else 'BUY'
        key = (bucket_ts, price_tick, side)
        buckets[key] = buckets.get(key, 0) + row['quantity']

    elapsed = time.perf_counter() - start
    results['python_dict_agg_per_sec'] = 100000 / elapsed

    # 2. Pandas groupby
    df['bucket_ts'] = (df['transact_time'] // bucket_ms) * bucket_ms
    df['price_tick'] = (df['price'] / tick_size).round().astype(int)
    df['side'] = np.where(df['is_buyer_maker'], 'SELL', 'BUY')

    start = time.perf_counter()
    agg = df.groupby(['bucket_ts', 'price_tick', 'side'])['quantity'].sum()
    elapsed = time.perf_counter() - start
    results['pandas_groupby_sec'] = elapsed
    results['pandas_groupby_per_sec'] = n_rows / elapsed
    results['unique_buckets'] = len(agg)

    return results


def run_all_benchmarks(data_path: str, output_path: str):
    """Run all benchmarks and save results"""

    print("=" * 60)
    print("AG-KERNEL BASELINE BENCHMARK")
    print("=" * 60)
    print(f"Data: {data_path}")
    print(f"Time: {datetime.now().isoformat()}")
    print()

    results = {
        'timestamp': datetime.now().isoformat(),
        'data_file': data_path,
        'version': 'baseline',
    }

    # Data loading benchmarks
    print(">>> Benchmarking data loading...")
    try:
        results['data_loading'] = benchmark_data_loading(data_path, n_rows=1_000_000)
        print(f"    Pandas read: {results['data_loading']['pandas_read_csv_sec']:.2f}s for 1M rows")
        print(f"    iterrows: {results['data_loading']['pandas_iterrows_per_sec']:.0f} rows/sec")
        print(f"    Vectorized: {results['data_loading']['vectorized_rows_per_sec']:.0f} rows/sec")
    except Exception as e:
        results['data_loading'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Tick processing benchmarks
    print(">>> Benchmarking tick processing...")
    try:
        results['tick_processing'] = benchmark_tick_processing(n_ticks=100_000)
        if 'error' not in results['tick_processing']:
            print(f"    Single tick: {results['tick_processing']['single_tick_per_sec']:.0f} ticks/sec")
            print(f"    Batch mode: {results['tick_processing']['batch_ticks_per_sec']:.0f} ticks/sec")
            print(f"    Batch+orders: {results['tick_processing']['batch_with_orders_per_sec']:.0f} ticks/sec")
        else:
            print(f"    SKIPPED: {results['tick_processing']['error']}")
    except Exception as e:
        results['tick_processing'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Aggregation benchmarks
    print(">>> Benchmarking aggregation...")
    try:
        results['aggregation'] = benchmark_aggregation(data_path, n_rows=1_000_000)
        print(f"    Python dict: {results['aggregation']['python_dict_agg_per_sec']:.0f} rows/sec")
        print(f"    Pandas groupby: {results['aggregation']['pandas_groupby_per_sec']:.0f} rows/sec")
    except Exception as e:
        results['aggregation'] = {'error': str(e)}
        print(f"    ERROR: {e}")
    print()

    # Save results
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print("=" * 60)
    print(f"Results saved to: {output_path}")
    print("=" * 60)

    return results


if __name__ == '__main__':
    data_path = str(Path(__file__).parent.parent / "benchmark_data" / "BTCUSDT-aggTrades-2024-01.csv")
    output_path = str(Path(__file__).parent / "results" / "baseline.json")

    if not Path(data_path).exists():
        print(f"Data file not found: {data_path}")
        print("Please download from https://data.binance.vision/")
        sys.exit(1)

    run_all_benchmarks(data_path, output_path)
