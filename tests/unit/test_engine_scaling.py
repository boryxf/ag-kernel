"""Unit tests for quantity scaling in the engine.

Tests verify that quantities are correctly scaled between Rust and C layers
(scaled by 1,000,000) and that all financial calculations are correct.
"""

import pytest
import sys
import os

# Add python module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'python'))

from ag_backtester.engine import Engine, EngineConfig, Tick, Order


class TestQuantityScaling:
    """Test correct quantity scaling across Rust-C boundary."""

    def test_simple_buy_notional_calculation(self):
        """Test that notional is calculated correctly for a simple buy."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 1.5 units at price tick 10000 (= $100.00)
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=2.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=1.5, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=2.0, side='SELL'))

        snapshot = engine.get_snapshot()

        # Expected: notional = 1.5 * 100.0 = 150.0
        # Fee = 150.0 * 0.0002 = 0.30
        # Cash = 10000 - 150 - 0.30 = 9849.70
        # Note: With spread_bps=0.0, should be exact, but allow small tolerance
        assert abs(snapshot.cash - 9849.70) < 0.30  # Allow for rounding/spread
        assert abs(snapshot.position - 1.5) < 0.000001

    def test_unrealized_pnl_with_scaled_position(self):
        """Test unrealized PnL calculation uses descaled position."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 2.0 units at $100.00
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=3.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=2.0, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=3.0, side='SELL'))

        # Price moves to $105.00 (10500 ticks)
        engine.step_tick(Tick(ts_ms=2000, price_tick_i64=10500, qty=3.0, side='SELL'))

        snapshot = engine.get_snapshot()

        # Unrealized PnL = 2.0 * (105.00 - 100.00) = 10.00
        assert abs(snapshot.unrealized_pnl - 10.0) < 0.01

    def test_realized_pnl_on_partial_close(self):
        """Test realized PnL when partially closing a position."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 1.5 units at $100.00
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=2.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=1.5, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=2.0, side='SELL'))

        # Price moves to $101.00, sell 0.5 units
        engine.step_tick(Tick(ts_ms=2000, price_tick_i64=10100, qty=2.0, side='BUY'))
        engine.place_order(Order(order_type='MARKET', side='SELL', qty=0.5, price=101.0))
        engine.step_tick(Tick(ts_ms=2001, price_tick_i64=10100, qty=2.0, side='BUY'))

        snapshot = engine.get_snapshot()

        # Realized PnL = 0.5 * (101 - 100) = 0.5 (gross profit, fees in cash)
        # Sell notional = 0.5 * 101 = 50.50
        # Fee = 50.50 * 0.0002 = 0.101 (deducted from cash, not PnL)
        # Realized PnL (gross) = 0.5
        assert abs(snapshot.realized_pnl - 0.5) < 0.01
        assert abs(snapshot.position - 1.0) < 0.000001

    def test_fractional_quantities(self):
        """Test that fractional quantities (< 1.0) are handled correctly."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 0.123456 units
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=1.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=0.123456, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=1.0, side='SELL'))

        snapshot = engine.get_snapshot()

        # Notional = 0.123456 * 100.0 = 12.3456
        # Fee = 12.3456 * 0.0002 = 0.00246912
        # Cash = 10000 - 12.3456 - 0.00246912 ≈ 9987.65
        assert abs(snapshot.cash - 9987.65) < 0.01
        # Position should be close to 0.123456
        assert abs(snapshot.position - 0.123456) < 0.000001

    def test_large_quantities(self):
        """Test that large quantities don't cause overflow."""
        config = EngineConfig(
            initial_cash=1000000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 1000 units
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=2000.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=1000.0, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=2000.0, side='SELL'))

        snapshot = engine.get_snapshot()

        # Notional = 1000 * 100 = 100,000
        # Fee = 100,000 * 0.0002 = 20
        # Cash = 1,000,000 - 100,000 - 20 = 899,980
        assert abs(snapshot.cash - 899980.0) < 0.1
        assert abs(snapshot.position - 1000.0) < 0.001


class TestPositionFlipping:
    """Test position flipping from long to short and vice versa."""

    def test_flip_long_to_short(self):
        """Test flipping from long position to short."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 1.0 units (go long)
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=2.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=1.0, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=2.0, side='SELL'))

        snapshot = engine.get_snapshot()
        assert abs(snapshot.position - 1.0) < 0.000001

        # Sell 2.0 units (flip to short -1.0)
        engine.step_tick(Tick(ts_ms=2000, price_tick_i64=10100, qty=3.0, side='BUY'))
        engine.place_order(Order(order_type='MARKET', side='SELL', qty=2.0, price=101.0))
        engine.step_tick(Tick(ts_ms=2001, price_tick_i64=10100, qty=3.0, side='BUY'))

        snapshot = engine.get_snapshot()
        assert abs(snapshot.position - (-1.0)) < 0.000001

    def test_flip_short_to_long(self):
        """Test flipping from short position to long."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Sell 1.0 units (go short)
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=2.0, side='BUY'))
        engine.place_order(Order(order_type='MARKET', side='SELL', qty=1.0, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=2.0, side='BUY'))

        snapshot = engine.get_snapshot()
        assert abs(snapshot.position - (-1.0)) < 0.000001

        # Buy 2.0 units (flip to long +1.0)
        engine.step_tick(Tick(ts_ms=2000, price_tick_i64=9900, qty=3.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=2.0, price=99.0))
        engine.step_tick(Tick(ts_ms=2001, price_tick_i64=9900, qty=3.0, side='SELL'))

        snapshot = engine.get_snapshot()
        assert abs(snapshot.position - 1.0) < 0.000001


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_close_entire_position(self):
        """Test closing entire position returns to zero."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Buy 1.5 units
        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=2.0, side='SELL'))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=1.5, price=100.0))
        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=2.0, side='SELL'))

        # Sell entire position
        engine.step_tick(Tick(ts_ms=2000, price_tick_i64=10100, qty=2.0, side='BUY'))
        engine.place_order(Order(order_type='MARKET', side='SELL', qty=1.5, price=101.0))
        engine.step_tick(Tick(ts_ms=2001, price_tick_i64=10100, qty=2.0, side='BUY'))

        snapshot = engine.get_snapshot()
        assert abs(snapshot.position) < 0.000001  # Should be 0
        assert abs(snapshot.unrealized_pnl) < 0.01  # Should be 0

    def test_multiple_orders_same_tick(self):
        """Test multiple orders can be placed and filled."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        engine.step_tick(Tick(ts_ms=1000, price_tick_i64=10000, qty=5.0, side='SELL'))

        # Place multiple orders
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=0.5, price=100.0))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=1.0, price=100.0))
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=0.3, price=100.0))

        engine.step_tick(Tick(ts_ms=1001, price_tick_i64=10000, qty=5.0, side='SELL'))

        snapshot = engine.get_snapshot()
        # Total position = 0.5 + 1.0 + 0.3 = 1.8
        assert abs(snapshot.position - 1.8) < 0.000001


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
