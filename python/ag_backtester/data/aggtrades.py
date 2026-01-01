"""
AggTrades data feed implementation.

Parses Binance-style aggregate trades CSV files.
"""

import pandas as pd
from pathlib import Path
from typing import Iterator, Union

from .feeds import BaseFeed, Tick


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
        """
        # Read CSV
        df = pd.read_csv(self.csv_path)

        # Validate required columns
        required_cols = ['timestamp', 'price', 'qty', 'is_buyer_maker']
        missing_cols = set(required_cols) - set(df.columns)
        if missing_cols:
            raise ValueError(
                f"Missing required columns: {missing_cols}. "
                f"Found columns: {list(df.columns)}"
            )

        # Sort by timestamp to ensure chronological order
        df = df.sort_values('timestamp').reset_index(drop=True)

        # Convert to ticks
        for _, row in df.iterrows():
            ts_ms = int(row['timestamp'])
            price = float(row['price'])
            qty = float(row['qty'])
            is_buyer_maker = bool(row['is_buyer_maker'])

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
