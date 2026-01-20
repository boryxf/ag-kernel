"""
Data loading and transformation module.

Provides data feeds and aggregation utilities for the backtesting engine.

Performance Guide:
- For small files (<100K rows): Use AggTradesFeed.iter_ticks() or load()
- For large files (>100K rows): Use AggTradesFeed.load_vectorized()
- For tick aggregation: Use aggregate_ticks_polars() (~10-50x faster)
- For Parquet files: Use load_parquet_mmap() for memory efficiency
- For huge files: Use stream_parquet_batches() for constant memory usage
"""

from .feeds import BaseFeed, Tick
from .aggtrades import AggTradesFeed
from .tick_aggregator import aggregate_ticks
from .converter import convert_to_parquet, load_dataset

# Fast aggregation (requires polars)
from .fast_aggregator import (
    aggregate_ticks_polars,
    aggregate_to_numpy,
    convert_aggtrades_to_parquet,
)

# Memory-mapped Parquet loading (requires pyarrow)
from .parquet_loader import (
    load_parquet_mmap,
    stream_parquet_batches,
    get_parquet_metadata,
)

__all__ = [
    # Base classes
    "BaseFeed",
    "Tick",
    # Data feeds
    "AggTradesFeed",
    # Aggregation
    "aggregate_ticks",
    "aggregate_ticks_polars",
    "aggregate_to_numpy",
    # Conversion
    "convert_to_parquet",
    "convert_aggtrades_to_parquet",
    # Loading
    "load_dataset",
    "load_parquet_mmap",
    "stream_parquet_batches",
    "get_parquet_metadata",
]
