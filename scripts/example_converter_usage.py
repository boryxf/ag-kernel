#!/usr/bin/env python3
"""
Example usage of the Parquet converter.

Demonstrates how to convert CSV to Parquet and load the data.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from ag_backtester.data import convert_to_parquet, load_dataset


def main():
    """Example workflow: CSV → Parquet → Load."""

    # Paths
    project_root = Path(__file__).parent.parent
    csv_path = project_root / "examples" / "data" / "btcusdt_aggtrades_sample.csv"
    parquet_path = project_root / "outputs" / "example_output.parquet"

    print("Parquet Converter Example")
    print("=" * 50)

    # Step 1: Convert CSV to Parquet
    print(f"\n1. Converting CSV to Parquet...")
    print(f"   Input:  {csv_path}")
    print(f"   Output: {parquet_path}")

    convert_to_parquet(csv_path, parquet_path, compression='zstd')
    print(f"   ✓ Conversion complete!")

    # Show file sizes
    csv_size = csv_path.stat().st_size
    parquet_size = parquet_path.stat().st_size
    reduction = (1 - parquet_size / csv_size) * 100

    print(f"\n   CSV size:     {csv_size:,} bytes")
    print(f"   Parquet size: {parquet_size:,} bytes")
    print(f"   Reduction:    {reduction:.1f}%")

    # Step 2: Load the Parquet data
    print(f"\n2. Loading Parquet dataset...")
    data = load_dataset(parquet_path)

    print(f"   ✓ Loaded {len(data['timestamp']):,} ticks")
    print(f"\n   Columns: {list(data.keys())}")
    print(f"   Data types:")
    for col, arr in data.items():
        print(f"     - {col}: {arr.dtype}")

    # Step 3: Show sample data
    print(f"\n3. Sample data (first 5 rows):")
    print(f"   {'Timestamp':<15} {'Price':<12} {'Qty':<12} {'Side'}")
    print(f"   {'-'*15} {'-'*12} {'-'*12} {'-'*4}")

    for i in range(min(5, len(data['timestamp']))):
        side_str = "SELL" if data['side'][i] == 1 else "BUY"
        print(
            f"   {data['timestamp'][i]:<15} "
            f"{data['price'][i]:<12.2f} "
            f"{data['qty'][i]:<12.6f} "
            f"{side_str}"
        )

    print("\n" + "=" * 50)
    print("Example complete!")
    print("\nNext steps:")
    print("  - Use load_dataset() in your backtesting pipeline")
    print("  - Access data as numpy arrays for maximum performance")
    print("  - Run scripts/benchmark_parquet.py for performance testing")


if __name__ == "__main__":
    main()
