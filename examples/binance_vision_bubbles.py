#!/usr/bin/env python3
"""
Binance Vision Delta Bubbles Visualization
===========================================

Visualizes full day of BTCUSDT aggTrades from Binance Vision historical data
as delta bubbles (aggregated buy/sell pressure in time buckets).

Usage:
    python examples/binance_vision_bubbles.py \
      --csv outputs/BTCUSDT-aggTrades-2025-10-10.csv \
      --delta 60 \
      --output outputs/btcusdt_2025-10-10_delta_bubbles.png
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.dates import DateFormatter, HourLocator


def load_binance_vision_csv(csv_path: str, max_rows: int = None) -> pd.DataFrame:
    """
    Load Binance Vision aggTrades CSV

    Format: agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker
    """
    print(f"📂 Loading {csv_path}...")

    df = pd.read_csv(
        csv_path,
        usecols=["transact_time", "price", "quantity", "is_buyer_maker"],
        nrows=max_rows,
    )

    # Rename to standard format
    df = df.rename(columns={"transact_time": "timestamp", "quantity": "qty"})

    print(f"✅ Loaded {len(df):,} trades")
    print(
        f"   Time: {datetime.fromtimestamp(df['timestamp'].iloc[0] / 1000)} to {datetime.fromtimestamp(df['timestamp'].iloc[-1] / 1000)}"
    )
    print(f"   Price: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
    print(f"   Volume: {df['qty'].sum():,.4f} BTC")

    return df


def aggregate_to_delta_bubbles(df: pd.DataFrame, delta_seconds: int) -> pd.DataFrame:
    """
    Aggregate trades into delta bubbles (time buckets showing buy/sell pressure)

    Args:
        df: DataFrame with timestamp, price, qty, is_buyer_maker
        delta_seconds: Bucket size in seconds

    Returns:
        DataFrame with aggregated delta bubbles
    """
    print(f"\n🔄 Aggregating to {delta_seconds}s delta buckets...")

    # Convert timestamp to datetime
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

    # Create time buckets
    df["bucket"] = df["datetime"].dt.floor(f"{delta_seconds}s")

    # Aggregate by bucket
    bubbles = []

    for bucket_time, group in df.groupby("bucket"):
        # Separate buy and sell trades
        # is_buyer_maker=True means market SELL (taker sells to maker buy order)
        # is_buyer_maker=False means market BUY (taker buys from maker sell order)
        buy_trades = group[~group["is_buyer_maker"]]
        sell_trades = group[group["is_buyer_maker"]]

        buy_qty = buy_trades["qty"].sum()
        sell_qty = sell_trades["qty"].sum()

        # Calculate net delta
        net_qty = buy_qty - sell_qty
        total_qty = buy_qty + sell_qty

        if total_qty > 0:
            bubbles.append(
                {
                    "datetime": bucket_time,
                    "price": group["price"].mean(),  # Average price in bucket
                    "price_open": group["price"].iloc[0],
                    "price_close": group["price"].iloc[-1],
                    "price_high": group["price"].max(),
                    "price_low": group["price"].min(),
                    "qty": abs(net_qty),  # Size of bubble = magnitude of delta
                    "net_qty": net_qty,
                    "buy_qty": buy_qty,
                    "sell_qty": sell_qty,
                    "side": "BUY" if net_qty > 0 else "SELL",
                    "trades_count": len(group),
                    "buy_pressure": buy_qty / total_qty if total_qty > 0 else 0.5,
                }
            )

    result = pd.DataFrame(bubbles)
    print(f"✅ Created {len(result):,} delta bubbles")
    print(
        f"   BUY pressure: {len(result[result['side'] == 'BUY']):,} bubbles ({len(result[result['side'] == 'BUY']) / len(result) * 100:.1f}%)"
    )
    print(
        f"   SELL pressure: {len(result[result['side'] == 'SELL']):,} bubbles ({len(result[result['side'] == 'SELL']) / len(result) * 100:.1f}%)"
    )

    return result


def create_delta_bubbles_chart(
    bubbles: pd.DataFrame,
    output_path: str,
    title: str = "BTCUSDT - Delta Bubbles",
    symbol: str = "BTCUSDT",
    bubble_scale: float = 500,
    bubble_alpha: float = 0.5,
    time_start: str = None,
    time_end: str = None,
):
    """
    Create beautiful delta bubbles visualization

    Args:
        time_start: Start time filter (HH:MM format, e.g., "12:00")
        time_end: End time filter (HH:MM format, e.g., "23:59")
    """
    print(f"\n🎨 Creating delta bubbles visualization...")

    # Apply time filtering if requested
    if time_start or time_end:
        original_len = len(bubbles)

        if time_start:
            time_start_obj = pd.to_datetime(f"1900-01-01 {time_start}")
            bubbles = bubbles[bubbles["datetime"].dt.time >= time_start_obj.time()]

        if time_end:
            time_end_obj = pd.to_datetime(f"1900-01-01 {time_end}")
            bubbles = bubbles[bubbles["datetime"].dt.time <= time_end_obj.time()]

        print(f"   Time filter: {time_start or '00:00'} - {time_end or '23:59'}")
        print(f"   Filtered: {original_len:,} → {len(bubbles):,} bubbles")

    # Prepare data
    buy_bubbles = bubbles[bubbles["side"] == "BUY"].copy()
    sell_bubbles = bubbles[bubbles["side"] == "SELL"].copy()

    # Calculate statistics
    total_buy_qty = buy_bubbles["buy_qty"].sum()
    total_sell_qty = sell_bubbles["sell_qty"].sum()
    total_volume = bubbles["buy_qty"].sum() + bubbles["sell_qty"].sum()
    price_min = bubbles["price_low"].min()
    price_max = bubbles["price_high"].max()
    duration = bubbles["datetime"].iloc[-1] - bubbles["datetime"].iloc[0]

    # Create figure
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(24, 14), gridspec_kw={"height_ratios": [3, 1]}
    )

    # Auto-scale bubble sizes with normalization (scale 1-10)
    # Combine all quantities for global scaling
    all_qtys = bubbles["qty"].values

    # Use percentile-based scaling to handle outliers
    q_min = np.percentile(all_qtys, 5)  # 5th percentile
    q_max = np.percentile(all_qtys, 95)  # 95th percentile

    # Normalize to 1-10 scale
    def normalize_size(qty):
        # Clamp to percentile range
        qty_clamped = np.clip(qty, q_min, q_max)
        # Normalize to 0-1
        if q_max > q_min:
            normalized = (qty_clamped - q_min) / (q_max - q_min)
        else:
            normalized = 0.5
        # Scale to 1-10 with sqrt for better perception
        return np.sqrt(normalized * 9 + 1)  # sqrt(1) to sqrt(10)

    # Apply scaling with size multiplier for visibility
    buy_sizes = np.array([normalize_size(q) for q in buy_bubbles["qty"]]) * bubble_scale
    sell_sizes = (
        np.array([normalize_size(q) for q in sell_bubbles["qty"]]) * bubble_scale
    )

    # Plot 1: Delta Bubbles
    if not buy_bubbles.empty:
        scatter_buy = ax1.scatter(
            buy_bubbles["datetime"],
            buy_bubbles["price"],
            s=buy_sizes,
            c="lime",
            alpha=bubble_alpha,
            edgecolors="white",
            linewidth=0.5,
            label=f"BUY Pressure ({len(buy_bubbles):,} bubbles)",
            zorder=5,
        )

    if not sell_bubbles.empty:
        scatter_sell = ax1.scatter(
            sell_bubbles["datetime"],
            sell_bubbles["price"],
            s=sell_sizes,
            c="red",
            alpha=bubble_alpha,
            edgecolors="white",
            linewidth=0.5,
            label=f"SELL Pressure ({len(sell_bubbles):,} bubbles)",
            zorder=5,
        )

    # Price line (OHLC-style)
    ax1.plot(
        bubbles["datetime"],
        bubbles["price"],
        color="cyan",
        alpha=0.5,
        linewidth=2,
        label="Price (avg)",
        zorder=3,
    )

    # High/Low bands
    ax1.fill_between(
        bubbles["datetime"],
        bubbles["price_low"],
        bubbles["price_high"],
        color="cyan",
        alpha=0.1,
        zorder=1,
    )

    # Formatting
    ax1.set_title(title, fontsize=18, fontweight="bold", pad=20)
    ax1.set_xlabel("Time (UTC)", fontsize=14)
    ax1.set_ylabel("Price (USDT)", fontsize=14)
    ax1.legend(loc="upper left", fontsize=12, framealpha=0.9)
    ax1.grid(True, alpha=0.2, linestyle="--")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    # Format x-axis
    ax1.xaxis.set_major_locator(HourLocator(interval=2))
    ax1.xaxis.set_major_formatter(DateFormatter("%H:%M"))
    fig.autofmt_xdate(rotation=45)

    # Statistics box
    delta_net = total_buy_qty - total_sell_qty
    buy_pct = total_buy_qty / total_volume * 100 if total_volume > 0 else 0
    sell_pct = total_sell_qty / total_volume * 100 if total_volume > 0 else 0

    stats_text = (
        f"Date: {bubbles['datetime'].iloc[0].strftime('%Y-%m-%d')}\n"
        f"Duration: {str(duration).split('.')[0]}\n"
        f"Bubbles: {len(bubbles):,}\n"
        f"Bubble Scale: 1-10 (auto-normalized)\n"
        f"Total Volume: {total_volume:,.2f} BTC\n"
        f"  BUY: {total_buy_qty:,.2f} BTC ({buy_pct:.1f}%)\n"
        f"  SELL: {total_sell_qty:,.2f} BTC ({sell_pct:.1f}%)\n"
        f"Net Delta: {delta_net:+,.2f} BTC\n"
        f"Price Range: ${price_min:,.0f} - ${price_max:,.0f}\n"
        f"Total Trades: {bubbles['trades_count'].sum():,}"
    )

    ax1.text(
        0.98,
        0.02,
        stats_text,
        transform=ax1.transAxes,
        fontsize=11,
        verticalalignment="bottom",
        horizontalalignment="right",
        bbox=dict(
            boxstyle="round",
            facecolor="black",
            alpha=0.9,
            edgecolor="white",
            linewidth=1.5,
        ),
        color="white",
        family="monospace",
    )

    # Plot 2: Cumulative Net Delta
    bubbles["cumulative_delta"] = bubbles["net_qty"].cumsum()

    colors = ["lime" if x >= 0 else "red" for x in bubbles["cumulative_delta"]]
    ax2.fill_between(
        bubbles["datetime"], 0, bubbles["cumulative_delta"], color="cyan", alpha=0.3
    )
    ax2.plot(
        bubbles["datetime"],
        bubbles["cumulative_delta"],
        color="gold",
        linewidth=2,
        label="Cumulative Net Delta",
    )

    # Zero line
    ax2.axhline(y=0, color="white", linestyle="--", alpha=0.5, linewidth=1)

    ax2.set_xlabel("Time (UTC)", fontsize=14)
    ax2.set_ylabel("Cumulative Delta (BTC)", fontsize=14)
    ax2.set_title("Cumulative Buy/Sell Pressure", fontsize=14)
    ax2.legend(loc="upper left", fontsize=11)
    ax2.grid(True, alpha=0.2, linestyle="--")
    ax2.xaxis.set_major_locator(HourLocator(interval=2))
    ax2.xaxis.set_major_formatter(DateFormatter("%H:%M"))

    # Add shading for positive/negative zones
    ax2.fill_between(
        bubbles["datetime"],
        0,
        bubbles["cumulative_delta"],
        where=(bubbles["cumulative_delta"] > 0),
        color="lime",
        alpha=0.2,
    )
    ax2.fill_between(
        bubbles["datetime"],
        0,
        bubbles["cumulative_delta"],
        where=(bubbles["cumulative_delta"] <= 0),
        color="red",
        alpha=0.2,
    )

    plt.tight_layout()

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="black")
    print(f"💾 Saved: {output_path}")

    # Print summary
    print(f"\n📊 Final Summary:")
    print(f"   Total bubbles: {len(bubbles):,}")
    print(f"   BUY pressure: {len(buy_bubbles):,} bubbles")
    print(f"   SELL pressure: {len(sell_bubbles):,} bubbles")
    print(f"   Total volume: {total_volume:,.2f} BTC")
    print(
        f"   Net delta: {delta_net:+,.2f} BTC ({abs(delta_net) / total_volume * 100:.2f}% imbalance)"
    )
    print(f"   Price range: ${price_min:,.2f} - ${price_max:,.2f}")
    print(f"   File size: {os.path.getsize(output_path) / 1024 / 1024:.1f} MB")


def main():
    parser = argparse.ArgumentParser(
        description="Create delta bubbles visualization from Binance Vision historical data"
    )

    parser.add_argument(
        "--csv",
        type=str,
        required=True,
        help="Path to Binance Vision aggTrades CSV file",
    )

    parser.add_argument(
        "--delta",
        type=int,
        default=60,
        help="Time bucket size in seconds (default: 60)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="outputs/delta_bubbles.png",
        help="Output PNG path (default: outputs/delta_bubbles.png)",
    )

    parser.add_argument(
        "--bubble-scale",
        type=float,
        default=500,
        help="Bubble size multiplier (default: 500, try 200-1000)",
    )

    parser.add_argument(
        "--bubble-alpha",
        type=float,
        default=0.5,
        help="Bubble transparency (default: 0.5, range 0.1-1.0)",
    )

    parser.add_argument(
        "--time-start",
        type=str,
        default=None,
        help="Start time filter (HH:MM format, e.g., 12:00 for second half of day)",
    )

    parser.add_argument(
        "--time-end",
        type=str,
        default=None,
        help="End time filter (HH:MM format, e.g., 23:59)",
    )

    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Chart title (auto-generated if not specified)",
    )

    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Limit number of rows to load (for testing)",
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading symbol (default: BTCUSDT)",
    )

    args = parser.parse_args()

    try:
        # Load data
        df = load_binance_vision_csv(args.csv, max_rows=args.max_rows)

        # Aggregate to delta bubbles
        bubbles = aggregate_to_delta_bubbles(df, args.delta)

        # Generate title
        if args.title is None:
            date_str = datetime.fromtimestamp(df["timestamp"].iloc[0] / 1000).strftime(
                "%Y-%m-%d"
            )
            args.title = (
                f"{args.symbol} - Delta Bubbles ({date_str}) - {args.delta}s buckets"
            )

        # Create visualization
        create_delta_bubbles_chart(
            bubbles=bubbles,
            output_path=args.output,
            title=args.title,
            symbol=args.symbol,
            bubble_scale=args.bubble_scale,
            bubble_alpha=args.bubble_alpha,
            time_start=args.time_start,
            time_end=args.time_end,
        )

        print(f"\n✅ Done! Open {args.output} to view the visualization")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
