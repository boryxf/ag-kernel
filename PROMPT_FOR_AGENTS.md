# Prompt for AI Agents

You are working with **ag-backtester v0**, a deterministic backtesting engine with a "bare kernel" architecture.

## Critical Rules

### 🚫 DO NOT TOUCH

**NEVER modify these directories:**
- `core/` - C execution kernel (deterministic, frozen)
- `crates/` - Rust FFI bindings (frozen)

Modifying these will break the deterministic execution guarantees.

### ✅ YOU CAN MODIFY

**Only work in these directories:**
- `strategies/` - Your custom trading strategies
- `examples/` - Example backtests and scripts
- `python/ag_backtester/userland/` - User-facing utilities and helpers

## Quick Start

### 1. Understand the Architecture

```
aggTrades CSV → DataFeed → Tick Aggregation → C Engine → Results → Tearsheet
                 (Python)   (Python)           (C/Rust)            (matplotlib)
```

**You write**: Strategies (Python)
**Framework provides**: Execution engine, data loading, visualization

### 2. Running a Backtest

```bash
python examples/run_backtest.py \
  --input examples/data/btcusdt_aggtrades_sample.csv \
  --auto-ticksize \
  --bucket-ms 50
```

Outputs:
- `outputs/report.png` - Dark tearsheet
- `outputs/metrics.json` - Performance metrics
- `outputs/equity.csv` - Equity curve

### 3. Writing a Strategy

```python
# strategies/my_strategy.py

from ag_backtester import Engine, EngineConfig
from ag_backtester.data import AggTradesFeed, aggregate_ticks
from ag_backtester.engine import Order

def run_strategy(data_path: str):
    # 1. Load data
    feed = AggTradesFeed(data_path, tick_size=10.0)
    ticks = aggregate_ticks(feed.load(), bucket_ms=100, tick_size=10.0)

    # 2. Initialize engine
    config = EngineConfig(initial_cash=100_000.0, tick_size=10.0)
    engine = Engine(config)

    # 3. Run strategy
    for tick in ticks:
        engine.step_tick(tick)

        # Your logic here
        # Example: Buy on first tick
        if tick == ticks[0]:
            engine.place_order(Order(
                order_type='MARKET',
                side='BUY',
                qty=0.1
            ))

    # 4. Get results
    return engine.get_history()
```

### 4. Key APIs

**Data Loading:**
```python
from ag_backtester.data import AggTradesFeed, aggregate_ticks

feed = AggTradesFeed(csv_path, tick_size=1.0)
ticks = aggregate_ticks(feed.load(), bucket_ms=50, tick_size=1.0)
```

**Engine:**
```python
from ag_backtester import Engine, EngineConfig

config = EngineConfig(
    initial_cash=100_000.0,
    maker_fee=0.0001,  # 1 bp
    taker_fee=0.0002,  # 2 bp
    tick_size=1.0
)
engine = Engine(config)

# Process tick
engine.step_tick(tick)

# Place order
from ag_backtester.engine import Order
engine.place_order(Order(order_type='MARKET', side='BUY', qty=0.1))

# Get state
snapshot = engine.get_snapshot()
history = engine.get_history()
```

**Visualization:**
```python
from ag_backtester.viz import generate_tearsheet

generate_tearsheet(
    snapshots=engine.get_history(),
    trades=[],
    output_path='outputs/report.png'
)
```

**Auto Tick Size:**
```python
from ag_backtester.userland import calculate_auto_ticksize

tick_size = calculate_auto_ticksize(
    42150.0,          # BTC price
    target_ticks=20   # Desired granularity
)  # → 5.0
```

## Data Format

**aggTrades CSV** (Binance format):
```csv
timestamp,price,qty,is_buyer_maker
1704067200000,42150.50,0.025,true
1704067200050,42151.00,0.018,false
...
```

**Tick dataclass:**
```python
@dataclass
class Tick:
    ts_ms: int           # Timestamp (milliseconds)
    price_tick_i64: int  # Price in ticks (integer)
    qty: float           # Volume
    side: str            # 'BUY' or 'SELL'
```

## Common Tasks

### Task 1: Add a New Strategy

1. Create `strategies/my_strategy.py`
2. Copy template from above
3. Implement your logic in the tick loop
4. Test with: `python strategies/my_strategy.py`

### Task 2: Add a Custom Indicator

1. Create `python/ag_backtester/userland/indicators.py`
2. Write pure Python indicator functions
3. Use in your strategy

### Task 3: Analyze Backtest Results

```python
import json
import pandas as pd

# Read metrics
with open('outputs/metrics.json') as f:
    metrics = json.load(f)
print(f"Return: {metrics['total_return']:.2%}")

# Read equity curve
df = pd.read_csv('outputs/equity.csv')
print(df.head())
```

## Troubleshooting

**Problem**: "Module 'ag_backtester' has no attribute '_ag_core'"
**Solution**: Run `maturin develop --release -m crates/ag-core/Cargo.toml` to build Rust extension

**Problem**: "No such file or directory: data.csv"
**Solution**: Use absolute paths or run from project root

**Problem**: "Tick aggregation returns empty list"
**Solution**: Check CSV format, ensure columns match expected schema

## Remember

- ✅ Write strategies, examples, and userland utilities
- ❌ Never modify `core/` or `crates/`
- 📖 Read `README.md` for full documentation
- 🤖 You're working with a **bare kernel** - strategies go in userland, not in the engine

---

**Happy backtesting!** 🚀
