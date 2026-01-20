"""
Memory-mapped Parquet loading for minimal RAM usage.

Provides efficient Parquet loading with memory-mapping and streaming batch
capabilities for processing large datasets that don't fit in memory.
"""

import numpy as np
from pathlib import Path
from typing import Generator, Tuple, Union

try:
    import pyarrow.parquet as pq
    import pyarrow as pa
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False


# Column name mappings for different Parquet formats
TIMESTAMP_COLS = ['transact_time', 'timestamp']
QUANTITY_COLS = ['quantity', 'qty']


def _detect_columns_arrow(column_names: list) -> Tuple[str, str]:
    """
    Detect the correct column names for timestamp and quantity.

    Args:
        column_names: List of column names from the table

    Returns:
        Tuple of (timestamp_col, quantity_col)

    Raises:
        ValueError: If required columns are not found
    """
    columns_set = set(column_names)

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
            f"found columns: {column_names}"
        )

    if qty_col is None:
        raise ValueError(
            f"Missing quantity column. Expected one of {QUANTITY_COLS}, "
            f"found columns: {column_names}"
        )

    return ts_col, qty_col


def load_parquet_mmap(
    parquet_path: Union[str, Path],
    tick_size: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Load Parquet file with memory-mapping for minimal RAM usage.

    Memory-mapping allows the OS to handle paging, meaning only the portions
    of the file being actively used are loaded into RAM. This is ideal for
    large files that exceed available memory.

    Args:
        parquet_path: Path to .parquet file
        tick_size: Price tick size for quantization

    Returns:
        Tuple of (timestamps, price_ticks, qtys, sides) as numpy arrays:
        - timestamps: int64 array of Unix timestamps in milliseconds
        - price_ticks: int64 array of quantized price levels (price / tick_size)
        - qtys: float64 array of trade quantities
        - sides: uint8 array where 0=BUY, 1=SELL

    Raises:
        ImportError: If PyArrow is not installed
        FileNotFoundError: If Parquet file doesn't exist
        ValueError: If required columns are missing

    Example:
        >>> ts, ticks, qtys, sides = load_parquet_mmap('trades.parquet', tick_size=0.01)
        >>> engine.step_batch(ts, ticks, qtys, sides)
    """
    if not HAS_PYARROW:
        raise ImportError(
            "PyArrow is required for Parquet loading. "
            "Install with: pip install pyarrow"
        )

    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    # Memory-mapped read for minimal RAM usage
    table = pq.read_table(parquet_path, memory_map=True)

    column_names = table.column_names
    ts_col, qty_col = _detect_columns_arrow(column_names)

    # Check for side vs is_buyer_maker column
    has_side = 'side' in column_names
    has_buyer_maker = 'is_buyer_maker' in column_names

    if not has_side and not has_buyer_maker:
        raise ValueError(
            f"Missing side column. Expected 'side' or 'is_buyer_maker', "
            f"found columns: {column_names}"
        )

    # Zero-copy conversion to numpy where possible
    timestamps = table.column(ts_col).to_numpy().astype(np.int64)
    prices = table.column('price').to_numpy().astype(np.float64)
    qtys = table.column(qty_col).to_numpy().astype(np.float64)

    # Handle both 'side' and 'is_buyer_maker' columns
    if has_side:
        sides = table.column('side').to_numpy().astype(np.uint8)
    else:
        # Convert is_buyer_maker (True/False) to side (0=BUY, 1=SELL)
        sides = table.column('is_buyer_maker').to_numpy().astype(np.uint8)

    # Quantize prices to tick levels
    price_ticks = np.round(prices / tick_size).astype(np.int64)

    return timestamps, price_ticks, qtys, sides


def stream_parquet_batches(
    parquet_path: Union[str, Path],
    tick_size: float,
    batch_size: int = 100_000,
) -> Generator[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], None, None]:
    """
    Stream Parquet file in batches for memory efficiency.

    This is useful for processing files that are too large to fit in memory.
    Each batch is independently processed, allowing for constant memory usage
    regardless of file size.

    Args:
        parquet_path: Path to .parquet file
        tick_size: Price tick size for quantization
        batch_size: Number of rows per batch (default: 100,000)

    Yields:
        Tuples of (timestamps, price_ticks, qtys, sides) for each batch:
        - timestamps: int64 array of Unix timestamps in milliseconds
        - price_ticks: int64 array of quantized price levels
        - qtys: float64 array of trade quantities
        - sides: uint8 array where 0=BUY, 1=SELL

    Raises:
        ImportError: If PyArrow is not installed
        FileNotFoundError: If Parquet file doesn't exist
        ValueError: If required columns are missing

    Example:
        >>> for ts, ticks, qtys, sides in stream_parquet_batches('trades.parquet', 0.01):
        ...     engine.step_batch(ts, ticks, qtys, sides)
    """
    if not HAS_PYARROW:
        raise ImportError(
            "PyArrow is required for Parquet loading. "
            "Install with: pip install pyarrow"
        )

    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    # Open file with memory mapping
    parquet_file = pq.ParquetFile(parquet_path, memory_map=True)

    # Get column names from schema
    schema = parquet_file.schema_arrow
    column_names = [field.name for field in schema]
    ts_col, qty_col = _detect_columns_arrow(column_names)

    # Check for side vs is_buyer_maker column
    has_side = 'side' in column_names
    has_buyer_maker = 'is_buyer_maker' in column_names

    if not has_side and not has_buyer_maker:
        raise ValueError(
            f"Missing side column. Expected 'side' or 'is_buyer_maker', "
            f"found columns: {column_names}"
        )

    # Stream batches
    for batch in parquet_file.iter_batches(batch_size=batch_size):
        table = pa.Table.from_batches([batch])

        # Extract numpy arrays
        timestamps = table.column(ts_col).to_numpy().astype(np.int64)
        prices = table.column('price').to_numpy().astype(np.float64)
        qtys = table.column(qty_col).to_numpy().astype(np.float64)

        # Handle both 'side' and 'is_buyer_maker' columns
        if has_side:
            sides = table.column('side').to_numpy().astype(np.uint8)
        else:
            sides = table.column('is_buyer_maker').to_numpy().astype(np.uint8)

        # Quantize prices to tick levels
        price_ticks = np.round(prices / tick_size).astype(np.int64)

        yield timestamps, price_ticks, qtys, sides


def get_parquet_metadata(parquet_path: Union[str, Path]) -> dict:
    """
    Get metadata about a Parquet file without loading it.

    Useful for understanding file structure and size before loading.

    Args:
        parquet_path: Path to .parquet file

    Returns:
        Dictionary with file metadata:
        - num_rows: Total number of rows
        - num_columns: Number of columns
        - columns: List of column names
        - num_row_groups: Number of row groups
        - file_size_mb: File size in megabytes
        - compression: Compression codec used

    Raises:
        ImportError: If PyArrow is not installed
        FileNotFoundError: If Parquet file doesn't exist
    """
    if not HAS_PYARROW:
        raise ImportError(
            "PyArrow is required for Parquet loading. "
            "Install with: pip install pyarrow"
        )

    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    # Get file size
    file_size_mb = parquet_path.stat().st_size / (1024 * 1024)

    # Open file for metadata
    parquet_file = pq.ParquetFile(parquet_path)
    metadata = parquet_file.metadata

    # Get compression from first row group, first column
    compression = None
    if metadata.num_row_groups > 0:
        row_group = metadata.row_group(0)
        if row_group.num_columns > 0:
            compression = row_group.column(0).compression

    return {
        'num_rows': metadata.num_rows,
        'num_columns': metadata.num_columns,
        'columns': [field.name for field in parquet_file.schema_arrow],
        'num_row_groups': metadata.num_row_groups,
        'file_size_mb': round(file_size_mb, 2),
        'compression': compression,
    }
