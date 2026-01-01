"""Engine wrapper - thin Python layer over Rust/C core"""
from dataclasses import dataclass
from typing import List, Optional
import warnings


@dataclass
class EngineConfig:
    """Configuration for the backtesting engine"""
    initial_cash: float = 100_000.0
    maker_fee: float = 0.0001  # 1 bp
    taker_fee: float = 0.0002  # 2 bp
    spread_bps: float = 2.0    # Spread in basis points
    spread_abs: Optional[float] = None  # Or absolute spread
    tick_size: float = 0.01


@dataclass
class Tick:
    """Tick event"""
    ts_ms: int
    price_tick_i64: int  # Price as integer ticks
    qty: float
    side: str  # 'BUY' or 'SELL'


@dataclass
class Order:
    """Order request"""
    order_type: str  # 'MARKET' or 'LIMIT'
    side: str  # 'BUY' or 'SELL'
    qty: float
    price: Optional[float] = None
    order_id: Optional[int] = None


@dataclass
class Snapshot:
    """Engine state snapshot"""
    ts_ms: int
    cash: float
    position: float
    avg_entry_price: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float


class Engine:
    """Main backtesting engine - wraps ag_core Rust extension"""

    def __init__(self, config: EngineConfig):
        self.config = config
        self._history: List[Snapshot] = []
        self._trades: List[dict] = []

        # Try to import Rust extension
        try:
            from ag_backtester import _ag_core
            self._core = _ag_core.Engine(
                initial_cash=config.initial_cash,
                maker_fee=config.maker_fee,
                taker_fee=config.taker_fee,
                spread_bps=config.spread_bps,
                tick_size=config.tick_size,
            )
        except (ImportError, AttributeError) as e:
            warnings.warn(f"Rust core not available ({e}), using stub")
            self._core = None
            self._cash = config.initial_cash
            self._position = 0.0
            self._avg_entry = 0.0

    def reset(self):
        """Reset engine to initial state"""
        if self._core:
            self._core.reset()
        else:
            self._cash = self.config.initial_cash
            self._position = 0.0
        self._history.clear()
        self._trades.clear()

    def step_tick(self, tick: Tick):
        """Process a tick event"""
        if self._core:
            self._core.step_tick(
                tick.ts_ms,
                tick.price_tick_i64,
                tick.qty,
                tick.side,
            )
        # Record snapshot
        snapshot = self.get_snapshot()
        snapshot.ts_ms = tick.ts_ms
        self._history.append(snapshot)

    def step_batch(self, timestamps, price_ticks, qtys, sides):
        """
        Process a batch of ticks efficiently.

        Args:
            timestamps: numpy array of int64 timestamps
            price_ticks: numpy array of int64 price ticks
            qtys: numpy array of float64 quantities
            sides: numpy array of uint8 sides (0=BUY, 1=SELL)
        """
        if self._core:
            self._core.step_batch(
                timestamps.tolist(),
                price_ticks.tolist(),
                qtys.tolist(),
                sides.tolist()
            )
        else:
            # Stub: process one by one
            for i in range(len(timestamps)):
                # Update stub state
                pass

    def place_order(self, order: Order):
        """Place an order"""
        if self._core:
            self._core.place_order(
                order.order_type,
                order.side,
                order.qty,
                order.price or 0.0,
            )
        else:
            # Stub: immediate execution
            pass

    def get_snapshot(self) -> Snapshot:
        """Get current engine state"""
        if self._core:
            data = self._core.get_snapshot()
            return Snapshot(
                ts_ms=0,  # Will be set by caller
                cash=data['cash'],
                position=data['position'],
                avg_entry_price=data['avg_entry_price'],
                realized_pnl=data['realized_pnl'],
                unrealized_pnl=data['unrealized_pnl'],
                equity=data['equity'],
            )
        else:
            return Snapshot(
                ts_ms=0,
                cash=self._cash,
                position=self._position,
                avg_entry_price=self._avg_entry,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                equity=self._cash,
            )

    def get_history(self) -> List[Snapshot]:
        """Get full snapshot history"""
        return self._history.copy()

    def get_trades(self) -> List[dict]:
        """Get executed trades"""
        return self._trades.copy()
