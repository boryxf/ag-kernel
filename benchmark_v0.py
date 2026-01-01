#!/usr/bin/env python3
"""
AG-Backtester Performance Benchmark (v0.2)

Compares three implementations on the same 1M tick dataset:
1. Pure Python (baseline)
2. Naive PyO3 (single-tick FFI calls)
3. AG-Backtester Batch (optimized batch processing with Parquet)

Usage:
    python3 benchmark_v0.py
"""

import time
import sys
from pathlib import Path
import numpy as np

# Add python package to path
sys.path.insert(0, str(Path(__file__).parent / "python"))

from ag_backtester import Engine, EngineConfig, SIDE_BUY, SIDE_SELL
from ag_backtester.engine import Tick
from ag_backtester.data.converter import convert_to_parquet, load_dataset


def format_number(n):
    """Format large numbers with commas"""
    return f"{n:,}"


def format_throughput(ticks_per_sec):
    """Format throughput in human-readable form"""
    if ticks_per_sec >= 1_000_000:
        return f"{ticks_per_sec / 1_000_000:.2f}M ticks/s"
    elif ticks_per_sec >= 1_000:
        return f"{ticks_per_sec / 1_000:.1f}K ticks/s"
    else:
        return f"{ticks_per_sec:.0f} ticks/s"


def generate_synthetic_data(n_ticks=1_000_000, seed=42):
    """Generate synthetic tick data for benchmarking"""
    np.random.seed(seed)

    # Random walk around 42000 (BTC price)
    base_price = 42000.0
    price_changes = np.random.normal(0, 5, n_ticks)
    prices = base_price + np.cumsum(price_changes)

    # Random quantities (exponential distribution)
    qtys = np.random.exponential(0.05, n_ticks)

    # Random sides (50/50 buy/sell)
    sides = np.random.randint(0, 2, n_ticks, dtype=np.uint8)

    # Timestamps (1ms intervals starting from arbitrary time)
    start_ts = 1609459200000  # 2021-01-01 00:00:00 UTC
    timestamps = np.arange(start_ts, start_ts + n_ticks, dtype=np.int64)

    return {
        'timestamp': timestamps,
        'price': prices,
        'qty': qtys,
        'side': sides
    }


def benchmark_pure_python(data, tick_size=10.0):
    """Baseline: Pure Python implementation (no Rust FFI)"""
    print("\n[1/3] Running Pure Python baseline...")

    # Simple state tracking
    cash = 100_000.0
    position = 0.0

    start = time.perf_counter()

    for i in range(len(data['timestamp'])):
        # Simulate some basic processing
        price = data['price'][i]
        qty = data['qty'][i]
        side = data['side'][i]

        # Simple state update (not full engine logic, just representative work)
        if side == SIDE_BUY:
            position += qty * 0.0001  # Arbitrary small factor
        else:
            position -= qty * 0.0001

    elapsed = time.perf_counter() - start
    ticks_per_sec = len(data['timestamp']) / elapsed

    return elapsed, ticks_per_sec


def benchmark_naive_pyo3(data, tick_size=10.0):
    """Naive PyO3: Single-tick FFI calls (simulating v0.1 approach)"""
    print("\n[2/3] Running Naive PyO3 (single-tick FFI)...")

    config = EngineConfig(
        initial_cash=100_000.0,
        tick_size=tick_size,
    )
    engine = Engine(config)

    # Check if Rust core is available
    if engine._core is None:
        print("  ⚠️  Rust core not available, using Python stub (results may vary)")

    start = time.perf_counter()

    # Process ticks one by one (FFI overhead for each call)
    for i in range(len(data['timestamp'])):
        tick = Tick(
            ts_ms=int(data['timestamp'][i]),
            price_tick_i64=int(data['price'][i] / tick_size),
            qty=float(data['qty'][i]),
            side='BUY' if data['side'][i] == SIDE_BUY else 'SELL'
        )
        engine.step_tick(tick)

    elapsed = time.perf_counter() - start
    ticks_per_sec = len(data['timestamp']) / elapsed

    return elapsed, ticks_per_sec


def benchmark_batch_mode(data, tick_size=10.0):
    """Optimized: Batch processing with step_batch (v0.2)"""
    print("\n[3/3] Running AG-Backtester Batch mode...")

    config = EngineConfig(
        initial_cash=100_000.0,
        tick_size=tick_size,
    )
    engine = Engine(config)

    # Check if Rust core is available
    if engine._core is None:
        print("  ⚠️  Rust core not available, using Python stub (results may vary)")

    # Convert prices to price ticks
    price_ticks = (data['price'] / tick_size).astype(np.int64)

    start = time.perf_counter()

    # Process all ticks in batch (loop inside Rust)
    engine.step_batch(
        timestamps=data['timestamp'],
        price_ticks=price_ticks,
        qtys=data['qty'],
        sides=data['side']
    )

    elapsed = time.perf_counter() - start
    ticks_per_sec = len(data['timestamp']) / elapsed

    return elapsed, ticks_per_sec


def print_results(results, n_ticks):
    """Print benchmark results in a formatted table"""
    print("\n" + "="*80)
    print("BENCHMARK RESULTS")
    print("="*80)
    print(f"\nDataset: {format_number(n_ticks)} ticks")
    print("\n{:<30} {:>12} {:>18} {:>12}".format(
        "Implementation", "Time (s)", "Throughput", "Speedup"
    ))
    print("-" * 80)

    baseline_time = results[0][1]  # Pure Python time

    for name, elapsed, tps in results:
        speedup = baseline_time / elapsed
        print("{:<30} {:>12.3f} {:>18} {:>11.1f}x".format(
            name, elapsed, format_throughput(tps), speedup
        ))

    print("="*80)

    # Extract specific values for README
    batch_time, batch_tps = results[2][1], results[2][2]
    pyo3_time, pyo3_tps = results[1][1], results[1][2]
    python_time, python_tps = results[0][1], results[0][2]

    print("\n📋 README.md snippet:")
    print("-" * 80)
    print(f"| **AG-Backtester (Batch)** | **{batch_time:.2f}s** | "
          f"**~{int(batch_tps):,} ticks/s** | **{baseline_time/batch_time:.0f}x** 🚀 |")
    print(f"| Naive PyO3 (Single Call) | {pyo3_time:.2f}s | "
          f"~{int(pyo3_tps):,} ticks/s | {baseline_time/pyo3_time:.0f}x |")
    print(f"| Pure Python | {python_time:.2f}s | "
          f"~{int(python_tps):,} ticks/s | 1x |")
    print("-" * 80)


def main():
    print("AG-Backtester v0.2 Performance Benchmark")
    print("="*80)

    # Configuration
    n_ticks = 1_000_000
    tick_size = 10.0

    print(f"\nGenerating {format_number(n_ticks)} synthetic ticks...")
    data = generate_synthetic_data(n_ticks)
    print(f"✓ Generated {format_number(n_ticks)} ticks")

    # Run benchmarks
    results = []

    # 1. Pure Python baseline
    elapsed, tps = benchmark_pure_python(data, tick_size)
    results.append(("Pure Python (Baseline)", elapsed, tps))
    print(f"  ✓ Completed in {elapsed:.3f}s ({format_throughput(tps)})")

    # 2. Naive PyO3 (single-tick)
    elapsed, tps = benchmark_naive_pyo3(data, tick_size)
    results.append(("Naive PyO3 (Single Call)", elapsed, tps))
    print(f"  ✓ Completed in {elapsed:.3f}s ({format_throughput(tps)})")

    # 3. Batch mode
    elapsed, tps = benchmark_batch_mode(data, tick_size)
    results.append(("AG-Backtester (Batch)", elapsed, tps))
    print(f"  ✓ Completed in {elapsed:.3f}s ({format_throughput(tps)})")

    # Print results
    print_results(results, n_ticks)

    # System info
    import platform
    print(f"\n💻 System: {platform.system()} {platform.machine()}")
    print(f"   Python: {platform.python_version()}")

    # Check if using Rust core
    config = EngineConfig(initial_cash=100_000.0, tick_size=tick_size)
    engine = Engine(config)
    if engine._core is None:
        print("\n⚠️  WARNING: Rust core not available. Install with:")
        print("   maturin develop --release -m crates/ag-core/Cargo.toml")
        print("   For best performance, ensure the Rust extension is compiled.")
    else:
        print("\n✓ Rust core enabled (optimal performance)")


if __name__ == '__main__':
    main()
