"""
Backwards compatibility tests for ag-kernel v0.3.0.

These tests ensure that ALL existing APIs continue to work
after performance optimizations.
"""

import pytest
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))

from ag_backtester import Engine, EngineConfig, SIDE_BUY, SIDE_SELL
from ag_backtester.engine import Tick, Order, Snapshot


class TestEngineBackwardsCompat:
    """Test that Engine API remains unchanged."""

    def test_engine_config_default_values(self):
        """EngineConfig should work with default values."""
        config = EngineConfig()
        assert config.initial_cash == 100_000.0
        assert config.maker_fee == 0.0001
        assert config.taker_fee == 0.0002
        assert config.tick_size == 0.01

    def test_engine_config_custom_values(self):
        """EngineConfig should accept custom values."""
        config = EngineConfig(
            initial_cash=50_000.0,
            maker_fee=0.0005,
            taker_fee=0.001,
            spread_bps=3.0,
            tick_size=0.1
        )
        assert config.initial_cash == 50_000.0
        assert config.tick_size == 0.1

    def test_engine_creation(self):
        """Engine should be creatable with config."""
        config = EngineConfig()
        engine = Engine(config)
        assert engine is not None
        assert engine.config == config

    def test_engine_reset(self):
        """Engine.reset() should work."""
        config = EngineConfig(initial_cash=10_000.0)
        engine = Engine(config)

        # Process some data
        tick = Tick(ts_ms=1000, price_tick_i64=100, qty=1.0, side='BUY')
        engine.step_tick(tick)

        # Reset
        engine.reset()

        # Should be back to initial state
        snap = engine.get_snapshot()
        assert snap['cash'] == 10_000.0 or abs(snap['cash'] - 10_000.0) < 0.01

    def test_tick_dataclass(self):
        """Tick dataclass should work."""
        tick = Tick(
            ts_ms=1000,
            price_tick_i64=42000,
            qty=0.5,
            side='BUY'
        )
        assert tick.ts_ms == 1000
        assert tick.price_tick_i64 == 42000
        assert tick.qty == 0.5
        assert tick.side == 'BUY'

    def test_order_dataclass(self):
        """Order dataclass should work."""
        order = Order(
            order_type='MARKET',
            side='SELL',
            qty=1.0,
            price=100.0
        )
        assert order.order_type == 'MARKET'
        assert order.side == 'SELL'
        assert order.qty == 1.0

    def test_step_tick_string_side(self):
        """step_tick should accept string sides (BUY/SELL)."""
        config = EngineConfig(tick_size=1.0)
        engine = Engine(config)

        # BUY side
        tick_buy = Tick(ts_ms=1000, price_tick_i64=100, qty=0.1, side='BUY')
        engine.step_tick(tick_buy)

        # SELL side
        tick_sell = Tick(ts_ms=2000, price_tick_i64=100, qty=0.1, side='SELL')
        engine.step_tick(tick_sell)

        # Should not raise

    def test_step_batch_lists(self):
        """step_batch should accept Python lists."""
        config = EngineConfig(tick_size=1.0)
        engine = Engine(config)

        timestamps = [1000, 2000, 3000]
        price_ticks = [100, 101, 102]
        qtys = [0.1, 0.2, 0.3]
        sides = [0, 1, 0]  # 0=BUY, 1=SELL

        engine.step_batch(timestamps, price_ticks, qtys, sides)
        # Should not raise

    def test_step_batch_numpy(self):
        """step_batch should accept numpy arrays (converted to list)."""
        config = EngineConfig(tick_size=1.0)
        engine = Engine(config)

        timestamps = np.array([1000, 2000, 3000], dtype=np.int64)
        price_ticks = np.array([100, 101, 102], dtype=np.int64)
        qtys = np.array([0.1, 0.2, 0.3], dtype=np.float64)
        sides = np.array([0, 1, 0], dtype=np.uint8)

        # Current API converts to list internally
        engine.step_batch(
            timestamps.tolist(),
            price_ticks.tolist(),
            qtys.tolist(),
            sides.tolist()
        )
        # Should not raise

    def test_place_order_market(self):
        """place_order should work with MARKET orders."""
        config = EngineConfig(tick_size=1.0, initial_cash=100_000.0)
        engine = Engine(config)

        # Need a tick first to set price
        tick = Tick(ts_ms=1000, price_tick_i64=100, qty=1.0, side='SELL')
        engine.step_tick(tick)

        # Place market order
        order = Order(order_type='MARKET', side='BUY', qty=0.1)
        engine.place_order(order)

        # Process another tick to fill order
        tick2 = Tick(ts_ms=2000, price_tick_i64=100, qty=1.0, side='SELL')
        engine.step_tick(tick2)

    def test_get_snapshot_returns_dict(self):
        """get_snapshot should return dict with expected keys."""
        config = EngineConfig()
        engine = Engine(config)

        snap = engine.get_snapshot()

        # Must have these keys
        assert 'cash' in snap
        assert 'position' in snap
        assert 'realized_pnl' in snap
        assert 'unrealized_pnl' in snap
        assert 'equity' in snap

        # Values should be numbers
        assert isinstance(snap['cash'], (int, float))
        assert isinstance(snap['position'], (int, float))

    def test_get_history_returns_list(self):
        """get_history should return list of snapshots."""
        config = EngineConfig(tick_size=1.0)
        engine = Engine(config)

        # Process some ticks
        for i in range(5):
            tick = Tick(ts_ms=i*1000, price_tick_i64=100+i, qty=0.1, side='BUY')
            engine.step_tick(tick)

        history = engine.get_history()

        assert isinstance(history, list)
        assert len(history) == 5

    def test_side_constants(self):
        """SIDE_BUY and SIDE_SELL constants should exist."""
        assert SIDE_BUY == 0
        assert SIDE_SELL == 1


class TestDataBackwardsCompat:
    """Test that data loading API remains unchanged."""

    def test_tick_aggregator_import(self):
        """tick_aggregator should be importable."""
        from ag_backtester.data.tick_aggregator import aggregate_ticks
        assert callable(aggregate_ticks)

    def test_aggtrades_feed_import(self):
        """AggTradesFeed should be importable."""
        from ag_backtester.data.aggtrades import AggTradesFeed
        assert AggTradesFeed is not None

    def test_feeds_tick_class(self):
        """feeds.Tick should be importable."""
        from ag_backtester.data.feeds import Tick
        tick = Tick(ts_ms=1000, price_tick_i64=100, qty=0.5, side='BUY')
        assert tick.ts_ms == 1000


class TestNewAPIsExist:
    """Test that new optimized APIs are available."""

    def test_fast_aggregator_exists(self):
        """fast_aggregator module should exist."""
        try:
            from ag_backtester.data.fast_aggregator import aggregate_ticks_polars
            assert callable(aggregate_ticks_polars)
        except ImportError:
            pytest.skip("fast_aggregator not yet implemented")

    def test_parquet_loader_exists(self):
        """parquet_loader module should exist."""
        try:
            from ag_backtester.data.parquet_loader import load_parquet_mmap
            assert callable(load_parquet_mmap)
        except ImportError:
            pytest.skip("parquet_loader not yet implemented")

    def test_parallel_module_exists(self):
        """parallel module should exist."""
        try:
            from ag_backtester.parallel import run_parallel_backtests
            assert callable(run_parallel_backtests)
        except ImportError:
            pytest.skip("parallel module not yet implemented")

    def test_analytics_module_exists(self):
        """analytics module should exist."""
        try:
            from ag_backtester.analytics import ticks_to_candles
            assert callable(ticks_to_candles)
        except ImportError:
            pytest.skip("analytics module not yet implemented")


class TestScalingConsistency:
    """Test that quantity scaling is consistent across APIs."""

    def test_batch_vs_single_tick_consistency(self):
        """Batch and single-tick processing should give same results."""
        config = EngineConfig(tick_size=1.0, initial_cash=10000.0)

        # Single tick processing
        engine1 = Engine(config)
        ticks = [
            Tick(ts_ms=1000, price_tick_i64=100, qty=0.5, side='BUY'),
            Tick(ts_ms=2000, price_tick_i64=101, qty=0.3, side='SELL'),
            Tick(ts_ms=3000, price_tick_i64=99, qty=0.4, side='BUY'),
        ]
        for t in ticks:
            engine1.step_tick(t)
        snap1 = engine1.get_snapshot()

        # Batch processing
        engine2 = Engine(config)
        engine2.step_batch(
            [1000, 2000, 3000],
            [100, 101, 99],
            [0.5, 0.3, 0.4],
            [0, 1, 0]
        )
        snap2 = engine2.get_snapshot()

        # Should have same cash
        assert abs(snap1['cash'] - snap2['cash']) < 0.0001, \
            f"Cash mismatch: single={snap1['cash']}, batch={snap2['cash']}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
