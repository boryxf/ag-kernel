"""
Parquet converter for high-performance data loading.

Converts CSV aggTrades to optimized Parquet format with ~50-80% size reduction
and sub-100ms loading times for 1M+ ticks.
"""

import os
from pathlib import Path
from typing import Union
import numpy as np

# Try to import polars (preferred), fall back to pandas
try:
    import polars as pl
    HAS_POLARS = True
except ImportError:
    import pandas as pd
    HAS_POLARS = False


def convert_to_parquet(
    input_csv: Union[str, Path],
    output_parquet: Union[str, Path],
    compression: str = 'zstd'
) -> None:
    """
    Convert aggTrades CSV to optimized Parquet format.

    Input CSV columns:
        - timestamp: Unix timestamp in milliseconds
        - price: Trade price (float)
        - qty: Trade quantity (float)
        - is_buyer_maker: Boolean (1/0 or True/False)

    Output Parquet schema:
        - timestamp: Int64 (Unix MS)
        - price: Float64
        - qty: Float64
        - side: Int8 (0=BUY, 1=SELL) - converted from is_buyer_maker

    Args:
        input_csv: Path to input CSV file
        output_parquet: Path to output Parquet file
        compression: Compression codec ('zstd', 'snappy', 'gzip', or None)

    Raises:
        FileNotFoundError: If input CSV doesn't exist
        ValueError: If CSV is missing required columns
    """
    input_path = Path(input_csv)
    output_path = Path(output_parquet)

    # Validate input file exists
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get file size for progress bar decision
    file_size_mb = input_path.stat().st_size / (1024 * 1024)

    if HAS_POLARS:
        _convert_with_polars(input_path, output_path, compression, file_size_mb)
    else:
        _convert_with_pandas(input_path, output_path, compression, file_size_mb)


def _convert_with_polars(
    input_path: Path,
    output_path: Path,
    compression: str,
    file_size_mb: float
) -> None:
    """Convert using polars (preferred for performance)."""

    # Read CSV with explicit schema for efficiency
    try:
        df = pl.read_csv(
            input_path,
            schema={
                'timestamp': pl.Int64,
                'price': pl.Float64,
                'qty': pl.Float64,
                'is_buyer_maker': pl.Boolean
            }
        )
    except Exception as e:
        # Fallback to inferred schema if explicit fails
        df = pl.read_csv(input_path)

        # Validate required columns
        required_cols = {'timestamp', 'price', 'qty', 'is_buyer_maker'}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            raise ValueError(
                f"Missing required columns: {missing_cols}. "
                f"Found columns: {df.columns}"
            )

    num_rows = len(df)

    # Show progress for large files
    if num_rows > 1_000_000:
        print(f"Converting {num_rows:,} rows from CSV to Parquet...")

    # Convert is_buyer_maker to side (Int8)
    # is_buyer_maker=True -> SELL (1), is_buyer_maker=False -> BUY (0)
    df = df.with_columns([
        pl.col('is_buyer_maker').cast(pl.Int8).alias('side')
    ])

    # Drop the original column
    df = df.drop('is_buyer_maker')

    # Ensure correct data types
    df = df.with_columns([
        pl.col('timestamp').cast(pl.Int64),
        pl.col('price').cast(pl.Float64),
        pl.col('qty').cast(pl.Float64),
        pl.col('side').cast(pl.Int8)
    ])

    # Write to Parquet with compression
    df.write_parquet(
        output_path,
        compression=compression,
        statistics=True,
        use_pyarrow=True
    )

    if num_rows > 1_000_000:
        output_size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Conversion complete: {output_size_mb:.2f} MB")


def _convert_with_pandas(
    input_path: Path,
    output_path: Path,
    compression: str,
    file_size_mb: float
) -> None:
    """Convert using pandas (fallback if polars not available)."""

    # Read CSV
    df = pd.read_csv(input_path)

    # Validate required columns
    required_cols = {'timestamp', 'price', 'qty', 'is_buyer_maker'}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"Missing required columns: {missing_cols}. "
            f"Found columns: {list(df.columns)}"
        )

    num_rows = len(df)

    # Show progress for large files
    if num_rows > 1_000_000:
        print(f"Converting {num_rows:,} rows from CSV to Parquet...")

    # Convert is_buyer_maker to side (int8)
    # is_buyer_maker=True -> SELL (1), is_buyer_maker=False -> BUY (0)
    df['side'] = df['is_buyer_maker'].astype('int8')
    df = df.drop(columns=['is_buyer_maker'])

    # Ensure correct data types
    df['timestamp'] = df['timestamp'].astype('int64')
    df['price'] = df['price'].astype('float64')
    df['qty'] = df['qty'].astype('float64')

    # Write to Parquet
    df.to_parquet(
        output_path,
        compression=compression,
        engine='pyarrow',
        index=False
    )

    if num_rows > 1_000_000:
        output_size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Conversion complete: {output_size_mb:.2f} MB")


def load_dataset(
    parquet_path: Union[str, Path]
) -> dict[str, np.ndarray]:
    """
    Load Parquet dataset into Struct-of-Arrays format.

    Returns:
        Dictionary with numpy arrays:
        {
            'timestamp': np.array(dtype=int64),
            'price': np.array(dtype=float64),
            'qty': np.array(dtype=float64),
            'side': np.array(dtype=uint8)  # 0=BUY, 1=SELL
        }

    Raises:
        FileNotFoundError: If Parquet file doesn't exist
    """
    parquet_path = Path(parquet_path)

    # Validate file exists
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    # Check file size for memory mapping decision
    file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
    use_memory_map = file_size_mb > 100

    if HAS_POLARS:
        return _load_with_polars(parquet_path, use_memory_map)
    else:
        return _load_with_pandas(parquet_path, use_memory_map)


def _load_with_polars(parquet_path: Path, use_memory_map: bool) -> dict[str, np.ndarray]:
    """Load using polars (preferred for performance)."""

    # Read Parquet file
    df = pl.read_parquet(
        parquet_path,
        memory_map=use_memory_map
    )

    # Convert to numpy arrays (zero-copy when possible)
    result = {
        'timestamp': df['timestamp'].to_numpy().astype(np.int64),
        'price': df['price'].to_numpy().astype(np.float64),
        'qty': df['qty'].to_numpy().astype(np.float64),
        'side': df['side'].to_numpy().astype(np.uint8)
    }

    return result


def _load_with_pandas(parquet_path: Path, use_memory_map: bool) -> dict[str, np.ndarray]:
    """Load using pandas (fallback if polars not available)."""

    # Read Parquet file
    df = pd.read_parquet(
        parquet_path,
        engine='pyarrow'
    )

    # Convert to numpy arrays
    result = {
        'timestamp': df['timestamp'].to_numpy().astype(np.int64),
        'price': df['price'].to_numpy().astype(np.float64),
        'qty': df['qty'].to_numpy().astype(np.float64),
        'side': df['side'].to_numpy().astype(np.uint8)
    }

    return result
