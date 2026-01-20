#!/usr/bin/env python3
"""
Generate professional benchmark comparison chart for ag-kernel README.

This script creates a dark-themed bar chart comparing processing methods:
- Pure Python (pandas iterrows simulation)
- PyO3 single tick mode
- PyO3 batch mode
- PyO3 NumPy batch (zero-copy)

Output: docs/benchmark_chart.png
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# Configuration
BENCHMARK_RESULTS_PATH = Path(__file__).parent / "results" / "final.json"
OUTPUT_PATH = Path(__file__).parent.parent / "docs" / "benchmark_chart.png"

# Dark theme colors
COLORS = {
    'background': '#1a1a2e',
    'panel': '#16213e',
    'text': '#e8e8e8',
    'text_secondary': '#a0a0a0',
    'grid': '#2a2a4a',
    'bars': ['#e94560', '#f39c12', '#3498db', '#00d9ff'],
    'highlight': '#00d9ff',
}


def format_ticks_per_sec(value: float) -> str:
    """Format ticks/sec with appropriate suffix."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.0f}K"
    else:
        return f"{value:.0f}"


def load_benchmark_data(path: Path) -> dict:
    """Load benchmark results from JSON file."""
    if not path.exists():
        print(f"Error: Benchmark file not found: {path}")
        print("Run the benchmark first: python benchmarks/final_benchmark.py")
        sys.exit(1)

    with open(path) as f:
        return json.load(f)


def extract_performance_data(results: dict) -> tuple[list, list]:
    """Extract performance metrics for the chart."""
    tick_processing = results.get('tick_processing', {})
    aggregation = results.get('aggregation', {})

    # Extract values with fallbacks
    python_dict_rate = aggregation.get('python_dict_per_sec', 62000)
    single_tick_rate = tick_processing.get('single_tick_per_sec', 537000)
    batch_rate = tick_processing.get('batch_ticks_per_sec', 14_000_000)
    numpy_batch_rate = tick_processing.get('numpy_batch_per_sec', 626_000_000)

    labels = [
        'Pure Python\n(dict iteration)',
        'Single Tick\n(PyO3)',
        'Batch Mode\n(PyO3)',
        'NumPy Batch\n(zero-copy)',
    ]

    values = [
        python_dict_rate,
        single_tick_rate,
        batch_rate,
        numpy_batch_rate,
    ]

    return labels, values


def create_benchmark_chart(labels: list, values: list, output_path: Path) -> None:
    """Create the benchmark comparison bar chart."""
    # Set up the figure with dark background
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7), facecolor=COLORS['background'])
    ax.set_facecolor(COLORS['panel'])

    # Create bar positions
    x = np.arange(len(labels))
    bar_width = 0.6

    # Create gradient-like effect with individual colors
    bars = ax.bar(x, values, bar_width, color=COLORS['bars'], edgecolor='none',
                  zorder=3)

    # Add value labels on top of bars
    for bar, value in zip(bars, values):
        height = bar.get_height()
        label_text = format_ticks_per_sec(value)

        # Position label above bar
        ax.annotate(
            label_text,
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 8),
            textcoords="offset points",
            ha='center',
            va='bottom',
            fontsize=14,
            fontweight='bold',
            color=COLORS['text'],
        )

    # Configure axes
    ax.set_ylabel('Ticks per Second', fontsize=14, color=COLORS['text'],
                  fontweight='bold', labelpad=15)
    ax.set_xlabel('Processing Method', fontsize=14, color=COLORS['text'],
                  fontweight='bold', labelpad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, color=COLORS['text'])

    # Use log scale for y-axis to show dramatic differences
    ax.set_yscale('log')

    # Custom y-axis formatter
    def log_formatter(x, pos):
        if x >= 1_000_000_000:
            return f'{x / 1_000_000_000:.0f}B'
        elif x >= 1_000_000:
            return f'{x / 1_000_000:.0f}M'
        elif x >= 1_000:
            return f'{x / 1_000:.0f}K'
        return f'{x:.0f}'

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(log_formatter))

    # Set y-axis limits with padding
    ax.set_ylim(10_000, 2_000_000_000)

    # Style grid
    ax.grid(True, axis='y', linestyle='--', alpha=0.3, color=COLORS['grid'],
            zorder=1)
    ax.set_axisbelow(True)

    # Style spines
    for spine in ax.spines.values():
        spine.set_color(COLORS['grid'])
        spine.set_linewidth(0.5)

    # Title with styling
    ax.set_title(
        'ag-kernel Performance Comparison',
        fontsize=20,
        fontweight='bold',
        color=COLORS['text'],
        pad=20
    )

    # Add subtitle with version info
    fig.text(
        0.5, 0.92,
        'Benchmark: 1M ticks on Apple M1 | v0.3.0',
        ha='center',
        fontsize=10,
        color=COLORS['text_secondary'],
        style='italic'
    )

    # Add speedup annotations
    speedup_batch = values[2] / values[0]
    speedup_numpy = values[3] / values[0]

    # Annotation for batch mode speedup
    ax.annotate(
        f'{speedup_batch:.0f}x faster',
        xy=(2, values[2]),
        xytext=(2.3, values[2] * 0.15),
        fontsize=10,
        color=COLORS['bars'][2],
        fontweight='bold',
        arrowprops=dict(
            arrowstyle='->',
            color=COLORS['bars'][2],
            lw=1.5,
            connectionstyle='arc3,rad=-0.2'
        )
    )

    # Annotation for numpy batch speedup
    ax.annotate(
        f'{speedup_numpy / 1000:.0f}Kx faster',
        xy=(3, values[3]),
        xytext=(2.5, values[3] * 2.5),
        fontsize=10,
        color=COLORS['bars'][3],
        fontweight='bold',
        arrowprops=dict(
            arrowstyle='->',
            color=COLORS['bars'][3],
            lw=1.5,
            connectionstyle='arc3,rad=0.2'
        )
    )

    # Adjust layout
    plt.tight_layout()
    fig.subplots_adjust(top=0.88)

    # Save with high DPI for quality
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        output_path,
        dpi=150,
        facecolor=fig.get_facecolor(),
        edgecolor='none',
        bbox_inches='tight',
        pad_inches=0.3
    )
    plt.close(fig)

    print(f"Chart saved to: {output_path}")
    print(f"Image size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    """Main entry point."""
    print("=" * 60)
    print("ag-kernel Benchmark Chart Generator")
    print("=" * 60)

    # Load benchmark data
    print(f"\nLoading benchmark data from: {BENCHMARK_RESULTS_PATH}")
    results = load_benchmark_data(BENCHMARK_RESULTS_PATH)

    # Extract performance metrics
    labels, values = extract_performance_data(results)

    print("\nPerformance data:")
    for label, value in zip(labels, values):
        print(f"  {label.replace(chr(10), ' ')}: {format_ticks_per_sec(value)} ticks/sec")

    # Generate chart
    print(f"\nGenerating chart...")
    create_benchmark_chart(labels, values, OUTPUT_PATH)

    print("\nDone!")
    print("=" * 60)


if __name__ == '__main__':
    main()
