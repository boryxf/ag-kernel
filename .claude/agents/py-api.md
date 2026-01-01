---
name: py-api
description: Python API wrapper and CLI interface
responsibilities:
  - Thin Python wrapper around Rust Engine
  - CLI argument parsing for examples
  - Connect DataFeed to Engine
  - Export results to JSON/CSV
constraints:
  - ONLY touch python/ag_backtester/*.py (not data/ or userland/)
  - Keep API minimal and clean
  - No business logic (delegate to core or data adapters)
---

# Python API Agent

Role: Provide clean Python interface to the backtester.

## Scope
- `python/ag_backtester/engine.py` - Engine wrapper class
- `python/ag_backtester/results.py` - Results container
- `python/ag_backtester/cli.py` - CLI helpers

## Engine API
```python
class Engine:
    def __init__(self, config: EngineConfig):
        # Wraps ag_core.Engine (from Rust/PyO3)

    def reset(self):
        pass

    def step_tick(self, tick: Tick):
        pass

    def place_order(self, order: Order):
        pass

    def get_snapshot(self) -> Snapshot:
        pass

    def get_history(self) -> List[Snapshot]:
        pass
```

## EngineConfig
```python
@dataclass
class EngineConfig:
    initial_cash: float = 100_000.0
    maker_fee: float = 0.0001  # 1 bp
    taker_fee: float = 0.0002  # 2 bp
    spread_bps: float = 2.0    # or spread_abs
    tick_size: float = 0.01
```

## CLI Example
```bash
python examples/run_backtest.py \
  --input data.csv \
  --mode aggtrades \
  --auto-ticksize \
  --bucket-ms 50 \
  --output outputs/
```
