"""Tests for batch processing mode.

Verifies that step_batch produces identical results to tick-by-tick processing.
"""

import pytest
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'python'))

from ag_backtester.engine import Engine, EngineConfig, Tick


class TestBatchProcessing:
    """Test batch processing matches tick-by-tick processing."""

    def test_batch_vs_tick_by_tick_identical(self):
        """Verify batch mode produces same results as tick-by-tick."""
        # Create two engines with identical config
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=2.0,
            tick_size=0.01
        )

        engine_tick = Engine(config)
        engine_batch = Engine(config)

        # Create test data
        timestamps = [1000, 1001, 1002, 1003, 1004]
        price_ticks = [10000, 10010, 10005, 10020, 10015]
        qtys = [1.5, 2.0, 1.8, 2.2, 1.9]
        sides = [0, 1, 0, 1, 0]  # 0=BUY, 1=SELL

        # Process tick-by-tick
        for i in range(len(timestamps)):
            side_str = 'BUY' if sides[i] == 0 else 'SELL'
            engine_tick.step_tick(Tick(
                ts_ms=timestamps[i],
                price_tick_i64=price_ticks[i],
                qty=qtys[i],
                side=side_str
            ))

        # Process in batch
        engine_batch.step_batch(
            timestamps=timestamps,
            price_ticks=price_ticks,
            qtys=qtys,
            sides=sides
        )

        # Compare snapshots
        snap_tick = engine_tick.get_snapshot()
        snap_batch = engine_batch.get_snapshot()

        assert abs(snap_tick.cash - snap_batch.cash) < 0.001
        assert abs(snap_tick.position - snap_batch.position) < 0.000001
        assert abs(snap_tick.realized_pnl - snap_batch.realized_pnl) < 0.001
        assert abs(snap_tick.unrealized_pnl - snap_batch.unrealized_pnl) < 0.001

    def test_batch_with_orders(self):
        """Test batch processing with placed orders."""
        from ag_backtester.engine import Order

        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Place a limit buy order at 99.00
        engine.place_order(Order(order_type='LIMIT', side='BUY', qty=1.0, price=99.0))

        # Process batch where price crosses the limit
        timestamps = [1000, 1001, 1002]
        price_ticks = [10000, 9900, 9850]  # 100.00 -> 99.00 -> 98.50
        qtys = [2.0, 2.0, 2.0]
        sides = [1, 1, 1]  # All SELL

        engine.step_batch(timestamps, price_ticks, qtys, sides)

        snapshot = engine.get_snapshot()

        # Order should have filled at 99.00
        assert abs(snapshot.position - 1.0) < 0.000001
        assert abs(snapshot.avg_entry_price - 9900.0) < 1.0

    def test_large_batch_performance(self):
        """Test processing a large batch of ticks."""
        config = EngineConfig(
            initial_cash=100000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=1.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Generate 1000 ticks
        n = 1000
        timestamps = list(range(1000, 1000 + n))
        # Simulate random walk
        np.random.seed(42)
        price_changes = np.random.randn(n) * 10
        price_ticks = [10000]
        for change in price_changes[1:]:
            price_ticks.append(int(price_ticks[-1] + change))

        qtys = np.random.uniform(0.1, 2.0, n).tolist()
        sides = np.random.randint(0, 2, n).tolist()

        # Should complete without errors
        engine.step_batch(timestamps, price_ticks, qtys, sides)

        snapshot = engine.get_snapshot()
        # Just verify it completes and produces valid output
        assert isinstance(snapshot.cash, float)
        assert isinstance(snapshot.position, float)

    def test_batch_scaling_correctness(self):
        """Test that batch processing correctly scales quantities."""
        from ag_backtester.engine import Order

        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Place order first
        engine.place_order(Order(order_type='MARKET', side='BUY', qty=2.5, price=100.0))

        # Process batch to fill order
        timestamps = [1000, 1001]
        price_ticks = [10000, 10000]
        qtys = [3.0, 3.0]
        sides = [1, 1]  # SELL

        engine.step_batch(timestamps, price_ticks, qtys, sides)

        snapshot = engine.get_snapshot()

        # Verify notional calculation is correct
        # Notional = 2.5 * 100.0 = 250.0
        # Fee = 250.0 * 0.0002 = 0.05
        # Cash = 10000 - 250 - 0.05 = 9749.95
        assert abs(snapshot.cash - 9749.95) < 0.01
        assert abs(snapshot.position - 2.5) < 0.000001

    def test_empty_batch(self):
        """Test that empty batch doesn't crash."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        # Process empty batch
        engine.step_batch([], [], [], [])

        snapshot = engine.get_snapshot()
        # Should remain at initial state
        assert abs(snapshot.cash - 10000.0) < 0.01
        assert abs(snapshot.position) < 0.000001

    def test_batch_mismatched_lengths_error(self):
        """Test that mismatched array lengths raise error."""
        config = EngineConfig(
            initial_cash=10000.0,
            maker_fee=0.0001,
            taker_fee=0.0002,
            spread_bps=0.0,
            tick_size=0.01
        )
        engine = Engine(config)

        with pytest.raises(Exception):
            # Mismatched lengths should raise error
            engine.step_batch(
                timestamps=[1000, 1001],
                price_ticks=[10000],  # Wrong length
                qtys=[1.0, 1.0],
                sides=[0, 0]
            )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
