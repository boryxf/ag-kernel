---
name: data-adapters
description: Data loading and aggTrades→Tick aggregation
responsibilities:
  - Parse aggTrades CSV/JSON
  - Implement tick aggregation with bucketing
  - Auto tick size calculation
  - Support multiple data formats (OHLC, ticks, aggTrades)
constraints:
  - ONLY touch python/ag_backtester/data/ and python/ag_backtester/userland/
  - Pure Python (pandas/numpy OK)
  - Clean interface for Engine consumption
---

# Data Adapters Agent

Role: Load and transform market data into engine-ready format.

## Scope
- `python/ag_backtester/data/feeds.py` - DataFeed base class
- `python/ag_backtester/data/aggtrades.py` - aggTrades adapter
- `python/ag_backtester/data/tick_aggregator.py` - Tick bucketing logic
- `python/ag_backtester/userland/auto_ticksize.py` - Auto tick size calculator

## aggTrades Format
Input CSV columns:
- `timestamp` (ms)
- `price` (float)
- `qty` (float)
- `is_buyer_maker` (bool)

## Tick Aggregation Logic
```python
bucket_ts = (ts_ms // bucket_ms) * bucket_ms
tick_i64 = round(price / tick_size)
side = 'SELL' if is_buyer_maker else 'BUY'
key = (bucket_ts, tick_i64, side)
# Accumulate qty per key
```

## Auto Tick Size
Goal: `typical_range / tick_size ≈ target_ticks`

Algorithm:
1. Estimate range (from recent OHLC bars or price * 0.002)
2. Initial tick = range / target_ticks
3. Round to "nice" step: 1, 2, 2.5, 5 × 10^k
4. Example: BTC ~$100k, 1h range ~$500, target=20 → tick=$25

Function: `calculate_auto_ticksize(data, timeframe='1h', target_ticks=20)`
