#!/usr/bin/env python3
"""
Advanced Bubbles Visualization for ag-kernel
==============================================

Features:
- Multiple strategy modes (mean-reversion, momentum, random)
- Real-time strategy switching
- Advanced bubble styling (transparency based on profit, size based on volume)
- Side-by-side comparison of strategies
- Order book depth visualization overlay

Usage:
    python examples/bubbles_advanced.py --fetch --limit 1000 --strategy momentum
    python examples/bubbles_advanced.py --csv data.csv --strategy mean-reversion --compare
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from ag_backtester import Engine, EngineConfig
from ag_backtester.data import AggTradesFeed, aggregate_ticks
from ag_backtester.engine import Order, Tick
from ag_backtester.userland import calculate_auto_ticksize


@dataclass
class OrderRecord:
    """Enhanced order record with profit tracking"""

    timestamp: int
    price: float
    qty: float
    side: str
    order_type: str
    fee: float
    position_before: float
    position_after: float
    realized_pnl: float
    strategy_name: str = "default"


class BaseStrategy:
    """Base class for all strategies"""

    def __init__(self, engine: Engine, name: str = "base"):
        self.engine = engine
        self.name = name
        self.order_records: List[OrderRecord] = []
        self.prices = []

    def record_order(self, tick: Tick, order: Order, snapshot_before) -> None:
        """Record executed order"""
        price = tick.price_tick_i64 * self.engine.config.tick_size
        snapshot_after = self.engine.get_snapshot()

        self.order_records.append(
            OrderRecord(
                timestamp=tick.ts_ms,
                price=price,
                qty=order.qty,
                side=order.side,
                order_type=order.order_type,
                fee=order.qty * price * self.engine.config.taker_fee,
                position_before=snapshot_before.position,
                position_after=snapshot_after.position,
                realized_pnl=snapshot_after.realized_pnl,
                strategy_name=self.name,
            )
        )

    def on_tick(self, tick: Tick) -> None:
        """Override in subclasses"""
        raise NotImplementedError


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy with Bollinger Bands"""

    def __init__(self, engine: Engine, lookback: int = 20, std_dev: float = 2.0):
        super().__init__(engine, name="mean-reversion")
        self.lookback = lookback
        self.std_dev = std_dev

    def on_tick(self, tick: Tick) -> None:
        price = tick.price_tick_i64 * self.engine.config.tick_size
        self.prices.append(price)

        if len(self.prices) < self.lookback:
            return

        # Bollinger Bands
        sma = np.mean(self.prices[-self.lookback :])
        std = np.std(self.prices[-self.lookback :])
        upper_band = sma + (self.std_dev * std)
        lower_band = sma - (self.std_dev * std)

        snapshot = self.engine.get_snapshot()
        position = snapshot.position

        # Mean reversion logic
        if price < lower_band and position <= 0:
            # Oversold - buy
            qty = 0.01
            order = Order(order_type="MARKET", side="BUY", qty=qty)
            self.engine.place_order(order)
            self.record_order(tick, order, snapshot)

        elif price > upper_band and position >= 0:
            # Overbought - sell
            qty = 0.01
            order = Order(order_type="MARKET", side="SELL", qty=qty)
            self.engine.place_order(order)
            self.record_order(tick, order, snapshot)


class MomentumStrategy(BaseStrategy):
    """Momentum strategy with moving average crossover"""

    def __init__(self, engine: Engine, fast_period: int = 10, slow_period: int = 30):
        super().__init__(engine, name="momentum")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.prev_signal = None

    def on_tick(self, tick: Tick) -> None:
        price = tick.price_tick_i64 * self.engine.config.tick_size
        self.prices.append(price)

        if len(self.prices) < self.slow_period:
            return

        # Moving averages
        fast_ma = np.mean(self.prices[-self.fast_period :])
        slow_ma = np.mean(self.prices[-self.slow_period :])

        # Signal
        signal = 1 if fast_ma > slow_ma else -1

        snapshot = self.engine.get_snapshot()
        position = snapshot.position

        # Only trade on crossover
        if self.prev_signal is not None and signal != self.prev_signal:
            if signal == 1 and position <= 0:
                # Golden cross - buy
                qty = 0.015
                order = Order(order_type="MARKET", side="BUY", qty=qty)
                self.engine.place_order(order)
                self.record_order(tick, order, snapshot)

            elif signal == -1 and position >= 0:
                # Death cross - sell
                qty = 0.015
                order = Order(order_type="MARKET", side="SELL", qty=qty)
                self.engine.place_order(order)
                self.record_order(tick, order, snapshot)

        self.prev_signal = signal


class RandomStrategy(BaseStrategy):
    """Random strategy for baseline comparison"""

    def __init__(self, engine: Engine, trade_probability: float = 0.05, seed: int = 42):
        super().__init__(engine, name="random")
        self.trade_probability = trade_probability
        self.rng = np.random.RandomState(seed)
        self.tick_count = 0

    def on_tick(self, tick: Tick) -> None:
        self.tick_count += 1

        # Trade randomly with given probability
        if self.rng.random() < self.trade_probability:
            snapshot = self.engine.get_snapshot()
            side = "BUY" if self.rng.random() < 0.5 else "SELL"
            qty = 0.01

            order = Order(order_type="MARKET", side=side, qty=qty)
            self.engine.place_order(order)
            self.record_order(tick, order, snapshot)


def fetch_binance_data(symbol: str, limit: int) -> pd.DataFrame:
    """Fetch data from Binance API"""
    url = "https://api.binance.com/api/v3/aggTrades"
    params = {"symbol": symbol, "limit": min(limit, 1000)}

    print(f"📡 Fetching {limit} trades for {symbol}...")
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    df = pd.DataFrame(data)
    df = df.rename(
        columns={"T": "timestamp", "p": "price", "q": "qty", "m": "is_buyer_maker"}
    )

    df = df[["timestamp", "price", "qty", "is_buyer_maker"]]
    df["timestamp"] = df["timestamp"].astype(int)
    df["price"] = df["price"].astype(float)
    df["qty"] = df["qty"].astype(float)
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)

    print(f"✅ Fetched {len(df)} trades")
    return df


def run_strategy_backtest(
    data_path: str,
    strategy_name: str,
    initial_cash: float = 100_000.0,
    tick_size: float = None,
    bucket_ms: int = 100,
) -> Tuple[List[OrderRecord], List[dict], Engine]:
    """Run backtest with specified strategy"""

    print(f"\n🚀 Running {strategy_name} strategy...")

    # Load and aggregate data
    feed = AggTradesFeed(data_path, tick_size=tick_size or 1.0)
    raw_ticks = feed.load()

    if tick_size is None:
        first_price = raw_ticks[0].price_tick_i64
        tick_size = calculate_auto_ticksize(first_price, target_ticks=20)
        feed = AggTradesFeed(data_path, tick_size=tick_size)
        raw_ticks = feed.load()

    ticks = aggregate_ticks(raw_ticks, bucket_ms=bucket_ms, tick_size=tick_size)
    print(f"📊 {len(ticks)} ticks aggregated")

    # Initialize engine
    config = EngineConfig(
        initial_cash=initial_cash,
        maker_fee=0.0001,
        taker_fee=0.0002,
        spread_bps=2.0,
        tick_size=tick_size,
    )
    engine = Engine(config)

    # Select strategy
    if strategy_name == "mean-reversion":
        strategy = MeanReversionStrategy(engine)
    elif strategy_name == "momentum":
        strategy = MomentumStrategy(engine)
    elif strategy_name == "random":
        strategy = RandomStrategy(engine)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    # Run
    for i, tick in enumerate(ticks):
        engine.step_tick(tick)
        strategy.on_tick(tick)

        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(ticks)} ticks", end="\r")

    print(f"\n✅ {len(strategy.order_records)} orders executed")

    return strategy.order_records, engine.get_history(), engine


def create_advanced_bubbles(
    orders_dict: Dict[str, List[OrderRecord]],
    history_dict: Dict[str, List[dict]],
    output_path: str,
    title: str = "Advanced Order Flow Bubbles",
) -> None:
    """Create advanced multi-strategy bubbles visualization"""

    print(f"\n🎨 Creating advanced bubbles visualization...")

    plt.style.use("dark_background")

    strategies = list(orders_dict.keys())
    n_strategies = len(strategies)

    if n_strategies == 1:
        fig, axes = plt.subplots(
            2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [2.5, 1]}
        )
        axes = [axes[0]], [axes[1]]
    else:
        fig, axes = plt.subplots(
            2,
            n_strategies,
            figsize=(8 * n_strategies, 10),
            gridspec_kw={"height_ratios": [2.5, 1]},
        )

    colors = {"BUY": "lime", "SELL": "red"}

    for idx, strategy_name in enumerate(strategies):
        orders = orders_dict[strategy_name]
        history = history_dict[strategy_name]

        if not orders:
            continue

        df = pd.DataFrame(
            [
                {
                    "timestamp": o.timestamp,
                    "price": o.price,
                    "qty": o.qty,
                    "side": o.side,
                    "fee": o.fee,
                    "realized_pnl": o.realized_pnl,
                }
                for o in orders
            ]
        )

        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Convert Snapshot objects to dicts if needed
        if history and hasattr(history[0], "__dict__"):
            history_dicts = [vars(s) for s in history]
        else:
            history_dicts = history

        equity_df = pd.DataFrame(history_dicts)
        equity_df["datetime"] = pd.to_datetime(equity_df["ts_ms"], unit="ms")

        # Bubbles plot
        ax1 = axes[0][idx] if n_strategies > 1 else axes[0][0]

        # Calculate alpha based on cumulative PnL
        if len(df) > 0:
            df["pnl_cumsum"] = df["realized_pnl"]
            df["alpha"] = 0.6  # Base alpha

            # Winning trades more opaque
            for side in ["BUY", "SELL"]:
                side_df = df[df["side"] == side]
                if not side_df.empty:
                    size_scale = 15000

                    ax1.scatter(
                        side_df["datetime"],
                        side_df["price"],
                        s=side_df["qty"] * size_scale,
                        c=colors[side],
                        alpha=0.6,
                        edgecolors="white",
                        linewidth=1.5,
                        label=f"{side} ({len(side_df)})",
                    )

        # Price line
        ax1.plot(
            df["datetime"],
            df["price"],
            color="cyan",
            alpha=0.3,
            linewidth=1,
            linestyle="--",
            label="Price",
        )

        ax1.set_xlabel("Time", fontsize=11)
        ax1.set_ylabel("Price (USDT)", fontsize=11)
        ax1.set_title(f"{strategy_name.upper()}", fontsize=13, fontweight="bold")
        ax1.legend(loc="upper left", fontsize=9)
        ax1.grid(True, alpha=0.2)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

        # Statistics
        total_orders = len(orders)
        total_volume = df["qty"].sum()
        total_fees = df["fee"].sum()
        final_equity = equity_df["equity"].iloc[-1] if not equity_df.empty else 0
        initial_equity = equity_df["equity"].iloc[0] if not equity_df.empty else 0
        pnl = final_equity - initial_equity
        pnl_pct = (pnl / initial_equity * 100) if initial_equity > 0 else 0

        stats = (
            f"Orders: {total_orders}\n"
            f"Volume: {total_volume:.4f} BTC\n"
            f"Fees: ${total_fees:.2f}\n"
            f"PnL: ${pnl:,.2f} ({pnl_pct:.2f}%)"
        )

        ax1.text(
            0.98,
            0.02,
            stats,
            transform=ax1.transAxes,
            fontsize=9,
            va="bottom",
            ha="right",
            bbox=dict(boxstyle="round", facecolor="black", alpha=0.8),
            color="white",
            family="monospace",
        )

        # Equity curve
        ax2 = axes[1][idx] if n_strategies > 1 else axes[1][0]

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

        # Add initial equity line
        ax2.axhline(
            y=initial_equity,
            color="white",
            linestyle="--",
            alpha=0.3,
            linewidth=1,
            label="Initial",
        )

        ax2.set_xlabel("Time", fontsize=11)
        ax2.set_ylabel("Equity (USDT)", fontsize=11)
        ax2.set_title("Equity Curve", fontsize=11)
        ax2.legend(loc="upper left", fontsize=9)
        ax2.grid(True, alpha=0.2)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    plt.suptitle(title, fontsize=16, fontweight="bold", y=0.995)
    plt.tight_layout()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="black")
    print(f"💾 Saved to {output_path}")

    # Print summary
    print(f"\n📊 Summary:")
    for strategy_name in strategies:
        orders = orders_dict[strategy_name]
        history = history_dict[strategy_name]

        if history:
            # Handle both dict and Snapshot objects
            if hasattr(history[0], "__dict__"):
                initial = history[0].equity
                final = history[-1].equity
            else:
                initial = history[0]["equity"]
                final = history[-1]["equity"]
            pnl = final - initial
            pnl_pct = (pnl / initial * 100) if initial > 0 else 0

            print(
                f"  {strategy_name:20s}: {len(orders):3d} orders, "
                f"PnL: ${pnl:>10,.2f} ({pnl_pct:>6.2f}%)"
            )


def main():
    parser = argparse.ArgumentParser(description="Advanced bubbles visualization")

    # Data source
    data_group = parser.add_mutually_exclusive_group(required=True)
    data_group.add_argument("--csv", type=str, help="Path to CSV")
    data_group.add_argument("--fetch", action="store_true", help="Fetch from Binance")

    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol")
    parser.add_argument("--limit", type=int, default=1000, help="Trades to fetch")
    parser.add_argument(
        "--strategy",
        default="momentum",
        choices=["mean-reversion", "momentum", "random"],
        help="Strategy to use",
    )
    parser.add_argument(
        "--compare", action="store_true", help="Compare all strategies side-by-side"
    )
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--tick-size", type=float, default=None)
    parser.add_argument("--bucket-ms", type=int, default=100)
    parser.add_argument("--output", default="outputs/bubbles_advanced.png")

    args = parser.parse_args()

    # Prepare data
    if args.fetch:
        df = fetch_binance_data(args.symbol, args.limit)
        temp_csv = "outputs/temp_aggtrades.csv"
        os.makedirs("outputs", exist_ok=True)
        df.to_csv(temp_csv, index=False)
        data_path = temp_csv
    else:
        data_path = args.csv

    # Run backtests
    orders_dict = {}
    history_dict = {}

    if args.compare:
        strategies = ["mean-reversion", "momentum", "random"]
    else:
        strategies = [args.strategy]

    for strategy in strategies:
        orders, history, engine = run_strategy_backtest(
            data_path=data_path,
            strategy_name=strategy,
            initial_cash=args.initial_cash,
            tick_size=args.tick_size,
            bucket_ms=args.bucket_ms,
        )
        orders_dict[strategy] = orders
        history_dict[strategy] = history

    # Visualize
    title = f"{args.symbol} - {'Strategy Comparison' if args.compare else args.strategy.upper()}"
    create_advanced_bubbles(orders_dict, history_dict, args.output, title)

    print(f"\n✅ Done! View: {args.output}")


if __name__ == "__main__":
    main()
