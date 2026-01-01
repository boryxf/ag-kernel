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
    from . import _ag_core
except ImportError:
    _ag_core = None

from .engine import Engine, EngineConfig
from .results import BacktestResult

__all__ = ["Engine", "EngineConfig", "BacktestResult", "_ag_core"]
