#!/usr/bin/env python3
"""
Bubbles Visualization for BTCUSDT Orders
=========================================

This script:
1. Fetches real BTCUSDT aggTrades data from Binance Open API
2. Runs a backtest through ag-kernel engine
3. Visualizes all orders as bubbles in matplotlib
   - Bubble size = order quantity
   - Color = BUY (green) / SELL (red)
   - Position on chart = time & price

Usage:
    python examples/bubbles_visualization.py --limit 1000 --strategy demo
    python examples/bubbles_visualization.py --csv path/to/data.csv
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from ag_backtester import Engine, EngineConfig
from ag_backtester.data import AggTradesFeed, aggregate_ticks
from ag_backtester.engine import Order, Tick
from ag_backtester.userland import calculate_auto_ticksize


@dataclass
class OrderRecord:
    """Record of an executed order for visualization"""

    timestamp: int  # ms
    price: float
    qty: float
    side: str  # 'BUY' or 'SELL'
    order_type: str  # 'MARKET' or 'LIMIT'
    fee: float


def fetch_binance_aggtrades(
    symbol: str = "BTCUSDT",
    limit: int = 1000,
    start_time: int = None,
    end_time: int = None,
) -> pd.DataFrame:
    """
    Fetch aggregated trades from Binance Public API

    API Docs: https://binance-docs.github.io/apidocs/spot/en/#compressed-aggregate-trades-list
    """
    url = "https://api.binance.com/api/v3/aggTrades"

    params = {
        "symbol": symbol,
        "limit": min(limit, 1000),  # Max 1000 per request
    }

    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    print(f"📡 Fetching {limit} aggTrades for {symbol} from Binance...")

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data:
            raise ValueError("No data returned from Binance API")

        # Convert to DataFrame
        df = pd.DataFrame(data)

        # Rename columns to match our format
        df = df.rename(
            columns={
                "T": "timestamp",  # Trade time
                "p": "price",  # Price
                "q": "qty",  # Quantity
                "m": "is_buyer_maker",  # Is buyer maker
            }
        )

        # Select and convert types
        df = df[["timestamp", "price", "qty", "is_buyer_maker"]]
        df["timestamp"] = df["timestamp"].astype(int)
        df["price"] = df["price"].astype(float)
        df["qty"] = df["qty"].astype(float)
        df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)

        print(f"✅ Fetched {len(df)} trades")
        print(f"   Price range: ${df['price'].min():.2f} - ${df['price'].max():.2f}")
        print(
            f"   Time range: {datetime.fromtimestamp(df['timestamp'].iloc[0] / 1000)} to {datetime.fromtimestamp(df['timestamp'].iloc[-1] / 1000)}"
        )

        return df

    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching data from Binance: {e}")
        raise
    except (ValueError, KeyError) as e:
        print(f"❌ Error parsing Binance data: {e}")
        raise


def save_aggtrades_csv(df: pd.DataFrame, output_path: str) -> None:
    """Save aggTrades DataFrame to CSV in our format"""
    df.to_csv(output_path, index=False)
    print(f"💾 Saved data to {output_path}")


class SimpleStrategy:
    """
    Simple demo strategy that generates orders for visualization

    Strategy: Mean reversion with momentum filter
    - Buy when price drops below 20-tick SMA
    - Sell when price rises above 20-tick SMA
    - Position sizing based on volatility
    """

    def __init__(self, engine: Engine, lookback: int = 20):
        self.engine = engine
        self.lookback = lookback
        self.prices = []
        self.order_records: List[OrderRecord] = []

    def on_tick(self, tick: Tick) -> None:
        """Process each tick and make trading decisions"""
        price = tick.price_tick_i64 * self.engine.config.tick_size
        self.prices.append(price)

        # Need enough data for indicators
        if len(self.prices) < self.lookback:
            return

        # Calculate simple moving average
        sma = np.mean(self.prices[-self.lookback :])

        # Get current position
        snapshot = self.engine.get_snapshot()
        position = snapshot.position

        # Trading logic
        if price < sma * 0.998 and position <= 0:
            # Buy signal - price below SMA
            qty = 0.01  # Fixed position size for demo
            order = Order(order_type="MARKET", side="BUY", qty=qty)
            self.engine.place_order(order)

            # Record order
            self.order_records.append(
                OrderRecord(
                    timestamp=tick.ts_ms,
                    price=price,
                    qty=qty,
                    side="BUY",
                    order_type="MARKET",
                    fee=qty * price * self.engine.config.taker_fee,
                )
            )

        elif price > sma * 1.002 and position >= 0:
            # Sell signal - price above SMA
            qty = 0.01
            order = Order(order_type="MARKET", side="SELL", qty=qty)
            self.engine.place_order(order)

            # Record order
            self.order_records.append(
                OrderRecord(
                    timestamp=tick.ts_ms,
                    price=price,
                    qty=qty,
                    side="SELL",
                    order_type="MARKET",
                    fee=qty * price * self.engine.config.taker_fee,
                )
            )


def run_backtest(
    data_path: str,
    initial_cash: float = 100_000.0,
    tick_size: float = None,
    bucket_ms: int = 100,
) -> Tuple[List[OrderRecord], List[dict], Engine]:
    """
    Run backtest through ag-kernel engine

    Returns:
        - List of order records
        - List of snapshots (equity curve)
        - Engine instance
    """
    print(f"\n🚀 Running backtest...")

    # Load data
    feed = AggTradesFeed(data_path, tick_size=tick_size or 1.0)
    raw_ticks = feed.load()

    if not raw_ticks:
        raise ValueError("No ticks loaded from data")

    # Auto-calculate tick size if not provided
    if tick_size is None:
        first_price = raw_ticks[0].price_tick_i64 * (tick_size or 1.0)
        tick_size = calculate_auto_ticksize(first_price, target_ticks=20)
        print(f"📏 Auto tick size: {tick_size}")

        # Reload with correct tick size
        feed = AggTradesFeed(data_path, tick_size=tick_size)
        raw_ticks = feed.load()

    # Aggregate ticks
    ticks = aggregate_ticks(raw_ticks, bucket_ms=bucket_ms, tick_size=tick_size)
    print(f"📊 Aggregated to {len(ticks)} ticks (bucket_ms={bucket_ms})")

    # Initialize engine
    config = EngineConfig(
        initial_cash=initial_cash,
        maker_fee=0.0001,  # 1 bp
        taker_fee=0.0002,  # 2 bp
        spread_bps=2.0,
        tick_size=tick_size,
    )
    engine = Engine(config)

    # Run strategy
    strategy = SimpleStrategy(engine, lookback=20)

    for i, tick in enumerate(ticks):
        engine.step_tick(tick)
        strategy.on_tick(tick)

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(ticks)} ticks...", end="\r")

    print(f"\n✅ Backtest complete: {len(strategy.order_records)} orders executed")

    # Get history
    history = engine.get_history()

    return strategy.order_records, history, engine


def create_bubbles_visualization(
    orders: List[OrderRecord],
    history: List[dict],
    output_path: str = "outputs/bubbles.png",
    title: str = "BTCUSDT Order Flow - Bubbles Visualization",
) -> None:
    """
    Create bubbles visualization of all orders

    - X-axis: Time
    - Y-axis: Price
    - Bubble size: Order quantity
    - Color: Green (BUY) / Red (SELL)
    """
    print(f"\n🎨 Creating bubbles visualization...")

    if not orders:
        print("⚠️  No orders to visualize")
        return

    # Prepare data
    df = pd.DataFrame(
        [
            {
                "timestamp": o.timestamp,
                "price": o.price,
                "qty": o.qty,
                "side": o.side,
                "order_type": o.order_type,
                "fee": o.fee,
            }
            for o in orders
        ]
    )

    # Convert timestamp to datetime
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

    # Prepare equity curve
    # Convert Snapshot objects to dicts if needed
    if history and hasattr(history[0], "__dict__"):
        history_dicts = [vars(s) for s in history]
    else:
        history_dicts = history

    equity_df = pd.DataFrame(history_dicts)
    equity_df["datetime"] = pd.to_datetime(equity_df["ts_ms"], unit="ms")

    # Create figure with dark theme
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [2, 1]}
    )

    # Plot 1: Bubbles (Orders)
    buy_orders = df[df["side"] == "BUY"]
    sell_orders = df[df["side"] == "SELL"]

    # Scale bubble sizes (multiply by large factor for visibility)
    size_scale = 10000

    # Plot BUY orders (green)
    if not buy_orders.empty:
        ax1.scatter(
            buy_orders["datetime"],
            buy_orders["price"],
            s=buy_orders["qty"] * size_scale,
            c="lime",
            alpha=0.6,
            edgecolors="white",
            linewidth=1,
            label=f"BUY ({len(buy_orders)} orders)",
        )

    # Plot SELL orders (red)
    if not sell_orders.empty:
        ax1.scatter(
            sell_orders["datetime"],
            sell_orders["price"],
            s=sell_orders["qty"] * size_scale,
            c="red",
            alpha=0.6,
            edgecolors="white",
            linewidth=1,
            label=f"SELL ({len(sell_orders)} orders)",
        )

    # Price line (from equity curve)
    if not equity_df.empty and "avg_entry_price" in equity_df.columns:
        # Use market price from snapshots if available
        # For now, just plot order prices as line
        ax1.plot(
            df["datetime"],
            df["price"],
            color="cyan",
            alpha=0.3,
            linewidth=1,
            linestyle="--",
            label="Price",
        )

    ax1.set_xlabel("Time", fontsize=12)
    ax1.set_ylabel("Price (USDT)", fontsize=12)
    ax1.set_title(title, fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=10)
    ax1.grid(True, alpha=0.2)

    # Format y-axis as currency
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    # Plot 2: Equity Curve
    ax2.plot(
        equity_df["datetime"],
        equity_df["equity"],
        color="gold",
        linewidth=2,
        label="Equity",
    )
    ax2.fill_between(
        equity_df["datetime"], equity_df["equity"], alpha=0.3, color="gold"
    )

    ax2.set_xlabel("Time", fontsize=12)
    ax2.set_ylabel("Equity (USDT)", fontsize=12)
    ax2.set_title("Equity Curve", fontsize=12)
    ax2.legend(loc="upper left", fontsize=10)
    ax2.grid(True, alpha=0.2)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    # Add statistics annotation
    total_qty = df["qty"].sum()
    total_fees = df["fee"].sum()

    # Handle equity calculations
    if not equity_df.empty and "equity" in equity_df.columns:
        final_equity = equity_df["equity"].iloc[-1]
        initial_equity = equity_df["equity"].iloc[0]
    elif history:
        # Fallback to Snapshot objects
        final_equity = history[-1].equity if hasattr(history[-1], "equity") else 0
        initial_equity = history[0].equity if hasattr(history[0], "equity") else 0
    else:
        final_equity = 0
        initial_equity = 0

    pnl = final_equity - initial_equity

    stats_text = (
        f"Orders: {len(orders)}\n"
        f"Total Volume: {total_qty:.4f} BTC\n"
        f"Total Fees: ${total_fees:.2f}\n"
        f"PnL: ${pnl:,.2f} ({pnl / initial_equity * 100:.2f}%)"
    )

    ax1.text(
        0.98,
        0.02,
        stats_text,
        transform=ax1.transAxes,
        fontsize=10,
        verticalalignment="bottom",
        horizontalalignment="right",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.8),
        color="white",
        family="monospace",
    )

    plt.tight_layout()

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="black")
    print(f"💾 Saved visualization to {output_path}")

    # Show statistics
    print(f"\n📈 Statistics:")
    print(f"   Total orders: {len(orders)}")
    print(f"   BUY orders: {len(buy_orders)}")
    print(f"   SELL orders: {len(sell_orders)}")
    print(f"   Total volume: {total_qty:.4f} BTC")
    print(f"   Total fees: ${total_fees:.2f}")
    print(f"   Final equity: ${final_equity:,.2f}")
    print(f"   PnL: ${pnl:,.2f} ({pnl / initial_equity * 100:.2f}%)")


def main():
    parser = argparse.ArgumentParser(
        description="Bubbles visualization for BTCUSDT orders through ag-kernel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Data source
    data_group = parser.add_mutually_exclusive_group(required=True)
    data_group.add_argument("--csv", type=str, help="Path to aggTrades CSV file")
    data_group.add_argument(
        "--fetch", action="store_true", help="Fetch data from Binance API"
    )

    # Binance API options
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading symbol (default: BTCUSDT)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Number of trades to fetch (default: 1000, max: 1000)",
    )

    # Backtest options
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100_000.0,
        help="Initial cash (default: 100000)",
    )
    parser.add_argument(
        "--tick-size",
        type=float,
        default=None,
        help="Tick size (default: auto-calculate)",
    )
    parser.add_argument(
        "--bucket-ms",
        type=int,
        default=100,
        help="Tick aggregation bucket in milliseconds (default: 100)",
    )

    # Output options
    parser.add_argument(
        "--output",
        type=str,
        default="outputs/bubbles.png",
        help="Output path for visualization (default: outputs/bubbles.png)",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="BTCUSDT Order Flow - Bubbles Visualization",
        help="Chart title",
    )

    args = parser.parse_args()

    # Prepare data
    if args.fetch:
        # Fetch from Binance
        df = fetch_binance_aggtrades(symbol=args.symbol, limit=args.limit)

        # Save to temporary CSV
        temp_csv = "outputs/temp_aggtrades.csv"
        os.makedirs("outputs", exist_ok=True)
        save_aggtrades_csv(df, temp_csv)
        data_path = temp_csv
    else:
        # Use provided CSV
        data_path = args.csv
        if not os.path.exists(data_path):
            print(f"❌ CSV file not found: {data_path}")
            sys.exit(1)

    # Run backtest
    try:
        orders, history, engine = run_backtest(
            data_path=data_path,
            initial_cash=args.initial_cash,
            tick_size=args.tick_size,
            bucket_ms=args.bucket_ms,
        )
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Create visualization
    try:
        create_bubbles_visualization(
            orders=orders, history=history, output_path=args.output, title=args.title
        )
    except Exception as e:
        print(f"❌ Visualization failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print(f"\n✅ Done! Open {args.output} to view the bubbles visualization.")


if __name__ == "__main__":
    main()
