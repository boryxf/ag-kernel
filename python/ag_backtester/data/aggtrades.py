"""
AggTrades data feed implementation.

Parses Binance-style aggregate trades CSV files.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Iterator, Tuple, Union

from .feeds import BaseFeed, Tick


# Column name mappings for different CSV formats
# Binance Vision uses: transact_time, quantity
# Standard format uses: timestamp, qty
TIMESTAMP_COLS = ['transact_time', 'timestamp']
QUANTITY_COLS = ['quantity', 'qty']
PRICE_COL = 'price'
IS_BUYER_MAKER_COL = 'is_buyer_maker'


def _detect_column_names(columns: list) -> Tuple[str, str]:
    """
    Detect the correct column names for timestamp and quantity.

    Handles both Binance Vision format (transact_time, quantity) and
    standard format (timestamp, qty).

    Args:
        columns: List of column names from the DataFrame

    Returns:
        Tuple of (timestamp_col, quantity_col)

    Raises:
        ValueError: If required columns are not found
    """
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

    # Validate
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

    if PRICE_COL not in columns_set:
        raise ValueError(
            f"Missing '{PRICE_COL}' column. Found columns: {columns}"
        )

    if IS_BUYER_MAKER_COL not in columns_set:
        raise ValueError(
            f"Missing '{IS_BUYER_MAKER_COL}' column. Found columns: {columns}"
        )

    return ts_col, qty_col


class AggTradesFeed(BaseFeed):
    """
    Data feed for aggregate trades from CSV files.

    Expected CSV columns:
        - timestamp: Unix timestamp in milliseconds
        - price: Trade price (float)
        - qty: Trade quantity (float)
        - is_buyer_maker: Boolean indicating if buyer was maker (1/0 or True/False)

    The feed converts aggTrades into raw ticks without aggregation.
    For tick aggregation, use tick_aggregator.aggregate_ticks().
    """

    def __init__(
        self,
        csv_path: Union[str, Path],
        tick_size: float = 1.0,
    ):
        """
        Initialize AggTradesFeed.

        Args:
            csv_path: Path to CSV file with aggTrades data
            tick_size: Price tick size for quantization
        """
        self.csv_path = Path(csv_path)
        self.tick_size = tick_size

        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")

    def iter_ticks(self) -> Iterator[Tick]:
        """
        Parse CSV and yield Tick objects.

        Side mapping:
            - is_buyer_maker=True -> SELL (maker was selling, taker bought)
            - is_buyer_maker=False -> BUY (maker was buying, taker sold)

        Yields:
            Tick objects in chronological order

        Note:
            For better performance on large files, use load_vectorized() instead.
        """
        # Read CSV
        df = pd.read_csv(self.csv_path)

        # Detect column names (handles both Binance Vision and standard formats)
        ts_col, qty_col = _detect_column_names(list(df.columns))

        # Sort by timestamp to ensure chronological order
        df = df.sort_values(ts_col).reset_index(drop=True)

        # Convert to ticks
        for _, row in df.iterrows():
            ts_ms = int(row[ts_col])
            price = float(row[PRICE_COL])
            qty = float(row[qty_col])
            is_buyer_maker = bool(row[IS_BUYER_MAKER_COL])

            # Quantize price to tick level
            price_tick_i64 = round(price / self.tick_size)

            # Determine side: buyer_maker means the passive side was buying,
            # so the aggressive taker was selling
            side = 'SELL' if is_buyer_maker else 'BUY'

            yield Tick(
                ts_ms=ts_ms,
                price_tick_i64=price_tick_i64,
                qty=qty,
                side=side
            )

    def load(self) -> list:
        """
        Load all ticks into a list.

        Returns:
            List of Tick objects
        """
        return list(self.iter_ticks())

    def load_vectorized(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Load all data as numpy arrays for maximum performance.

        This method is ~100x faster than iter_ticks() for large files because
        it uses vectorized pandas/numpy operations instead of row-by-row iteration.

        Returns:
            Tuple of (timestamps, price_ticks, qtys, sides) as numpy arrays:
            - timestamps: int64 array of Unix timestamps in milliseconds
            - price_ticks: int64 array of quantized price levels (price / tick_size)
            - qtys: float64 array of trade quantities
            - sides: uint8 array where 0=BUY, 1=SELL (matches is_buyer_maker)

        Example:
            >>> feed = AggTradesFeed('trades.csv', tick_size=0.01)
            >>> timestamps, price_ticks, qtys, sides = feed.load_vectorized()
            >>> # Feed directly to engine.step_batch()
        """
        # Read CSV
        df = pd.read_csv(self.csv_path)

        # Detect column names (handles both Binance Vision and standard formats)
        ts_col, qty_col = _detect_column_names(list(df.columns))

        # Sort by timestamp to ensure chronological order
        df = df.sort_values(ts_col).reset_index(drop=True)

        # Extract as numpy arrays (vectorized operations)
        timestamps = df[ts_col].values.astype(np.int64)

        prices = df[PRICE_COL].values
        price_ticks = np.round(prices / self.tick_size).astype(np.int64)

        qtys = df[qty_col].values.astype(np.float64)

        # 0=BUY, 1=SELL (is_buyer_maker=True means SELL)
        sides = df[IS_BUYER_MAKER_COL].values.astype(np.uint8)

        return timestamps, price_ticks, qtys, sides
