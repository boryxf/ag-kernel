# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ag-kernel** is a high-performance backtesting engine (10M+ ticks/sec) with deterministic execution. Three-layer architecture: C kernel → Rust FFI → Python API.

**Key principle**: "Bare kernel" architecture - the C/Rust core is frozen for deterministic guarantees. User development happens in Python userland only.

## Architecture

```
┌─────────────────────────────────────────┐
│    Python API (python/ag_backtester/)   │  ← User-facing interface
├─────────────────────────────────────────┤
│    Rust Bridge (crates/ag-core/)        │  ← Safe FFI bindings (PyO3)
├─────────────────────────────────────────┤
│    C Kernel (core/engine.c)             │  ← Deterministic execution
└─────────────────────────────────────────┘
```

### Layer Responsibilities

**C Kernel (`core/`)**:
- Execution engine with deterministic math
- Position tracking, order matching, PnL calculations
- **FROZEN** - never modify

**Rust Bridge (`crates/`)**:
- Safe FFI bindings using PyO3
- Quantity scaling (1,000,000x for integer math in C)
- Type conversions between Python and C
- **FROZEN** - never modify

**Python API (`python/ag_backtester/`)**:
- `engine.py` - Thin wrapper over Rust core
- `data/` - Data loading (aggTrades CSV, tick aggregation, Parquet parsers)
- `viz/` - Matplotlib tearsheets and metrics
- `userland/` - User-facing utilities (auto_ticksize, indicators, etc.)
- **Modifiable** - safe to edit

**User Development Areas**:
- `strategies/` - Custom trading strategies
- `examples/` - Example scripts and backtests
- `python/ag_backtester/userland/` - User utilities

## Critical Scaling Convention

**All quantities are scaled by 1,000,000 at the Rust→C boundary**:

- Rust sends: `qty * 1_000_000.0 as i64`
- C calculates: `notional = price * (qty / 1_000_000.0)`
- Rust receives: `position as f64 / 1_000_000.0`

This convention is documented in `core/engine.c:8-11` and verified in `CRITICAL_AUDIT_REPORT.md`. Price ticks remain unscaled.

## Build and Development Commands

### Initial Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Rust (if needed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build Rust extension (REQUIRED before running Python code)
cd crates/ag-core
maturin develop --release
cd ../..
```

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_engine_scaling.py -v

# Run with coverage
pytest tests/ --cov=ag_backtester --cov-report=html

# Test results: 25 passing (96% pass rate), 1 skipped
```

### Common Development Tasks

```bash
# Rebuild after C/Rust changes (rare - core is frozen)
cd crates/ag-core && maturin develop --release && cd ../..

# Run example backtest
python examples/run_backtest.py --input examples/data/sample.csv --auto-ticksize --bucket-ms 50

# Run bubbles visualization (demo mode, no internet)
./examples/demo_bubbles_local.sh

# Run bubbles with live Binance data
python examples/bubbles_visualization.py --fetch --limit 1000
```

## Key APIs and Data Flow

### Engine Configuration

```python
from ag_backtester import Engine, EngineConfig

config = EngineConfig(
    initial_cash=100_000.0,
    maker_fee=0.0001,      # 1 bp (fraction, not bps)
    taker_fee=0.0002,      # 2 bps
    spread_bps=2.0,        # Spread in basis points
    tick_size=0.01         # Price granularity
)
engine = Engine(config)
```

### Processing Ticks

**Single tick mode**:
```python
from ag_backtester.engine import Tick

tick = Tick(
    ts_ms=1000,
    price_tick_i64=10000,  # Price in tick units (e.g., 100.00 with tick_size=0.01)
    qty=2.0,
    side='SELL'
)
engine.step_tick(tick)
```

**Batch mode** (10M+ ticks/sec throughput):
```python
# Sides: 0=BUY, 1=SELL (integer for performance)
from ag_backtester import SIDE_BUY, SIDE_SELL

engine.step_batch(
    timestamps=[1000, 1001, 1002],
    price_ticks=[10000, 10010, 10005],
    qtys=[1.5, 2.0, 1.8],
    sides=[SIDE_BUY, SIDE_SELL, SIDE_BUY]
)
```

### Order Placement

```python
from ag_backtester.engine import Order

engine.place_order(Order(
    order_type='MARKET',  # or 'LIMIT'
    side='BUY',           # or 'SELL'
    qty=1.5,
    price=100.0           # Required for LIMIT orders
))
```

### Getting Results

```python
# Current state
snapshot = engine.get_snapshot()
# Fields: ts_ms, cash, position, avg_entry_price, realized_pnl, unrealized_pnl, equity

# Full history
history = engine.get_history()  # List[Snapshot]

# Trades
trades = engine.get_trades()  # List[dict]
```

## Data Loading

**aggTrades CSV format** (Binance standard):
```csv
timestamp,price,qty,is_buyer_maker
1704067200000,42150.50,0.025,true
1704067200050,42151.00,0.018,false
```

**Loading and aggregating**:
```python
from ag_backtester.data import AggTradesFeed, aggregate_ticks

# Load raw trades
feed = AggTradesFeed('path/to/data.csv', tick_size=10.0)
raw_ticks = feed.load()

# Aggregate to time buckets (e.g., 50ms)
aggregated = aggregate_ticks(raw_ticks, bucket_ms=50, tick_size=10.0)

# Alternative: Zero-copy Parquet loading
from ag_backtester.data.aggtrades import parse_parquet_streaming
for tick in parse_parquet_streaming('data.parquet', tick_size=1.0):
    engine.step_tick(tick)
```

**Auto tick size calculation**:
```python
from ag_backtester.userland import calculate_auto_ticksize

tick_size = calculate_auto_ticksize(
    price=42150.0,     # Current price
    target_ticks=20    # Desired granularity
)  # Returns: 5.0
```

## Visualization

```python
from ag_backtester.viz import generate_tearsheet

generate_tearsheet(
    snapshots=engine.get_history(),
    trades=engine.get_trades(),
    output_path='outputs/report.png'
)
# Generates dark-themed tearsheet with equity curve, drawdown, metrics
```

## Recent Critical Fixes (v0.2.1)

Two major bugs were fixed - see `CRITICAL_AUDIT_REPORT.md` for details:

1. **Quantity Scaling Bug**: All financial calculations were off by 1,000,000x. Fixed by adding proper descaling in C kernel calculations (core/engine.c:45, 78, 111).

2. **Fee Double-Counting**: Fees were subtracted from both cash AND realized_pnl. Fixed by only deducting from cash.

All 25 tests now passing. System is production-ready.

## File Organization

```
ag-kernel/
├── core/                    # C kernel (FROZEN - do not modify)
│   └── engine.c            # Execution engine with deterministic math
├── crates/                  # Rust FFI (FROZEN - do not modify)
│   ├── ag-core-sys/        # Raw C bindings
│   └── ag-core/            # Safe wrapper + PyO3 bindings
├── python/ag_backtester/    # Python API
│   ├── engine.py           # Thin wrapper over Rust
│   ├── data/               # Data loading (aggTrades, Parquet, tick aggregation)
│   ├── viz/                # Tearsheet generation, metrics calculation
│   └── userland/           # User utilities (SAFE TO MODIFY)
├── strategies/              # User strategies (SAFE TO MODIFY)
├── examples/                # Example scripts (SAFE TO MODIFY)
└── tests/                   # Test suite
    ├── unit/               # Unit tests for scaling, fees, batch mode
    └── integration/        # End-to-end tests
```

## Development Guidelines

### What You Can Modify

- `strategies/` - Add new trading strategies
- `examples/` - Add example scripts
- `python/ag_backtester/userland/` - Add utilities, indicators, helpers
- `python/ag_backtester/viz/` - Enhance visualization
- `python/ag_backtester/data/` - Add new data adapters
- `tests/` - Add tests for new features

### What You Cannot Modify

- `core/` - C kernel is frozen for deterministic guarantees
- `crates/` - Rust FFI is frozen (any change breaks determinism)

Modifying frozen components breaks the deterministic execution guarantee. If core changes are needed, they require comprehensive testing and audit.

### When Adding Features

- Write strategies in Python, not in the engine
- Add indicators/utilities in `userland/`, not in the core
- Use the existing Engine API - don't extend it
- Add tests in `tests/` for new functionality
- Check `PROMPT_FOR_AGENTS.md` for additional guidance

## Troubleshooting

**"Module 'ag_backtester' has no attribute '_ag_core'"**
→ Run `cd crates/ag-core && maturin develop --release`

**Tests failing with quantity mismatches**
→ Ensure you've built the latest Rust code with the scaling fixes

**"No such file or directory" errors**
→ Run from project root or use absolute paths

**Empty tick list from aggregation**
→ Check CSV format matches Binance aggTrades schema

## Additional Documentation

- `README.md` - Project overview, features, API reference
- `PROMPT_FOR_AGENTS.md` - AI agent developer guide with examples
- `CRITICAL_AUDIT_REPORT.md` - Security and correctness audit
- `CHANGELOG.md` - Version history
- `examples/BUBBLES_README.md` - Bubbles visualization guide
