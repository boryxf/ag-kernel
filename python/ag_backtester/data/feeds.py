"""
Base data feed abstractions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Literal


@dataclass
class Tick:
    """
    A single tick representing aggregated volume at a specific price level.

    Attributes:
        ts_ms: Timestamp in milliseconds (UTC)
        price_tick_i64: Quantized price level (price / tick_size, rounded)
        qty: Volume accumulated at this tick level
        side: Trade direction ('BUY' or 'SELL')
    """
    ts_ms: int
    price_tick_i64: int
    qty: float
    side: Literal['BUY', 'SELL']


class BaseFeed(ABC):
    """
    Abstract base class for market data feeds.

    All data feeds must implement the iter_ticks method to provide
    a stream of Tick objects to the backtesting engine.
    """

    @abstractmethod
    def iter_ticks(self) -> Iterator[Tick]:
        """
        Yield ticks in chronological order.

        Returns:
            Iterator of Tick objects
        """
        pass
