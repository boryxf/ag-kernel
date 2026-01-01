#!/usr/bin/env python3
"""
Generate synthetic aggTrades data for benchmarking.

Creates a CSV file with 1M+ rows to properly test Parquet performance.
"""

import sys
from pathlib import Path
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def generate_test_csv(output_path: Path, num_rows: int = 1_000_000):
    """
    Generate synthetic aggTrades CSV data.

    Args:
        output_path: Path to output CSV file
        num_rows: Number of rows to generate
    """
    print(f"Generating {num_rows:,} rows of synthetic aggTrades data...")

    # Set random seed for reproducibility
    np.random.seed(42)

    # Generate timestamps (50ms intervals)
    start_ts = 1704067200000  # 2024-01-01 00:00:00 UTC
    timestamps = start_ts + np.arange(num_rows) * 50

    # Generate realistic price data (random walk around 42000)
    price_changes = np.random.randn(num_rows) * 10
    prices = 42000 + np.cumsum(price_changes)

    # Generate quantities (exponential distribution, mostly small)
    qtys = np.random.exponential(0.05, num_rows)

    # Generate sides (roughly 50/50)
    is_buyer_maker = np.random.choice([True, False], size=num_rows)

    # Write to CSV
    print(f"Writing to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        # Header
        f.write("timestamp,price,qty,is_buyer_maker\n")

        # Write in chunks for efficiency
        chunk_size = 10000
        for i in range(0, num_rows, chunk_size):
            end_idx = min(i + chunk_size, num_rows)
            for j in range(i, end_idx):
                f.write(f"{timestamps[j]},{prices[j]:.2f},{qtys[j]:.6f},{str(is_buyer_maker[j]).lower()}\n")

            if (i + chunk_size) % 100000 == 0:
                print(f"  Written {i + chunk_size:,} rows...")

    file_size = output_path.stat().st_size
    file_size_mb = file_size / (1024 * 1024)
    print(f"Complete! File size: {file_size_mb:.2f} MB")


def main():
    """Generate test data files."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    output_dir = project_root / "examples" / "data"

    # Generate 1M row test file
    output_path = output_dir / "btcusdt_aggtrades_1m.csv"
    generate_test_csv(output_path, num_rows=1_000_000)

    print("\nTest data generation complete!")
    print(f"Output file: {output_path}")


if __name__ == "__main__":
    main()
