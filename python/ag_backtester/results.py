"""Backtest results container"""
from dataclasses import dataclass
from typing import List
import json
import pandas as pd


@dataclass
class BacktestResult:
    """Container for backtest results"""
    snapshots: List
    trades: List[dict]
    metrics: dict
    config: dict

    def to_json(self, path: str):
        """Export metrics to JSON"""
        with open(path, 'w') as f:
            json.dump(self.metrics, f, indent=2)

    def to_csv(self, path: str):
        """Export equity curve to CSV"""
        df = pd.DataFrame([
            {
                'timestamp': s.ts_ms,
                'equity': s.equity,
                'cash': s.cash,
                'position': s.position,
                'realized_pnl': s.realized_pnl,
                'unrealized_pnl': s.unrealized_pnl,
            }
            for s in self.snapshots
        ])
        df.to_csv(path, index=False)

    def summary(self) -> str:
        """Get text summary"""
        m = self.metrics
        return f"""
Backtest Results:
-----------------
Total Return: {m.get('total_return', 0):.2%}
Max Drawdown: {m.get('max_drawdown', 0):.2%}
Sharpe Ratio: {m.get('sharpe_ratio', 0):.2f}
Win Rate: {m.get('win_rate', 0):.2%}
Total Trades: {m.get('total_trades', 0)}
Avg Trade: {m.get('avg_trade', 0):.4f}
""".strip()
