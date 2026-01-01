#!/usr/bin/env python3
"""
Example backtest runner - aggTrades mode

Usage:
    python examples/run_backtest.py --input data.csv --mode aggtrades --auto-ticksize
"""
import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from ag_backtester import Engine, EngineConfig, BacktestResult
from ag_backtester.data.aggtrades import AggTradesFeed
from ag_backtester.data.tick_aggregator import aggregate_ticks
from ag_backtester.userland.auto_ticksize import calculate_auto_ticksize
from ag_backtester.viz.tearsheet import generate_tearsheet


def main():
    parser = argparse.ArgumentParser(description='Run backtest on aggTrades data')
    parser.add_argument('--input', required=True, help='Input CSV file')
    parser.add_argument('--mode', default='aggtrades', choices=['aggtrades', 'ohlc', 'ticks'])
    parser.add_argument('--auto-ticksize', action='store_true', help='Auto-calculate tick size')
    parser.add_argument('--tick-size', type=float, help='Manual tick size')
    parser.add_argument('--bucket-ms', type=int, default=50, help='Tick bucketing in ms')
    parser.add_argument('--output', default='outputs/', help='Output directory')
    parser.add_argument('--initial-cash', type=float, default=100_000.0)
    parser.add_argument('--timeframe', default='1h', help='Timeframe for auto tick size')
    parser.add_argument('--target-ticks', type=int, default=20, help='Target ticks per bar')

    args = parser.parse_args()

    # Create output dir
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True, parents=True)

    print(f"Loading data from {args.input}...")

    # Auto tick size from first price if enabled
    if args.auto_ticksize:
        # Quick peek at first price for auto tick size
        import pandas as pd
        df_peek = pd.read_csv(args.input, nrows=1)
        first_price = df_peek['price'].iloc[0]
        tick_size = calculate_auto_ticksize(
            first_price,
            timeframe=args.timeframe,
            target_ticks=args.target_ticks
        )
        print(f"Auto tick size: {tick_size}")
    else:
        tick_size = args.tick_size or 1.0
        print(f"Manual tick size: {tick_size}")

    # Load data with tick size
    feed = AggTradesFeed(args.input, tick_size=tick_size)
    trades = feed.load()

    print(f"Loaded {len(trades)} trades")

    # Aggregate ticks
    print(f"Aggregating ticks (bucket={args.bucket_ms}ms)...")
    ticks = aggregate_ticks(trades, bucket_ms=args.bucket_ms, tick_size=tick_size)
    print(f"Generated {len(ticks)} aggregated ticks")

    # Configure engine
    config = EngineConfig(
        initial_cash=args.initial_cash,
        tick_size=tick_size,
    )

    # Run backtest (simple buy-and-hold for demo)
    print("Running backtest...")
    engine = Engine(config)

    # Simple strategy: buy on first tick, hold
    first_tick = True
    for tick in ticks:
        engine.step_tick(tick)

        # Demo strategy: buy 0.1 BTC on first tick
        if first_tick and tick.side == 'BUY':
            from ag_backtester.engine import Order
            engine.place_order(Order(
                order_type='MARKET',
                side='BUY',
                qty=0.1,
            ))
            first_tick = False

    # Get results
    snapshots = engine.get_history()
    trades_executed = engine.get_trades()

    print(f"Backtest complete: {len(snapshots)} snapshots, {len(trades_executed)} trades")

    # Convert snapshots to dict format for visualization
    snapshots_dict = []
    for s in snapshots:
        snapshots_dict.append({
            'timestamp': s.ts_ms / 1000.0,  # Convert to seconds for datetime
            'equity': s.equity,
            'cash': s.cash,
            'position': s.position,
        })

    # Generate tearsheet
    print("Generating tearsheet...")
    output_png = str(output_dir / 'report.png')
    generate_tearsheet(
        snapshots=snapshots_dict,
        trades=trades_executed,
        output_path=output_png,
    )

    print(f"\nResults saved to {output_dir}/")
    print(f"  - report.png")
    print(f"  - metrics.json")
    print(f"  - equity.csv")


if __name__ == '__main__':
    main()
