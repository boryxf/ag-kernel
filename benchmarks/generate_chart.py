#!/usr/bin/env python3
"""
Generate professional benchmark comparison chart for ag-kernel README.
Shows both tick processing and analytics performance.
Output: docs/benchmark_chart.png
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# Configuration
OUTPUT_PATH = Path(__file__).parent.parent / "docs" / "benchmark_chart.png"

# Dark theme colors
COLORS = {
    'background': '#1a1a2e',
    'panel': '#16213e',
    'text': '#e8e8e8',
    'text_secondary': '#a0a0a0',
    'grid': '#2a2a4a',
    'python': '#e94560',
    'c_engine': '#00d9ff',
    'bars': ['#e94560', '#f39c12', '#3498db', '#00d9ff'],
}


def format_rate(value: float) -> str:
    """Format rate with appropriate suffix."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.0f}K"
    else:
        return f"{value:.0f}"


def create_benchmark_chart(output_path: Path) -> None:
    """Create the benchmark comparison chart with two panels."""
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor=COLORS['background'])

    # ========== Left Panel: Tick Processing ==========
    ax1.set_facecolor(COLORS['panel'])

    tick_labels = ['Pure Python\n(dict iter)', 'Single Tick\n(PyO3)', 'Batch Mode\n(PyO3)', 'NumPy Batch\n(zero-copy)']
    tick_values = [62_000, 537_000, 14_000_000, 626_000_000]

    x1 = np.arange(len(tick_labels))
    bars1 = ax1.bar(x1, tick_values, 0.6, color=COLORS['bars'], edgecolor='none', zorder=3)

    # Value labels
    for bar, value in zip(bars1, tick_values):
        ax1.annotate(format_rate(value), xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 8), textcoords="offset points", ha='center', va='bottom',
                    fontsize=13, fontweight='bold', color=COLORS['text'])

    ax1.set_ylabel('Ticks per Second', fontsize=12, color=COLORS['text'], fontweight='bold')
    ax1.set_title('Tick Processing', fontsize=16, fontweight='bold', color=COLORS['text'], pad=15)
    ax1.set_xticks(x1)
    ax1.set_xticklabels(tick_labels, fontsize=10, color=COLORS['text'])
    ax1.set_yscale('log')
    ax1.set_ylim(10_000, 2_000_000_000)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: format_rate(x)))
    ax1.grid(True, axis='y', linestyle='--', alpha=0.3, color=COLORS['grid'], zorder=1)
    for spine in ax1.spines.values():
        spine.set_color(COLORS['grid'])

    # Speedup annotation
    ax1.annotate('10Kx faster', xy=(3, 626_000_000), xytext=(2.4, 2_500_000_000),
                fontsize=11, color=COLORS['c_engine'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['c_engine'], lw=1.5))

    # ========== Right Panel: Analytics Performance ==========
    ax2.set_facecolor(COLORS['panel'])

    analytics_labels = ['Candles', 'VWAP', 'Volume\nProfile', 'Cumulative\nDelta', 'Volatility']
    py_values = [64_000, 95_000_000, 32_000_000, 218_000_000, 225_000]
    c_values = [84_000_000, 402_000_000, 304_000_000, 1_098_000_000, 114_000_000]
    speedups = [1307, 4.2, 9.6, 5.0, 507]

    x2 = np.arange(len(analytics_labels))
    width = 0.35

    bars_py = ax2.bar(x2 - width/2, py_values, width, label='Python/NumPy',
                      color=COLORS['python'], edgecolor='none', zorder=3)
    bars_c = ax2.bar(x2 + width/2, c_values, width, label='C Implementation',
                     color=COLORS['c_engine'], edgecolor='none', zorder=3)

    # Speedup labels on C bars
    for bar, speedup in zip(bars_c, speedups):
        label = f'{speedup:.0f}x' if speedup >= 10 else f'{speedup:.1f}x'
        ax2.annotate(label, xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 5), textcoords="offset points", ha='center', va='bottom',
                    fontsize=10, fontweight='bold', color=COLORS['c_engine'])

    ax2.set_ylabel('Operations per Second', fontsize=12, color=COLORS['text'], fontweight='bold')
    ax2.set_title('Analytics Performance (C vs Python)', fontsize=16, fontweight='bold', color=COLORS['text'], pad=15)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(analytics_labels, fontsize=10, color=COLORS['text'])
    ax2.set_yscale('log')
    ax2.set_ylim(10_000, 5_000_000_000)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: format_rate(x)))
    ax2.grid(True, axis='y', linestyle='--', alpha=0.3, color=COLORS['grid'], zorder=1)
    ax2.legend(loc='upper right', facecolor=COLORS['panel'], edgecolor=COLORS['grid'], fontsize=10)
    for spine in ax2.spines.values():
        spine.set_color(COLORS['grid'])

    # Main title
    fig.suptitle('ag-kernel Performance', fontsize=22, fontweight='bold', color=COLORS['text'], y=0.98)
    fig.text(0.5, 0.02, 'Benchmark: Apple M1 | 10M ticks | v0.3.0',
             ha='center', fontsize=11, color=COLORS['text_secondary'], style='italic')

    plt.tight_layout(rect=[0, 0.04, 1, 0.94])

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none',
                bbox_inches='tight', pad_inches=0.2)
    plt.close(fig)

    print(f"Chart saved to: {output_path}")
    print(f"Image size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    print("=" * 60)
    print("ag-kernel Benchmark Chart Generator")
    print("=" * 60)

    print("\nPerformance Summary:")
    print("  Tick Processing:")
    print("    - Pure Python: 62K/s")
    print("    - NumPy Batch: 626M/s (10,000x faster)")
    print("\n  Analytics (C vs Python):")
    print("    - Candles: 84M/s vs 64K/s (1,307x)")
    print("    - VWAP: 402M/s vs 95M/s (4.2x)")
    print("    - Volume Profile: 304M/s vs 32M/s (9.6x)")
    print("    - Cumulative Delta: 1.1B/s vs 218M/s (5.0x)")
    print("    - Volatility: 114M/s vs 225K/s (507x)")

    print(f"\nGenerating chart...")
    create_benchmark_chart(OUTPUT_PATH)
    print("\nDone!")


if __name__ == '__main__':
    main()
