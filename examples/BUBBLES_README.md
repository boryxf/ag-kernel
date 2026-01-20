# Bubbles Visualization for Order Flow

Visual analysis of trading orders executed through ag-kernel backtesting engine.

## Overview

The bubbles visualization scripts provide an intuitive way to see:
- **Order timing** - When orders were placed (X-axis)
- **Order price** - At what price (Y-axis)
- **Order size** - Quantity traded (bubble size)
- **Order direction** - BUY (green) vs SELL (red)
- **Strategy performance** - Equity curve below

## Scripts

### 1. `bubbles_visualization.py` - Basic Bubbles

Simple single-strategy visualization with Binance API integration.

**Features:**
- Fetch real BTCUSDT data from Binance
- Mean-reversion strategy
- Dark-themed matplotlib output
- Equity curve + statistics

**Usage:**

```bash
# Fetch latest 1000 trades from Binance
python examples/bubbles_visualization.py --fetch --limit 1000

# Use local CSV file
python examples/bubbles_visualization.py --csv data/btcusdt.csv

# Custom parameters
python examples/bubbles_visualization.py \
  --fetch \
  --symbol BTCUSDT \
  --limit 1000 \
  --initial-cash 50000 \
  --bucket-ms 50 \
  --output outputs/my_bubbles.png
```

**Output:**
- `outputs/bubbles.png` - Visualization
- Console statistics

### 2. `bubbles_advanced.py` - Multi-Strategy Comparison

Compare multiple strategies side-by-side with advanced visualizations.

**Features:**
- 3 built-in strategies:
  - `mean-reversion` - Bollinger Bands
  - `momentum` - Moving Average Crossover
  - `random` - Baseline comparison
- Side-by-side comparison mode
- Enhanced bubble styling
- Per-strategy statistics

**Usage:**

```bash
# Single strategy
python examples/bubbles_advanced.py \
  --fetch \
  --limit 1000 \
  --strategy momentum

# Compare all strategies
python examples/bubbles_advanced.py \
  --fetch \
  --limit 1000 \
  --compare

# Use local data + compare
python examples/bubbles_advanced.py \
  --csv data/btcusdt_aggtrades_sample.csv \
  --compare \
  --output outputs/strategy_comparison.png
```

**Output:**
- `outputs/bubbles_advanced.png` - Multi-panel visualization
- Comparative statistics

## Command-Line Options

### Data Source (required, pick one)
- `--fetch` - Fetch from Binance API
- `--csv PATH` - Use local CSV file

### Binance API Options
- `--symbol SYMBOL` - Trading pair (default: BTCUSDT)
- `--limit N` - Number of trades (default: 1000, max: 1000)

### Backtest Parameters
- `--initial-cash AMOUNT` - Starting capital (default: 100000)
- `--tick-size SIZE` - Price granularity (default: auto)
- `--bucket-ms MS` - Tick aggregation (default: 100ms)

### Strategy Options (advanced only)
- `--strategy NAME` - Choose: mean-reversion, momentum, random
- `--compare` - Run all strategies side-by-side

### Output
- `--output PATH` - Save location (default: outputs/bubbles.png)
- `--title TEXT` - Chart title

## Understanding the Visualization

### Bubble Chart (Top Panel)

```
         Price
           ↑
           |     ○ ← Small SELL order
           |  ●     ← Large BUY order
           |    ○   
           |  ●  ○  
           |─────────→ Time
```

**Reading bubbles:**
- **Size** = Order quantity (larger bubble = more BTC)
- **Color** = Direction (green BUY, red SELL)
- **Position** = When (X) and where (Y) order executed
- **Edge** = White outline for visibility

**Cyan dashed line** = Market price movement

### Equity Curve (Bottom Panel)

Shows portfolio value over time:
- **Gold line** = Total equity (cash + position value)
- **White dashed** = Initial capital
- **Above/below** = Profit/loss

### Statistics Box

```
Orders: 47              # Total orders executed
Volume: 0.4700 BTC      # Total BTC traded
Fees: $156.79           # Total trading costs
PnL: $-234.56 (-0.23%)  # Net profit/loss
```

## Data Format

### Binance aggTrades CSV

The scripts expect Binance aggregated trades format:

```csv
timestamp,price,qty,is_buyer_maker
1704067200000,42150.50,0.025,true
1704067200050,42151.00,0.018,false
```

**Columns:**
- `timestamp` - Unix milliseconds
- `price` - Trade price (USDT)
- `qty` - Trade quantity (BTC)
- `is_buyer_maker` - True if buyer is maker side

### Creating Your Own Data

```python
import pandas as pd

df = pd.DataFrame({
    'timestamp': [1704067200000, 1704067200100],
    'price': [42150.5, 42151.0],
    'qty': [0.025, 0.018],
    'is_buyer_maker': [True, False]
})

df.to_csv('my_data.csv', index=False)
```

## Strategy Details

### Mean Reversion

**Logic:** Buy oversold, sell overbought
- **Indicator:** Bollinger Bands (20-period, 2 std dev)
- **Buy:** Price < lower band
- **Sell:** Price > upper band
- **Best for:** Ranging markets

### Momentum

**Logic:** Follow the trend
- **Indicator:** MA crossover (10-fast, 30-slow)
- **Buy:** Golden cross (fast > slow)
- **Sell:** Death cross (fast < slow)
- **Best for:** Trending markets

### Random

**Logic:** Random trades for baseline
- **Trades:** 5% probability per tick
- **Direction:** 50/50 buy/sell
- **Purpose:** Compare against chance

## Examples

### Example 1: Quick Test

```bash
# Get latest 500 trades and visualize
python examples/bubbles_visualization.py --fetch --limit 500
```

### Example 2: Strategy Comparison

```bash
# Which strategy performs best?
python examples/bubbles_advanced.py --fetch --limit 1000 --compare
```

### Example 3: High-Frequency Data

```bash
# 50ms buckets for more granular view
python examples/bubbles_visualization.py \
  --fetch \
  --limit 1000 \
  --bucket-ms 50
```

### Example 4: Custom Data

```bash
# Use your own historical data
python examples/bubbles_visualization.py \
  --csv ~/data/btc_jan2024.csv \
  --initial-cash 200000 \
  --tick-size 10.0
```

## Interpreting Results

### Good Strategy Signs
- ✅ Bubbles cluster at local extremes (buy low, sell high)
- ✅ Equity curve trending upward
- ✅ BUY bubbles at price troughs
- ✅ SELL bubbles at price peaks

### Bad Strategy Signs
- ❌ Random bubble distribution
- ❌ Equity curve declining
- ❌ BUY bubbles at peaks (buy high)
- ❌ SELL bubbles at troughs (sell low)

### Example Analysis

```
Good mean-reversion:
  ● Buys cluster at bottom of dips
  ○ Sells cluster at top of spikes
  → Equity curve rises steadily

Poor momentum following:
  ● Buys cluster after price already rose
  ○ Sells cluster after price already fell
  → Equity curve declines (buy high, sell low)
```

## Performance Tips

### For Faster Execution
- Use larger `--bucket-ms` (e.g., 200ms instead of 50ms)
- Reduce `--limit` for quick tests
- Use local CSV instead of API fetching

### For Better Visuals
- Use 500-1000 trades for clear bubbles
- Smaller `--bucket-ms` for smoother price line
- `--compare` mode for strategy insights

## Troubleshooting

### "No orders to visualize"
- Strategy didn't trigger any trades
- Try different `--bucket-ms` or `--limit`
- Check if price moved enough for signals

### "Module 'ag_backtester' not found"
```bash
cd crates/ag-core
maturin develop --release
```

### "Binance API error"
- Check internet connection
- API might be rate-limited (wait 1 minute)
- Try smaller `--limit`

### Empty/weird bubbles
- Data might be corrupted
- Check CSV format matches expected schema
- Try `--tick-size` auto-calculation (omit parameter)

## Technical Details

### Architecture Flow

```
Binance API → CSV → AggTradesFeed → Tick Aggregation
                                            ↓
                                      ag-kernel Engine
                                            ↓
                                    Strategy Execution
                                            ↓
                                    Order Recording
                                            ↓
                                  Matplotlib Visualization
```

### Performance

- **Backtest speed:** ~10K ticks/second
- **Memory usage:** ~50MB for 1000 trades
- **Visualization:** ~2 seconds for rendering

### Dependencies

```
matplotlib  # Visualization
pandas      # Data handling
numpy       # Calculations
requests    # Binance API
ag_backtester  # Our engine (built from Rust)
```

## Advanced: Custom Strategies

Create your own strategy in the scripts:

```python
class MyStrategy(BaseStrategy):
    def __init__(self, engine: Engine):
        super().__init__(engine, name="my-strategy")
        
    def on_tick(self, tick: Tick) -> None:
        price = tick.price_tick_i64 * self.engine.config.tick_size
        snapshot = self.engine.get_snapshot()
        
        # Your logic here
        if your_buy_condition:
            order = Order(order_type='MARKET', side='BUY', qty=0.01)
            self.engine.place_order(order)
            self.record_order(tick, order, snapshot)
```

## Related Documentation

- [README.md](../README.md) - Main project documentation
- [PROMPT_FOR_AGENTS.md](../PROMPT_FOR_AGENTS.md) - Developer guide
- [examples/run_backtest.py](run_backtest.py) - Full backtest example

## Support

For issues or questions:
1. Check console output for error messages
2. Verify CSV format matches Binance aggTrades
3. Ensure ag-core is built (`maturin develop --release`)
4. Review strategy logic in source code

---

**Happy visualizing!** 🎨📊
