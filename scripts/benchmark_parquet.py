#!/usr/bin/env python3
"""
Benchmark Parquet conversion and loading performance.

Tests:
1. CSV → Parquet conversion time
2. Parquet loading time (target: < 0.1s for 1M ticks)
3. File size comparison
4. Data integrity verification
"""

import sys
import time
from pathlib import Path

# Add parent directory to path to import ag_backtester
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from ag_backtester.data.converter import convert_to_parquet, load_dataset
import numpy as np


def format_time(seconds: float) -> str:
    """Format time in human-readable format."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f} μs"
    elif seconds < 1:
        return f"{seconds * 1_000:.2f} ms"
    else:
        return f"{seconds:.3f} s"


def format_size(bytes_size: int) -> str:
    """Format file size in human-readable format."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.2f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.2f} MB"


def verify_data_integrity(csv_path: Path, data: dict) -> bool:
    """
    Verify data integrity by comparing against original CSV.

    Returns:
        True if data matches, False otherwise
    """
    import pandas as pd

    # Read original CSV
    df_original = pd.read_csv(csv_path)

    # Check row count
    if len(df_original) != len(data['timestamp']):
        print(f"  ✗ Row count mismatch: {len(df_original)} vs {len(data['timestamp'])}")
        return False

    # Check timestamps match
    if not np.array_equal(df_original['timestamp'].values, data['timestamp']):
        print("  ✗ Timestamp mismatch")
        return False

    # Check prices match
    if not np.allclose(df_original['price'].values, data['price']):
        print("  ✗ Price mismatch")
        return False

    # Check quantities match
    if not np.allclose(df_original['qty'].values, data['qty']):
        print("  ✗ Quantity mismatch")
        return False

    # Check side conversion (is_buyer_maker -> side)
    expected_side = df_original['is_buyer_maker'].astype('uint8').values
    if not np.array_equal(expected_side, data['side']):
        print("  ✗ Side conversion mismatch")
        return False

    return True


def benchmark_single_file(csv_path: Path, output_dir: Path, compression: str = 'zstd'):
    """
    Benchmark conversion and loading for a single CSV file.

    Args:
        csv_path: Path to input CSV file
        output_dir: Directory for Parquet output
        compression: Compression codec to use
    """
    print(f"\nBenchmarking: {csv_path.name}")
    print("=" * 70)

    # Get input file size
    csv_size = csv_path.stat().st_size
    print(f"Input CSV size: {format_size(csv_size)}")

    # Output path
    parquet_path = output_dir / f"{csv_path.stem}.parquet"

    # STEP 1: Conversion
    print(f"\n1. Converting CSV → Parquet ({compression})...")
    start = time.perf_counter()
    convert_to_parquet(csv_path, parquet_path, compression=compression)
    conversion_time = time.perf_counter() - start

    parquet_size = parquet_path.stat().st_size
    size_reduction = (1 - parquet_size / csv_size) * 100

    print(f"   Conversion time: {format_time(conversion_time)}")
    print(f"   Parquet size: {format_size(parquet_size)}")
    print(f"   Size reduction: {size_reduction:.1f}%")

    # STEP 2: Loading
    print(f"\n2. Loading Parquet dataset...")
    start = time.perf_counter()
    data = load_dataset(parquet_path)
    load_time = time.perf_counter() - start

    num_ticks = len(data['timestamp'])
    ticks_per_second = num_ticks / load_time if load_time > 0 else float('inf')

    print(f"   Load time: {format_time(load_time)}")
    print(f"   Rows loaded: {num_ticks:,}")
    print(f"   Throughput: {ticks_per_second:,.0f} ticks/sec")

    # STEP 3: Performance target check
    print(f"\n3. Performance Target Check:")
    target_time = 0.1  # 100ms target for 1M ticks

    if num_ticks >= 1_000_000:
        # Normalize to 1M ticks
        normalized_time = load_time * (1_000_000 / num_ticks)
        met_target = normalized_time < target_time

        print(f"   Target: < {target_time * 1000:.0f} ms for 1M ticks")
        print(f"   Actual (normalized): {format_time(normalized_time)}")
        print(f"   Status: {'✓ PASS' if met_target else '✗ FAIL'}")
    else:
        # For smaller files, just report actual time
        print(f"   File has {num_ticks:,} ticks (< 1M)")
        print(f"   Load time: {format_time(load_time)}")

        # Estimate for 1M ticks
        estimated_time = load_time * (1_000_000 / num_ticks)
        met_target = estimated_time < target_time

        print(f"   Estimated for 1M: {format_time(estimated_time)}")
        print(f"   Status: {'✓ PASS (estimated)' if met_target else '✗ FAIL (estimated)'}")

    # STEP 4: Data integrity
    print(f"\n4. Data Integrity Check:")
    integrity_ok = verify_data_integrity(csv_path, data)

    if integrity_ok:
        print("   ✓ All data matches original CSV")
    else:
        print("   ✗ Data integrity check failed!")

    # STEP 5: Summary
    print(f"\n" + "=" * 70)
    print("SUMMARY:")
    print(f"  Conversion: {format_time(conversion_time)}")
    print(f"  Loading: {format_time(load_time)}")
    print(f"  Size reduction: {size_reduction:.1f}%")
    print(f"  Data integrity: {'✓ PASS' if integrity_ok else '✗ FAIL'}")

    return {
        'csv_size': csv_size,
        'parquet_size': parquet_size,
        'conversion_time': conversion_time,
        'load_time': load_time,
        'num_ticks': num_ticks,
        'integrity_ok': integrity_ok,
    }


def main():
    """Main benchmark function."""
    # Locate project root and sample data
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    examples_dir = project_root / "examples" / "data"

    # Try to use 1M row file if available, otherwise fall back to sample
    test_csv = examples_dir / "btcusdt_aggtrades_1m.csv"
    if not test_csv.exists():
        test_csv = examples_dir / "btcusdt_aggtrades_sample.csv"
        print("Note: Using small sample file. For accurate benchmarking, generate 1M rows:")
        print("  python scripts/generate_test_data.py\n")

    # Check if file exists
    if not test_csv.exists():
        print(f"Error: CSV file not found at {test_csv}")
        print("Please ensure the examples/data/ directory contains test data.")
        sys.exit(1)

    # Create output directory
    output_dir = project_root / "outputs" / "parquet_benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║          Parquet Conversion & Loading Benchmark                  ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")

    # Test with different compression codecs
    compressions = ['zstd', 'snappy', None]
    results = {}

    for compression in compressions:
        compression_name = compression or 'none'
        results[compression_name] = benchmark_single_file(
            test_csv,
            output_dir,
            compression=compression
        )

    # COMPARISON
    print("\n\n" + "=" * 70)
    print("COMPRESSION COMPARISON:")
    print("=" * 70)
    print(f"{'Codec':<10} {'Size':<12} {'Reduction':<12} {'Load Time':<15}")
    print("-" * 70)

    for compression_name, result in results.items():
        size_reduction = (1 - result['parquet_size'] / result['csv_size']) * 100
        print(
            f"{compression_name:<10} "
            f"{format_size(result['parquet_size']):<12} "
            f"{size_reduction:>5.1f}%{'':6} "
            f"{format_time(result['load_time']):<15}"
        )

    print("\n" + "=" * 70)
    print("Benchmark complete! Parquet files saved to:")
    print(f"  {output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
