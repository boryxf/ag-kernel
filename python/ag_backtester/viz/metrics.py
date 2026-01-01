"""
Performance metrics calculation for backtesting results.
"""

import numpy as np


def calculate_metrics(snapshots, trades=None):
    """
    Calculate comprehensive performance metrics from backtest results.

    Args:
        snapshots: List of equity snapshots, each with 'timestamp' and 'equity' fields
        trades: Optional list of trade dictionaries with 'pnl' field

    Returns:
        dict: Performance metrics including:
            - total_return: Overall return percentage (decimal)
            - max_drawdown: Maximum drawdown percentage (negative decimal)
            - sharpe_ratio: Risk-adjusted return metric
            - win_rate: Percentage of winning trades (decimal)
            - total_trades: Total number of trades
            - avg_trade: Average profit per trade (decimal)
            - profit_factor: Ratio of gross profit to gross loss
    """
    if not snapshots or len(snapshots) == 0:
        return {
            'total_return': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'win_rate': 0.0,
            'total_trades': 0,
            'avg_trade': 0.0,
            'profit_factor': 0.0
        }

    # Extract equity values
    equity_values = np.array([s.get('equity', s.get('value', 0)) for s in snapshots])

    if len(equity_values) == 0 or equity_values[0] == 0:
        initial_equity = 10000.0  # Default initial capital
    else:
        initial_equity = equity_values[0]

    # Total return
    final_equity = equity_values[-1]
    total_return = (final_equity - initial_equity) / initial_equity if initial_equity > 0 else 0.0

    # Maximum drawdown
    running_max = np.maximum.accumulate(equity_values)
    drawdown = (equity_values - running_max) / running_max
    max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0.0

    # Sharpe ratio (simplified - assumes daily returns)
    returns = np.diff(equity_values) / equity_values[:-1] if len(equity_values) > 1 else np.array([])
    if len(returns) > 0:
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        # Annualized Sharpe (assuming 252 trading days)
        sharpe_ratio = (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0.0
    else:
        sharpe_ratio = 0.0

    # Trade-based metrics
    if trades and len(trades) > 0:
        total_trades = len(trades)
        pnls = [t.get('pnl', t.get('profit', 0)) for t in trades]

        # Win rate
        winning_trades = [pnl for pnl in pnls if pnl > 0]
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0

        # Average trade
        avg_trade = np.mean(pnls) / initial_equity if len(pnls) > 0 and initial_equity > 0 else 0.0

        # Profit factor
        gross_profit = sum(winning_trades) if winning_trades else 0.0
        losing_trades = [abs(pnl) for pnl in pnls if pnl < 0]
        gross_loss = sum(losing_trades) if losing_trades else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)
    else:
        total_trades = 0
        win_rate = 0.0
        avg_trade = 0.0
        profit_factor = 0.0

    return {
        'total_return': round(total_return, 4),
        'max_drawdown': round(max_drawdown, 4),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'win_rate': round(win_rate, 4),
        'total_trades': total_trades,
        'avg_trade': round(avg_trade, 6),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999.99
    }
