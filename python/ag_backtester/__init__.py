"""
ag-backtester: Lightweight backtesting engine

Architecture:
- C kernel (core/) - deterministic execution engine
- Rust bridge (crates/) - safe FFI bindings
- Python API - user-facing interface

Modules:
- engine: Core Engine and EngineConfig classes
- results: BacktestResult container
- parallel: Multi-threaded/multi-process backtest runners
- analytics: Candle, volume, and volatility analysis tools
"""

__version__ = "0.1.0"

# Import Rust extension if available
try:
    import _ag_core
except ImportError:
    _ag_core = None

from .engine import Engine, EngineConfig
from .results import BacktestResult

# Parallel execution utilities
from .parallel import (
    run_parallel_backtests,
    run_monte_carlo,
    run_parameter_sweep,
)

# Side constants for batch processing
SIDE_BUY = 0
SIDE_SELL = 1

__all__ = [
    # Core classes
    "Engine",
    "EngineConfig",
    "BacktestResult",
    "_ag_core",
    # Side constants
    "SIDE_BUY",
    "SIDE_SELL",
    # Parallel execution
    "run_parallel_backtests",
    "run_monte_carlo",
    "run_parameter_sweep",
]
