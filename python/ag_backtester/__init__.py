"""
ag-backtester: Lightweight backtesting engine

Architecture:
- C kernel (core/) - deterministic execution engine
- Rust bridge (crates/) - safe FFI bindings
- Python API - user-facing interface
"""

__version__ = "0.1.0"

# Import Rust extension if available
try:
    import _ag_core
except ImportError:
    _ag_core = None

from .engine import Engine, EngineConfig
from .results import BacktestResult

# Side constants for batch processing
SIDE_BUY = 0
SIDE_SELL = 1

__all__ = ["Engine", "EngineConfig", "BacktestResult", "_ag_core", "SIDE_BUY", "SIDE_SELL"]
