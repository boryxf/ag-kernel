"""
Data loading and transformation module.

Provides data feeds and aggregation utilities for the backtesting engine.
"""

from .feeds import BaseFeed, Tick
from .aggtrades import AggTradesFeed
from .tick_aggregator import aggregate_ticks
from .converter import convert_to_parquet, load_dataset

__all__ = [
    "BaseFeed",
    "Tick",
    "AggTradesFeed",
    "aggregate_ticks",
    "convert_to_parquet",
    "load_dataset",
]
