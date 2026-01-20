"""
Ultra-fast tick aggregation using Polars.

Provides ~10-50x faster tick aggregation compared to Python dict-based aggregation
by leveraging Polars' lazy evaluation and vectorized operations.
"""

import numpy as np
from pathlib import Path
from typing import Tuple, Union

try:
    import polars as pl
    HAS_POLARS = True
except ImportError:
    HAS_POLARS = False

# Column name mappings for different CSV formats
TIMESTAMP_COLS = ['transact_time', 'timestamp']
QUANTITY_COLS = ['quantity', 'qty']


def _detect_columns_polars(schema: dict) -> Tuple[str, str]:
    """
    Detect the correct column names for timestamp and quantity.

    Args:
        schema: Polars schema dictionary

    Returns:
        Tuple of (timestamp_col, quantity_col)

    Raises:
        ValueError: If required columns are not found
    """
    columns = list(schema.keys())
    columns_set = set(columns)

    # Find timestamp column
    ts_col = None
    for col in TIMESTAMP_COLS:
        if col in columns_set:
            ts_col = col
            break

    # Find quantity column
    qty_col = None
    for col in QUANTITY_COLS:
        if col in columns_set:
            qty_col = col
            break

    if ts_col is None:
        raise ValueError(
            f"Missing timestamp column. Expected one of {TIMESTAMP_COLS}, "
            f"found columns: {columns}"
        )

    if qty_col is None:
        raise ValueError(
            f"Missing quantity column. Expected one of {QUANTITY_COLS}, "
            f"found columns: {columns}"
        )

    return ts_col, qty_col


def aggregate_ticks_polars(
    csv_path: Union[str, Path],
    bucket_ms: int = 1000,
    tick_size: float = 0.1,
) -> "pl.DataFrame":
    """
    Ultra-fast tick aggregation using Polars.

    Aggregates raw aggTrades into time-bucketed volumes per (bucket_ts, price_tick, side).
    Uses Polars' lazy evaluation for optimal performance (~10-50x faster than Python dicts).

    Args:
        csv_path: Path to CSV file with aggTrades data
        bucket_ms: Time bucket size in milliseconds (e.g., 1000 for 1s buckets)
        tick_size: Price tick size for quantization

    Returns:
        Polars DataFrame with columns:
        - bucket_ts: int64, bucketed timestamp
        - price_tick: int64, quantized price level
        - side: int8 (0=BUY, 1=SELL)
        - qty: float64, accumulated quantity

    Raises:
        ImportError: If Polars is not installed
        FileNotFoundError: If CSV file doesn't exist
        ValueError: If required columns are missing

    Example:
        >>> df = aggregate_ticks_polars('trades.csv', bucket_ms=1000, tick_size=0.01)
        >>> print(df.head())
    """
    if not HAS_POLARS:
        raise ImportError(
            "Polars is required for fast aggregation. "
            "Install with: pip install polars"
        )

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Use lazy evaluation for optimal performance
    lf = pl.scan_csv(csv_path)

    # Detect column names from schema
    schema = lf.collect_schema()
    ts_col, qty_col = _detect_columns_polars(schema)

    # Perform aggregation using lazy evaluation
    result = (
        lf
        .with_columns([
            # Bucket timestamp
            ((pl.col(ts_col) // bucket_ms) * bucket_ms).alias('bucket_ts'),
            # Quantize price to tick level
            (pl.col('price') / tick_size).round().cast(pl.Int64).alias('price_tick'),
            # Convert is_buyer_maker to side (0=BUY, 1=SELL)
            pl.when(pl.col('is_buyer_maker'))
              .then(pl.lit(1))  # SELL
              .otherwise(pl.lit(0))  # BUY
              .cast(pl.Int8)
              .alias('side'),
        ])
        # Group by bucket and aggregate quantities
        .group_by(['bucket_ts', 'price_tick', 'side'])
        .agg(pl.col(qty_col).sum().alias('qty'))
        # Sort for deterministic output
        .sort(['bucket_ts', 'price_tick', 'side'])
        # Execute the lazy plan
        .collect()
    )

    return result


def aggregate_to_numpy(
    csv_path: Union[str, Path],
    bucket_ms: int = 1000,
    tick_size: float = 0.1,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Aggregate ticks and return as numpy arrays ready for engine.step_batch().

    This is the recommended interface for feeding aggregated data directly
    to the backtesting engine.

    Args:
        csv_path: Path to CSV file with aggTrades data
        bucket_ms: Time bucket size in milliseconds (e.g., 1000 for 1s buckets)
        tick_size: Price tick size for quantization

    Returns:
        Tuple of (bucket_ts, price_ticks, qtys, sides) as numpy arrays:
        - bucket_ts: int64 array of bucketed timestamps
        - price_ticks: int64 array of quantized price levels
        - qtys: float64 array of accumulated quantities
        - sides: uint8 array where 0=BUY, 1=SELL

    Example:
        >>> ts, ticks, qtys, sides = aggregate_to_numpy('trades.csv', 1000, 0.01)
        >>> engine.step_batch(ts, ticks, qtys, sides)
    """
    df = aggregate_ticks_polars(csv_path, bucket_ms, tick_size)

    return (
        df['bucket_ts'].to_numpy().astype(np.int64),
        df['price_tick'].to_numpy().astype(np.int64),
        df['qty'].to_numpy().astype(np.float64),
        df['side'].to_numpy().astype(np.uint8),
    )


def convert_aggtrades_to_parquet(
    csv_path: Union[str, Path],
    parquet_path: Union[str, Path],
    compression: str = 'zstd',
) -> None:
    """
    Convert aggTrades CSV to optimized Parquet format.

    Uses Polars' streaming sink for memory-efficient conversion of large files.

    Args:
        csv_path: Path to input CSV file
        parquet_path: Path to output Parquet file
        compression: Compression codec ('zstd', 'snappy', 'gzip', 'lz4', or 'uncompressed')

    Raises:
        ImportError: If Polars is not installed
        FileNotFoundError: If CSV file doesn't exist

    Example:
        >>> convert_aggtrades_to_parquet('trades.csv', 'trades.parquet')
    """
    if not HAS_POLARS:
        raise ImportError(
            "Polars is required for Parquet conversion. "
            "Install with: pip install polars"
        )

    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Create output directory if needed
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    # Use streaming sink for memory-efficient conversion
    lf = pl.scan_csv(csv_path)

    # Detect column names
    schema = lf.collect_schema()
    ts_col, qty_col = _detect_columns_polars(schema)

    # Normalize column names and types for consistent output
    lf = lf.select([
        pl.col(ts_col).cast(pl.Int64).alias('timestamp'),
        pl.col('price').cast(pl.Float64),
        pl.col(qty_col).cast(pl.Float64).alias('quantity'),
        pl.col('is_buyer_maker').cast(pl.Boolean),
    ])

    # Write to Parquet with streaming
    lf.sink_parquet(parquet_path, compression=compression)
