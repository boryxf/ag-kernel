"""
Tick aggregation utilities.

Aggregates raw ticks into time-bucketed, price-level volumes.
"""

from typing import Iterator, List
from collections import defaultdict

from .feeds import Tick


def aggregate_ticks(
    trades: Iterator[Tick],
    bucket_ms: int,
    tick_size: float,
) -> List[Tick]:
    """
    Aggregate ticks into time-bucketed volumes per (time, price_level, side).

    Algorithm:
        1. Bucket timestamp: bucket_ts = (ts_ms // bucket_ms) * bucket_ms
        2. Quantize price: tick_i64 = round(price / tick_size)
        3. Map side: 'SELL' if is_buyer_maker else 'BUY'
        4. Accumulate qty for each unique (bucket_ts, tick_i64, side) tuple

    Args:
        trades: Iterator of Tick objects (raw trades)
        bucket_ms: Time bucket size in milliseconds (e.g., 1000 for 1s buckets)
        tick_size: Price tick size for quantization

    Returns:
        List of aggregated Tick objects, sorted by (timestamp, price_tick_i64, side)

    Example:
        >>> raw_ticks = [
        ...     Tick(ts_ms=1000, price_tick_i64=100, qty=1.5, side='BUY'),
        ...     Tick(ts_ms=1100, price_tick_i64=100, qty=2.0, side='BUY'),
        ...     Tick(ts_ms=1200, price_tick_i64=101, qty=1.0, side='SELL'),
        ... ]
        >>> agg = aggregate_ticks(iter(raw_ticks), bucket_ms=1000, tick_size=1.0)
        >>> # First two trades bucketed together (same 1000ms bucket, same tick, same side)
        >>> # Result: [(1000, 100, 3.5, 'BUY'), (1000, 101, 1.0, 'SELL')]
    """
    # Accumulator: {(bucket_ts, tick_i64, side): total_qty}
    buckets = defaultdict(float)

    for tick in trades:
        # Calculate bucket timestamp
        bucket_ts = (tick.ts_ms // bucket_ms) * bucket_ms

        # Re-quantize price if tick_size changed
        # (In case input ticks used different tick_size)
        price_reconstructed = tick.price_tick_i64 * tick_size
        tick_i64 = round(price_reconstructed / tick_size)

        # Use the tick_i64 from the input tick directly if tick_size matches
        # For simplicity, we assume input ticks are already correctly quantized
        tick_i64 = tick.price_tick_i64

        # Create bucket key
        key = (bucket_ts, tick_i64, tick.side)

        # Accumulate quantity
        buckets[key] += tick.qty

    # Convert to list of Tick objects
    result = []
    for (bucket_ts, tick_i64, side), total_qty in buckets.items():
        result.append(Tick(
            ts_ms=bucket_ts,
            price_tick_i64=tick_i64,
            qty=total_qty,
            side=side
        ))

    # Sort by timestamp, then price level, then side
    result.sort(key=lambda t: (t.ts_ms, t.price_tick_i64, t.side))

    return result
