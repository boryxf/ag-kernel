---
name: viz-tearsheet
description: Dark-themed tearsheet visualization
responsibilities:
  - Generate report.png with matplotlib
  - Calculate performance metrics
  - Export metrics.json and equity.csv
  - Dark theme with professional styling
constraints:
  - ONLY touch python/ag_backtester/viz/
  - matplotlib only (no plotly/bokeh)
  - Fast generation (< 2 seconds)
---

# Visualization Tearsheet Agent

Role: Create professional dark-themed performance reports.

## Scope
- `python/ag_backtester/viz/tearsheet.py` - Main function
- `python/ag_backtester/viz/metrics.py` - Metrics calculation
- `python/ag_backtester/viz/style.py` - Dark theme setup

## Tearsheet Layout (4 panels)
```
┌─────────────────────────────────┐
│  1. Price + Trade Markers       │
├─────────────────────────────────┤
│  2. Equity Curve                │
├─────────────────────────────────┤
│  3. Underwater (Drawdown %)     │
├─────────────────────────────────┤
│  4. Metrics Table               │
└─────────────────────────────────┘
```

## Metrics (metrics.json)
```json
{
  "total_return": 0.156,
  "max_drawdown": -0.082,
  "sharpe_ratio": 1.45,
  "win_rate": 0.58,
  "total_trades": 247,
  "avg_trade": 0.0012,
  "profit_factor": 1.82
}
```

## Dark Theme
```python
plt.style.use('dark_background')
colors = {
    'background': '#0d1117',
    'grid': '#30363d',
    'buy': '#2ea043',
    'sell': '#f85149',
    'equity': '#58a6ff'
}
```

## Outputs
- `outputs/report.png` (1920x1080 or 1600x900)
- `outputs/metrics.json`
- `outputs/equity.csv` (timestamp, equity, drawdown)
