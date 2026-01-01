# ag-backtester v0

Lightweight, deterministic backtesting engine with C kernel, Rust bridge, and Python API.

---

## ⚠️ AI AGENTS: DO NOT TOUCH `core/` (C) AND `crates/` (Rust)

**These directories are OFF-LIMITS for modifications.**

The execution kernel provides deterministic, reproducible backtesting results. Any changes to `core/` or `crates/` will break this guarantee.

### What You CAN Do:
- ✅ Add strategies in `strategies/`
- ✅ Add examples in `examples/`
- ✅ Add user utilities in `python/ag_backtester/userland/`

### What You CANNOT Do:
- ❌ Modify `core/` - C execution engine
- ❌ Modify `crates/` - Rust FFI bindings
- ❌ Change engine semantics

See `PROMPT_FOR_AGENTS.md` for detailed guidelines.

---

## 🚀 Performance

Processing **1,000,000 ticks** on a standard machine:

| Implementation | Execution Time | Throughput | Speedup |
| :--- | :--- | :--- | :--- |
| **AG-Backtester (Batch)** | **0.06s** | **~16,400,000 ticks/s** | **2.8x** 🚀 |
| Naive PyO3 (Single Call) | 2.04s | ~491,000 ticks/s | 0.1x |
| Pure Python | 0.17s | ~5,764,000 ticks/s | 1.0x |

*Benchmark run on Apple M1 (Darwin arm64) with Python 3.9*

**Key Optimizations:**
- ✅ **Batch processing**: Moves loop inside Rust to eliminate FFI overhead
- ✅ **Parquet binary format**: 70% size reduction + instant loading (< 100ms for 1M ticks)
- ✅ **Automatic conversion**: First run converts CSV → Parquet, subsequent runs load instantly

Run your own benchmark: `python3 benchmark_v0.py`

---

## Features

- **Deterministic C kernel**: Pure calculation engine with no I/O or randomness
- **Batch processing**: Process millions of ticks in milliseconds via Rust FFI
- **Automatic Parquet conversion**: ZSTD compressed binary format with instant loading
- **aggTrades → Tick aggregation**: Built-in support for Binance aggTrades format
- **Auto tick size**: Automatically calculates optimal tick size for your instrument
- **Dark tearsheet**: Professional GitHub-dark themed performance reports
- **Three-layer architecture**: C (execution) → Rust (safe bindings) → Python (API)

## Quick Start

### Installation

```bash
# Clone repository
git clone <repo-url>
cd ag-kernel

# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install maturin if not already installed
pip install maturin

# Build and install
maturin develop --release -m crates/ag-core/Cargo.toml

# Install Python dependencies
pip install -e .
```

### Run Example

```bash
python examples/run_backtest.py \
  --input examples/data/btcusdt_aggtrades_sample.csv \
  --mode aggtrades \
  --auto-ticksize \
  --bucket-ms 50
```

**Outputs**:
- `outputs/report.png` - Dark-themed tearsheet with charts and metrics
- `outputs/metrics.json` - Performance metrics (return, drawdown, Sharpe, etc.)
- `outputs/equity.csv` - Equity curve time series

## Architecture

### Layer 1: C Kernel (`core/`)

Pure C execution engine with deterministic behavior:

- **State management**: Cash, position, open orders, PnL tracking
- **Order execution**: Market and limit orders with configurable fees and spread
- **Events**: Tick-based event processing
- **No dependencies**: Standard library only

**Key files**:
- `core/types.h` - Data structures (events, orders, snapshots)
- `core/engine.h` - C API (handle-based interface)
- `core/engine.c` - Implementation

### Layer 2: Rust Bridge (`crates/`)

Safe FFI bindings with Python integration:

- **`ag-core-sys/`**: Unsafe C bindings + build script (cc crate)
- **`ag-core/`**: Safe wrapper + PyO3 Python bindings

**Build process**:
1. `build.rs` compiles C code via `cc` crate
2. Unsafe bindings map C functions
3. Safe wrapper provides RAII and error handling
4. PyO3 exposes to Python

### Layer 3: Python API (`python/ag_backtester/`)

User-facing interface:

- **`engine.py`**: Engine wrapper (uses Rust core or stub fallback)
- **`data/`**: Data feeds and tick aggregation
  - `aggtrades.py` - Binance aggTrades CSV parser
  - `tick_aggregator.py` - Time-bucketed volume aggregation
- **`userland/`**: User utilities
  - `auto_ticksize.py` - Automatic tick size calculation
- **`viz/`**: Visualization
  - `tearsheet.py` - 4-panel dark tearsheet generator
  - `metrics.py` - Performance metrics calculation

## Data Modes

| Mode | Input | Description | Status |
|------|-------|-------------|--------|
| **aggTrades** | CSV with timestamp, price, qty, is_buyer_maker | Binance aggregate trades | ✅ Supported |
| **OHLC** | CSV/JSON with open, high, low, close | Bar data | 🔄 Planned |
| **Ticks** | Pre-aggregated ticks | Direct tick feed | 🔄 Planned |
| **L2** | Order book snapshots | Level 2 data | 🔄 Planned |

## aggTrades Format

Input CSV columns:
- `timestamp`: Unix timestamp in milliseconds
- `price`: Trade price (float)
- `qty`: Trade quantity (float)
- `is_buyer_maker`: Boolean (1/0 or True/False)

Side mapping:
- `is_buyer_maker=True` → `SELL` (taker bought from maker)
- `is_buyer_maker=False` → `BUY` (taker sold to maker)

## Auto Tick Size

Automatically determines optimal tick size for your instrument:

```python
from ag_backtester.userland import calculate_auto_ticksize

# From price (uses 0.2% heuristic)
tick_size = calculate_auto_ticksize(42150.0, target_ticks=20)  # → 5.0

# From OHLC DataFrame
import pandas as pd
df = pd.DataFrame({'high': [...], 'low': [...]})
tick_size = calculate_auto_ticksize(df, timeframe='1h', target_ticks=20)
```

Algorithm:
1. Estimate typical range (from OHLC or price * 0.002)
2. Calculate raw tick: range / target_ticks
3. Round to "nice" value: 1, 2, 2.5, 5 × 10^k

## Writing Strategies

### Directory Structure

```
ag-kernel/
├── strategies/          # ← Your strategies go here
│   ├── my_strategy.py
│   └── ...
├── examples/            # ← Example backtests
│   ├── run_backtest.py
│   └── data/
└── python/
    └── ag_backtester/   # ← Framework code
        ├── userland/    # ← You can add helpers here
        └── ...
```

### Example Strategy

```python
# strategies/simple_momentum.py

from ag_backtester import Engine, EngineConfig
from ag_backtester.data import AggTradesFeed, aggregate_ticks
from ag_backtester.engine import Order

def run_backtest(data_path: str):
    # Load and prepare data
    feed = AggTradesFeed(data_path, tick_size=10.0)
    ticks = aggregate_ticks(feed.load(), bucket_ms=100, tick_size=10.0)

    # Initialize engine
    config = EngineConfig(initial_cash=100_000.0, tick_size=10.0)
    engine = Engine(config)

    # Simple momentum strategy
    price_history = []
    position = 0

    for tick in ticks:
        engine.step_tick(tick)

        price = tick.price_tick_i64 * config.tick_size
        price_history.append(price)

        # Calculate 10-period momentum
        if len(price_history) >= 10:
            momentum = (price - price_history[-10]) / price_history[-10]

            if momentum > 0.01 and position == 0:  # Buy signal
                engine.place_order(Order(
                    order_type='MARKET',
                    side='BUY',
                    qty=0.1
                ))
                position = 1
            elif momentum < -0.01 and position == 1:  # Sell signal
                engine.place_order(Order(
                    order_type='MARKET',
                    side='SELL',
                    qty=0.1
                ))
                position = 0

    return engine.get_history()
```

## AI AGENTS: READ THIS

**⚠️ IMPORTANT: DO NOT TOUCH `core/` (C) AND `crates/` (Rust)**

These directories contain the deterministic execution kernel. You **MUST NOT** modify them.

### What You CAN Do

✅ **Add strategies** in `strategies/`
✅ **Add examples** in `examples/`
✅ **Add user utilities** in `python/ag_backtester/userland/`
✅ **Read documentation** and existing code

### What You CANNOT Do

❌ **Modify `core/`** - C execution engine is off-limits
❌ **Modify `crates/`** - Rust bindings are off-limits
❌ **Change engine semantics** - Execution logic is frozen

### If You Need Help

1. Read this README
2. Check `examples/run_backtest.py` for usage patterns
3. Look at `python/ag_backtester/` for API documentation
4. Ask the human if unclear

## Configuration

### Engine Config

```python
from ag_backtester import EngineConfig

config = EngineConfig(
    initial_cash=100_000.0,  # Starting capital
    maker_fee=0.0001,         # 1 bp (0.01%)
    taker_fee=0.0002,         # 2 bp (0.02%)
    spread_bps=2.0,           # 2 bp spread (applied to each side)
    tick_size=1.0,            # Price quantization
)
```

### Tick Aggregation

```python
from ag_backtester.data import aggregate_ticks

ticks = aggregate_ticks(
    raw_trades,              # Iterator of Tick objects
    bucket_ms=50,            # Time bucket size (milliseconds)
    tick_size=10.0,          # Price quantization
)
```

## Development

### Project Structure

```
ag-kernel/
├── core/                   # C execution kernel
│   ├── engine.h
│   ├── engine.c
│   └── types.h
├── crates/                 # Rust bridge
│   ├── ag-core-sys/        # Unsafe FFI bindings
│   └── ag-core/            # Safe wrapper + PyO3
├── python/
│   └── ag_backtester/      # Python API
│       ├── data/           # Data feeds
│       ├── userland/       # User utilities
│       └── viz/            # Visualization
├── examples/               # Example backtests
├── strategies/             # User strategies
├── outputs/                # Generated reports
└── .claude/
    └── agents/             # Agent definitions
```

### Building

```bash
# Development build (fast compilation)
maturin develop -m crates/ag-core/Cargo.toml

# Release build (optimized)
maturin develop --release -m crates/ag-core/Cargo.toml

# Build wheel for distribution
maturin build --release -m crates/ag-core/Cargo.toml
```

### Testing

```bash
# Run example backtest
python examples/run_backtest.py --input examples/data/btcusdt_aggtrades_sample.csv --auto-ticksize

# Test C kernel (via Rust)
cargo test --release
```

## Performance Details

The engine achieves high throughput through several optimizations:

1. **Batch Processing**: The `step_batch()` method processes arrays of ticks entirely in Rust, eliminating per-tick FFI overhead
2. **Binary Format**: Parquet with ZSTD compression provides 70% size reduction and sub-100ms load times
3. **Zero-Copy Operations**: Direct numpy array access without Python object creation
4. **Columnar Storage**: Struct-of-Arrays layout for cache-friendly processing

**Workflow:**
```bash
# First run: Auto-converts CSV to Parquet
python examples/run_backtest.py --input data.csv --tick-size 10.0
# → Converts to data.parquet (70% smaller)
# → Subsequent runs load from Parquet instantly

# Force CSV mode (for compatibility)
python examples/run_backtest.py --input data.csv --force-csv
```

See `benchmark_v0.py` for detailed performance comparison.

## License

[Your license here]

## Contributing

Contributions welcome! Please:
1. Read the AI AGENTS section above
2. Only modify allowed directories
3. Submit pull requests with clear descriptions

---

**Built with** C, Rust (PyO3), and Python | **Designed for** AI agents and human traders
