"""
Tearsheet generation for backtest performance visualization.
"""

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from datetime import datetime

from .style import setup_dark_theme, COLORS
from .metrics import calculate_metrics


def generate_tearsheet(snapshots, trades=None, output_path='outputs/report.png'):
    """
    Generate a professional dark-themed tearsheet with 4 panels.

    Panels:
        1. Price chart with trade markers (buy/sell)
        2. Equity curve
        3. Underwater chart (drawdown %)
        4. Performance metrics table

    Args:
        snapshots: List of equity snapshots with 'timestamp' and 'equity' fields.
                   May optionally include 'price' field for price chart.
        trades: Optional list of trade dictionaries with fields:
                - timestamp: Trade execution time
                - side: 'buy' or 'sell'
                - price: Execution price
                - pnl: Profit/loss (for metrics)
        output_path: Path to save the PNG report (default: 'outputs/report.png')

    Side effects:
        - Saves report.png to output_path
        - Saves metrics.json to same directory
        - Saves equity.csv to same directory
    """
    # Setup
    setup_dark_theme()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate metrics
    metrics = calculate_metrics(snapshots, trades)

    # Prepare data
    timestamps = [s.get('timestamp', i) for i, s in enumerate(snapshots)]
    equity_values = [s.get('equity', s.get('value', 0)) for s in snapshots]

    # Convert timestamps to datetime if they're numeric
    if timestamps and isinstance(timestamps[0], (int, float)):
        dates = [datetime.fromtimestamp(ts) for ts in timestamps]
    else:
        dates = timestamps

    # Extract price data if available
    prices = [s.get('price', None) for s in snapshots]
    has_price = any(p is not None for p in prices)

    # Calculate drawdown
    equity_array = np.array(equity_values)
    running_max = np.maximum.accumulate(equity_array)
    drawdown = (equity_array - running_max) / running_max * 100  # Convert to percentage

    # Create figure with 4 subplots
    fig = plt.figure(figsize=(16, 9), dpi=120)
    gs = fig.add_gridspec(4, 1, height_ratios=[1.5, 1, 0.8, 0.7], hspace=0.3)

    # Panel 1: Price + Trade Markers
    ax1 = fig.add_subplot(gs[0])
    if has_price and any(p is not None for p in prices):
        # Plot price if available
        valid_prices = [(d, p) for d, p in zip(dates, prices) if p is not None]
        if valid_prices:
            price_dates, price_vals = zip(*valid_prices)
            ax1.plot(price_dates, price_vals, color=COLORS['text'], linewidth=1.5, label='Price')
    else:
        # Fallback to equity curve
        ax1.plot(dates, equity_values, color=COLORS['equity'], linewidth=1.5, label='Equity')

    # Add trade markers
    if trades:
        buy_trades = [t for t in trades if t.get('side', '').lower() in ['buy', 'long', 'open']]
        sell_trades = [t for t in trades if t.get('side', '').lower() in ['sell', 'short', 'close']]

        # Convert trade timestamps
        if buy_trades:
            buy_times = [t.get('timestamp', 0) for t in buy_trades]
            buy_prices = [t.get('price', 0) for t in buy_trades]
            if isinstance(buy_times[0], (int, float)):
                buy_times = [datetime.fromtimestamp(ts) for ts in buy_times]
            ax1.scatter(buy_times, buy_prices, color=COLORS['buy'], marker='^',
                       s=50, alpha=0.7, label='Buy', zorder=5)

        if sell_trades:
            sell_times = [t.get('timestamp', 0) for t in sell_trades]
            sell_prices = [t.get('price', 0) for t in sell_trades]
            if isinstance(sell_times[0], (int, float)):
                sell_times = [datetime.fromtimestamp(ts) for ts in sell_times]
            ax1.scatter(sell_times, sell_prices, color=COLORS['sell'], marker='v',
                       s=50, alpha=0.7, label='Sell', zorder=5)

    ax1.set_title('Price Chart with Trade Markers', fontweight='bold', pad=10)
    ax1.set_ylabel('Price', fontweight='bold')
    ax1.legend(loc='upper left', framealpha=0.9)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax1.tick_params(axis='x', rotation=45)
    ax1.grid(True, alpha=0.3)

    # Panel 2: Equity Curve
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.plot(dates, equity_values, color=COLORS['equity'], linewidth=2, label='Equity')
    ax2.fill_between(dates, equity_values, alpha=0.3, color=COLORS['equity'])
    ax2.set_title('Equity Curve', fontweight='bold', pad=10)
    ax2.set_ylabel('Equity ($)', fontweight='bold')
    ax2.legend(loc='upper left', framealpha=0.9)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax2.tick_params(axis='x', rotation=45)
    ax2.grid(True, alpha=0.3)

    # Panel 3: Underwater (Drawdown)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax3.fill_between(dates, drawdown, 0, color=COLORS['sell'], alpha=0.5)
    ax3.plot(dates, drawdown, color=COLORS['sell'], linewidth=1.5)
    ax3.set_title('Underwater Chart (Drawdown %)', fontweight='bold', pad=10)
    ax3.set_ylabel('Drawdown (%)', fontweight='bold')
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax3.tick_params(axis='x', rotation=45)
    ax3.grid(True, alpha=0.3)
    ax3.axhline(y=0, color=COLORS['grid'], linestyle='-', linewidth=1)

    # Panel 4: Metrics Table
    ax4 = fig.add_subplot(gs[3])
    ax4.axis('off')

    # Format metrics for display
    metrics_display = [
        ['Total Return', f"{metrics['total_return']*100:.2f}%"],
        ['Max Drawdown', f"{metrics['max_drawdown']*100:.2f}%"],
        ['Sharpe Ratio', f"{metrics['sharpe_ratio']:.2f}"],
        ['Win Rate', f"{metrics['win_rate']*100:.1f}%"],
        ['Total Trades', f"{metrics['total_trades']}"],
        ['Avg Trade', f"{metrics['avg_trade']*100:.3f}%"],
        ['Profit Factor', f"{metrics['profit_factor']:.2f}"],
    ]

    # Create table
    table = ax4.table(cellText=metrics_display,
                     colWidths=[0.3, 0.2],
                     cellLoc='left',
                     loc='center',
                     bbox=[0.1, 0, 0.8, 1])

    table.auto_set_font_size(False)
    table.set_fontsize(9)

    # Style table cells
    for i, (key, val) in enumerate(metrics_display):
        cell_key = table[(i, 0)]
        cell_val = table[(i, 1)]

        cell_key.set_facecolor(COLORS['background'])
        cell_val.set_facecolor(COLORS['background'])
        cell_key.set_edgecolor(COLORS['grid'])
        cell_val.set_edgecolor(COLORS['grid'])
        cell_key.set_text_props(color=COLORS['text_secondary'], weight='bold')
        cell_val.set_text_props(color=COLORS['text'], weight='bold')

    ax4.set_title('Performance Metrics', fontweight='bold', pad=10)

    # Adjust layout and save
    plt.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor=COLORS['background'],
                edgecolor='none', bbox_inches='tight')
    plt.close(fig)

    # Export metrics.json
    metrics_path = output_path.parent / 'metrics.json'
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)

    # Export equity.csv
    equity_df = pd.DataFrame({
        'timestamp': dates,
        'equity': equity_values,
        'drawdown': drawdown
    })
    equity_path = output_path.parent / 'equity.csv'
    equity_df.to_csv(equity_path, index=False)

    return str(output_path)
