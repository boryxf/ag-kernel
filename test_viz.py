#!/usr/bin/env python3
"""
Quick validation script for viz module.
"""

import sys
import numpy as np
from datetime import datetime, timedelta

# Add python directory to path
sys.path.insert(0, '/Users/borkiss../ag-kernel/python')

from ag_backtester.viz import generate_tearsheet, calculate_metrics

# Generate sample data
start_date = datetime(2025, 1, 1)
num_days = 100

# Create realistic equity curve with some volatility
np.random.seed(42)
initial_equity = 10000
returns = np.random.normal(0.001, 0.02, num_days)  # Mean 0.1%, std 2%
equity_values = initial_equity * np.cumprod(1 + returns)

snapshots = []
for i in range(num_days):
    snapshots.append({
        'timestamp': (start_date + timedelta(days=i)).timestamp(),
        'equity': equity_values[i],
        'price': 100 + i * 0.5 + np.random.normal(0, 2)  # Price trending up with noise
    })

# Generate sample trades
trades = []
for i in range(0, num_days, 10):
    # Buy trade
    trades.append({
        'timestamp': (start_date + timedelta(days=i)).timestamp(),
        'side': 'buy',
        'price': 100 + i * 0.5,
        'pnl': 0
    })
    # Sell trade (5 days later)
    if i + 5 < num_days:
        pnl = np.random.normal(50, 100)  # Random P&L
        trades.append({
            'timestamp': (start_date + timedelta(days=i + 5)).timestamp(),
            'side': 'sell',
            'price': 100 + (i + 5) * 0.5,
            'pnl': pnl
        })

# Test metrics calculation
print("Testing metrics calculation...")
metrics = calculate_metrics(snapshots, trades)
print("Metrics:")
for key, value in metrics.items():
    print(f"  {key}: {value}")

# Generate tearsheet
print("\nGenerating tearsheet...")
output = generate_tearsheet(snapshots, trades, output_path='outputs/report.png')
print(f"Tearsheet saved to: {output}")
print(f"Metrics saved to: outputs/metrics.json")
print(f"Equity curve saved to: outputs/equity.csv")

print("\nValidation complete!")
