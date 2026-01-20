#!/usr/bin/env python3
"""
Market Trades Bubbles Visualization
====================================

Visualizes ALL real market trades from Binance as bubbles without any trading strategy.
Just shows pure market activity - every trade as a bubble.

Usage:
    # Get full day of trades for 10 October 2025
    python examples/market_bubbles.py --date 2025-10-10 --symbol BTCUSDT

    # Get last N trades
    python examples/market_bubbles.py --symbol BTCUSDT --limit 10000

    # With delta aggregation (time buckets)
    python examples/market_bubbles.py --date 2025-10-10 --symbol BTCUSDT --delta 5
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from matplotlib.dates import DateFormatter

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def fetch_binance_trades_by_date(
    symbol: str, date_str: str, max_trades: int = 100000
) -> pd.DataFrame:
    """
    Fetch all trades for a specific date from Binance

    Args:
        symbol: Trading pair (e.g., BTCUSDT)
        date_str: Date in YYYY-MM-DD format
        max_trades: Maximum trades to fetch (safety limit)

    Returns:
        DataFrame with all trades for that date
    """
    # Parse date
    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    start_time = int(target_date.timestamp() * 1000)
    end_time = int((target_date + timedelta(days=1)).timestamp() * 1000)

    print(f"📅 Fetching {symbol} trades for {date_str}")
    print(f"   Start: {target_date}")
    print(f"   End:   {target_date + timedelta(days=1)}")

    url = "https://api.binance.com/api/v3/aggTrades"
    all_trades = []
    current_time = start_time

    while current_time < end_time and len(all_trades) < max_trades:
        params = {
            "symbol": symbol,
            "startTime": current_time,
            "endTime": end_time,
            "limit": 1000,  # Max per request
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            all_trades.extend(data)
            current_time = data[-1]["T"] + 1  # Next millisecond

            print(f"   Fetched {len(all_trades):,} trades...", end="\r")

        except Exception as e:
            print(f"\n⚠️  Error fetching data: {e}")
            break

    print(f"\n✅ Total trades fetched: {len(all_trades):,}")

    if not all_trades:
        raise ValueError("No trades fetched")

    # Convert to DataFrame
    df = pd.DataFrame(all_trades)
    df = df.rename(
        columns={"T": "timestamp", "p": "price", "q": "qty", "m": "is_buyer_maker"}
    )

    df = df[["timestamp", "price", "qty", "is_buyer_maker"]]
    df["timestamp"] = df["timestamp"].astype(int)
    df["price"] = df["price"].astype(float)
    df["qty"] = df["qty"].astype(float)
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)

    return df


def fetch_binance_trades_recent(symbol: str, limit: int = 10000) -> pd.DataFrame:
    """
    Fetch recent trades from Binance

    Args:
        symbol: Trading pair
        limit: Number of recent trades

    Returns:
        DataFrame with trades
    """
    print(f"📡 Fetching {limit:,} recent {symbol} trades from Binance...")

    url = "https://api.binance.com/api/v3/aggTrades"
    all_trades = []

    # Fetch in batches of 1000
    batches = (limit + 999) // 1000

    for i in range(batches):
        batch_limit = min(1000, limit - len(all_trades))

        params = {"symbol": symbol, "limit": batch_limit}

        if all_trades:
            # Continue from last trade
            params["endTime"] = all_trades[0]["T"] - 1

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            all_trades = data + all_trades  # Prepend older trades
            print(f"   Fetched {len(all_trades):,} trades...", end="\r")

        except Exception as e:
            print(f"\n⚠️  Error: {e}")
            break

    print(f"\n✅ Total trades fetched: {len(all_trades):,}")

    # Convert to DataFrame
    df = pd.DataFrame(all_trades)
    df = df.rename(
        columns={"T": "timestamp", "p": "price", "q": "qty", "m": "is_buyer_maker"}
    )

    df = df[["timestamp", "price", "qty", "is_buyer_maker"]]
    df["timestamp"] = df["timestamp"].astype(int)
    df["price"] = df["price"].astype(float)
    df["qty"] = df["qty"].astype(float)
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)

    return df


def create_market_bubbles_visualization(
    df: pd.DataFrame,
    symbol: str,
    output_path: str,
    title: str = None,
    max_bubbles: int = 5000,
    delta_seconds: int = None,
):
    """
    Create bubbles visualization of market trades

    Args:
        df: DataFrame with trades (timestamp, price, qty, is_buyer_maker)
        symbol: Trading symbol
        output_path: Where to save PNG
        title: Chart title (auto-generated if None)
        max_bubbles: Maximum bubbles to show (for performance)
        delta_seconds: If set, aggregate trades into time buckets (delta bubbles)
    """
    print(f"\n🎨 Creating market bubbles visualization...")

    # Convert timestamp to datetime first
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

    # Delta aggregation if requested
    if delta_seconds:
        print(f"   Aggregating trades into {delta_seconds}s delta buckets...")

        # Create time buckets
        df["bucket"] = df["datetime"].dt.floor(f"{delta_seconds}s")

        # Aggregate by bucket
        agg_data = []
        for bucket_time, group in df.groupby("bucket"):
            buy_qty = group[~group["is_buyer_maker"]]["qty"].sum()
            sell_qty = group[group["is_buyer_maker"]]["qty"].sum()

            # Net delta: positive = more buying, negative = more selling
            net_qty = buy_qty - sell_qty
            total_qty = buy_qty + sell_qty

            if total_qty > 0:
                agg_data.append(
                    {
                        "datetime": bucket_time,
                        "price": group["price"].mean(),
                        "qty": abs(net_qty),
                        "side": "BUY" if net_qty > 0 else "SELL",
                        "buy_qty": buy_qty,
                        "sell_qty": sell_qty,
                        "trades_count": len(group),
                    }
                )

        df = pd.DataFrame(agg_data)
        print(f"   Aggregated {len(df):,} delta bubbles from original trades")
    else:
        # Sample if too many trades
        if len(df) > max_bubbles:
            print(f"   Sampling {max_bubbles:,} trades from {len(df):,} total")
            df = df.sample(n=max_bubbles).sort_values("timestamp")
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Determine side from is_buyer_maker
        df["side"] = df["is_buyer_maker"].apply(lambda x: "SELL" if x else "BUY")

    # Calculate statistics
    total_volume = df["qty"].sum()
    buy_volume = df[df["side"] == "BUY"]["qty"].sum()
    sell_volume = df[df["side"] == "SELL"]["qty"].sum()
    avg_price = df["price"].mean()
    price_min = df["price"].min()
    price_max = df["price"].max()
    time_start = df["datetime"].iloc[0]
    time_end = df["datetime"].iloc[-1]
    duration = time_end - time_start

    # Create figure
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(20, 12), gridspec_kw={"height_ratios": [3, 1]}
    )

    # Prepare data for plotting
    buy_trades = df[df["side"] == "BUY"]
    sell_trades = df[df["side"] == "SELL"]

    # Scale bubble sizes
    # Use log scale for better visibility
    size_scale = 5000
    buy_sizes = np.sqrt(buy_trades["qty"]) * size_scale
    sell_sizes = np.sqrt(sell_trades["qty"]) * size_scale

    # Plot 1: Market Trades Bubbles
    if not buy_trades.empty:
        ax1.scatter(
            buy_trades["datetime"],
            buy_trades["price"],
            s=buy_sizes,
            c="lime",
            alpha=0.5,
            edgecolors="lime",
            linewidth=0.5,
            label=f"BUY ({len(buy_trades):,} trades, {buy_volume:.4f} BTC)",
        )

    if not sell_trades.empty:
        ax1.scatter(
            sell_trades["datetime"],
            sell_trades["price"],
            s=sell_sizes,
            c="red",
            alpha=0.5,
            edgecolors="red",
            linewidth=0.5,
            label=f"SELL ({len(sell_trades):,} trades, {sell_volume:.4f} BTC)",
        )

    # Price line (moving average)
    window = max(1, len(df) // 100)
    df["price_ma"] = df["price"].rolling(window=window, center=True).mean()
    ax1.plot(
        df["datetime"],
        df["price_ma"],
        color="cyan",
        alpha=0.7,
        linewidth=2,
        label="Price (MA)",
    )

    # Formatting
    if title is None:
        if delta_seconds:
            title = f"{symbol} - Delta Bubbles ({delta_seconds}s aggregation)"
        else:
            title = f"{symbol} - Market Trades Bubbles"

    ax1.set_title(title, fontsize=16, fontweight="bold", pad=20)
    ax1.set_xlabel("Time", fontsize=12)
    ax1.set_ylabel("Price (USDT)", fontsize=12)
    ax1.legend(loc="upper left", fontsize=10, framealpha=0.8)
    ax1.grid(True, alpha=0.2)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.2f}"))

    # Format x-axis
    ax1.xaxis.set_major_formatter(DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()

    # Statistics box
    if delta_seconds:
        stats_text = (
            f"Delta Bubbles: {len(df):,}\n"
            f"Bucket: {delta_seconds}s\n"
            f"Volume: {total_volume:.4f} BTC\n"
            f"BUY: {buy_volume:.4f} ({buy_volume / total_volume * 100:.1f}%)\n"
            f"SELL: {sell_volume:.4f} ({sell_volume / total_volume * 100:.1f}%)\n"
            f"Price: ${price_min:,.2f} - ${price_max:,.2f}\n"
            f"Avg: ${avg_price:,.2f}\n"
            f"Duration: {str(duration).split('.')[0]}"
        )
    else:
        stats_text = (
            f"Total Trades: {len(df):,}\n"
            f"Volume: {total_volume:.4f} BTC\n"
            f"BUY: {buy_volume:.4f} ({buy_volume / total_volume * 100:.1f}%)\n"
            f"SELL: {sell_volume:.4f} ({sell_volume / total_volume * 100:.1f}%)\n"
            f"Price: ${price_min:,.2f} - ${price_max:,.2f}\n"
            f"Avg: ${avg_price:,.2f}\n"
            f"Duration: {str(duration).split('.')[0]}"
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

    # Plot 2: Volume over time
    # Aggregate volume in time buckets
    time_buckets = 100
    df_sorted = df.sort_values("datetime")
    bucket_size = len(df_sorted) // time_buckets

    bucket_times = []
    bucket_volumes = []
    bucket_colors = []

    for i in range(time_buckets):
        start_idx = i * bucket_size
        end_idx = min((i + 1) * bucket_size, len(df_sorted))
        bucket = df_sorted.iloc[start_idx:end_idx]

        if not bucket.empty:
            bucket_times.append(bucket["datetime"].iloc[len(bucket) // 2])

            buy_vol = bucket[bucket["side"] == "BUY"]["qty"].sum()
            sell_vol = bucket[bucket["side"] == "SELL"]["qty"].sum()
            net_vol = buy_vol - sell_vol

            bucket_volumes.append(abs(net_vol))
            bucket_colors.append("lime" if net_vol > 0 else "red")

    ax2.bar(
        bucket_times,
        bucket_volumes,
        width=duration / time_buckets,
        color=bucket_colors,
        alpha=0.7,
        edgecolor="white",
        linewidth=0.5,
    )

    ax2.set_xlabel("Time", fontsize=12)
    ax2.set_ylabel("Net Volume (BTC)", fontsize=12)
    ax2.set_title("Buy/Sell Pressure Over Time", fontsize=12)
    ax2.grid(True, alpha=0.2, axis="y")
    ax2.xaxis.set_major_formatter(DateFormatter("%H:%M"))

    # Add zero line
    ax2.axhline(y=0, color="white", linestyle="--", alpha=0.3, linewidth=1)

    plt.tight_layout()

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="black")
    print(f"💾 Saved: {output_path}")

    # Print summary
    print(f"\n📊 Summary:")
    print(f"   Total trades: {len(df):,}")
    print(
        f"   BUY trades: {len(buy_trades):,} ({len(buy_trades) / len(df) * 100:.1f}%)"
    )
    print(
        f"   SELL trades: {len(sell_trades):,} ({len(sell_trades) / len(df) * 100:.1f}%)"
    )
    print(f"   Total volume: {total_volume:.4f} BTC")
    print(f"   Price range: ${price_min:,.2f} - ${price_max:,.2f}")
    print(f"   Time span: {duration}")


def main():
    parser = argparse.ArgumentParser(
        description="Market trades bubbles visualization (NO strategy, just raw market data)"
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading symbol (default: BTCUSDT)",
    )

    # Date or limit
    fetch_group = parser.add_mutually_exclusive_group(required=True)
    fetch_group.add_argument(
        "--date", type=str, help="Date to fetch in YYYY-MM-DD format (e.g., 2024-10-10)"
    )
    fetch_group.add_argument(
        "--limit", type=int, help="Number of recent trades to fetch"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="outputs/market_bubbles.png",
        help="Output path (default: outputs/market_bubbles.png)",
    )

    parser.add_argument(
        "--max-bubbles",
        type=int,
        default=5000,
        help="Maximum bubbles to display (default: 5000)",
    )

    parser.add_argument(
        "--save-csv", action="store_true", help="Save fetched data to CSV"
    )

    parser.add_argument(
        "--delta",
        type=int,
        default=None,
        help="Aggregate trades into delta buckets (seconds). E.g., --delta 5 for 5-second buckets",
    )

    args = parser.parse_args()

    # Fetch data
    try:
        if args.date:
            df = fetch_binance_trades_by_date(args.symbol, args.date)
            title = f"{args.symbol} - Market Trades - {args.date}"
            csv_path = f"outputs/market_trades_{args.symbol}_{args.date}.csv"
        else:
            df = fetch_binance_trades_recent(args.symbol, args.limit)
            title = f"{args.symbol} - Recent {args.limit:,} Market Trades"
            csv_path = f"outputs/market_trades_{args.symbol}_recent.csv"

        if df.empty:
            print("❌ No data fetched")
            return 1

        # Save CSV if requested
        if args.save_csv:
            os.makedirs("outputs", exist_ok=True)
            df.to_csv(csv_path, index=False)
            print(f"💾 Saved data: {csv_path}")

        # Create visualization
        create_market_bubbles_visualization(
            df=df,
            symbol=args.symbol,
            output_path=args.output,
            title=title,
            max_bubbles=args.max_bubbles,
            delta_seconds=args.delta,
        )

        print(f"\n✅ Done! View: {args.output}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
