"""
Parallel backtesting utilities for running multiple backtests concurrently.

This module provides functions for:
- Running multiple backtests in parallel using ProcessPool or ThreadPool
- Monte Carlo simulations with parameter variations
"""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import List, Callable, Any, Optional, Dict, Tuple, Union
import multiprocessing as mp


def _run_single_backtest(args: Tuple[dict, Any, Callable]) -> dict:
    """
    Internal worker function to run a single backtest.

    Args:
        args: Tuple of (config, data, strategy_fn)

    Returns:
        Snapshot dict from engine
    """
    config, data, strategy_fn = args
    from ag_backtester import Engine, EngineConfig

    engine = Engine(EngineConfig(**config))
    strategy_fn(engine, data)
    snapshot = engine.get_snapshot()

    # Convert Snapshot dataclass to dict for serialization
    return {
        'ts_ms': snapshot.ts_ms,
        'cash': snapshot.cash,
        'position': snapshot.position,
        'avg_entry_price': snapshot.avg_entry_price,
        'realized_pnl': snapshot.realized_pnl,
        'unrealized_pnl': snapshot.unrealized_pnl,
        'equity': snapshot.equity,
        'config': config,
    }


def run_parallel_backtests(
    configs: List[dict],
    data_loader: Callable,
    strategy_fn: Callable,
    n_workers: Optional[int] = None,
    use_processes: bool = True,
) -> List[dict]:
    """
    Run multiple backtests in parallel.

    This function executes multiple backtest configurations concurrently,
    either using process-based parallelism (better for CPU-bound work) or
    thread-based parallelism (better for I/O-bound work).

    Args:
        configs: List of config dicts for each backtest. Each dict should
            contain keys matching EngineConfig fields (initial_cash, maker_fee,
            taker_fee, spread_bps, tick_size, etc.)
        data_loader: Function that returns tick data. The return value is
            passed directly to strategy_fn. Common formats:
            - Tuple of (timestamps, prices, qtys, sides) numpy arrays
            - Dict with 'timestamps', 'prices', 'qtys', 'sides' keys
            - Any format your strategy_fn expects
        strategy_fn: Function(engine, tick_data) that implements the trading
            strategy. Should call engine.step_tick() or engine.step_batch()
            and engine.place_order() as needed.
        n_workers: Number of parallel workers. Defaults to CPU count.
        use_processes: If True, use ProcessPoolExecutor (default).
            If False, use ThreadPoolExecutor. Processes are generally
            preferred for CPU-bound backtesting work.

    Returns:
        List of result dicts from each backtest, containing:
        - ts_ms: Final timestamp
        - cash: Final cash balance
        - position: Final position
        - avg_entry_price: Average entry price
        - realized_pnl: Realized P&L
        - unrealized_pnl: Unrealized P&L
        - equity: Final equity
        - config: The config dict used for this run

    Example:
        >>> configs = [
        ...     {'initial_cash': 100000, 'maker_fee': 0.0001},
        ...     {'initial_cash': 100000, 'maker_fee': 0.0002},
        ...     {'initial_cash': 100000, 'maker_fee': 0.0003},
        ... ]
        >>> def load_data():
        ...     return np.load('tick_data.npz')
        >>> def my_strategy(engine, data):
        ...     engine.step_batch(data['ts'], data['prices'], data['qtys'], data['sides'])
        >>> results = run_parallel_backtests(configs, load_data, my_strategy)
    """
    if n_workers is None:
        n_workers = mp.cpu_count()

    # Pre-load data once (shared across workers for threads, copied for processes)
    data = data_loader()

    # Prepare arguments for each worker
    worker_args = [(config, data, strategy_fn) for config in configs]

    Executor = ProcessPoolExecutor if use_processes else ThreadPoolExecutor

    with Executor(max_workers=n_workers) as executor:
        results = list(executor.map(_run_single_backtest, worker_args))

    return results


def run_monte_carlo(
    base_config: dict,
    data_loader: Callable,
    strategy_fn: Callable,
    n_simulations: int = 100,
    param_sampler: Optional[Callable[[], dict]] = None,
    n_workers: Optional[int] = None,
    use_processes: bool = True,
) -> List[dict]:
    """
    Run Monte Carlo simulations with parameter variations.

    This function runs multiple backtests with randomized parameters,
    useful for:
    - Sensitivity analysis
    - Parameter optimization
    - Robustness testing
    - Statistical analysis of strategy performance

    Args:
        base_config: Base configuration dict. All simulations start with
            these values, then apply param_sampler overrides.
        data_loader: Function that returns tick data (same as run_parallel_backtests)
        strategy_fn: Strategy function (same as run_parallel_backtests)
        n_simulations: Number of simulations to run (default: 100)
        param_sampler: Optional function that returns a dict of parameter
            overrides. Called once per simulation. If None, all simulations
            use the base_config unchanged.
        n_workers: Number of parallel workers (default: CPU count)
        use_processes: Use processes (True) or threads (False)

    Returns:
        List of result dicts from each simulation

    Example:
        >>> import random
        >>> base_config = {'initial_cash': 100000, 'maker_fee': 0.0001}
        >>> def sample_params():
        ...     return {
        ...         'maker_fee': random.uniform(0.00005, 0.0003),
        ...         'spread_bps': random.uniform(1.0, 5.0),
        ...     }
        >>> results = run_monte_carlo(
        ...     base_config, load_data, my_strategy,
        ...     n_simulations=1000, param_sampler=sample_params
        ... )
        >>> equities = [r['equity'] for r in results]
        >>> print(f"Mean equity: {np.mean(equities):.2f}")
    """
    configs = []
    for _ in range(n_simulations):
        config = base_config.copy()
        if param_sampler is not None:
            config.update(param_sampler())
        configs.append(config)

    return run_parallel_backtests(
        configs=configs,
        data_loader=data_loader,
        strategy_fn=strategy_fn,
        n_workers=n_workers,
        use_processes=use_processes,
    )


def run_parameter_sweep(
    base_config: dict,
    data_loader: Callable,
    strategy_fn: Callable,
    param_grid: Dict[str, List[Any]],
    n_workers: Optional[int] = None,
    use_processes: bool = True,
) -> List[dict]:
    """
    Run a parameter sweep over a grid of values.

    This function performs an exhaustive search over all combinations
    of parameter values, useful for systematic parameter optimization.

    Args:
        base_config: Base configuration dict
        data_loader: Function that returns tick data
        strategy_fn: Strategy function
        param_grid: Dict mapping parameter names to lists of values to try.
            All combinations will be tested.
        n_workers: Number of parallel workers
        use_processes: Use processes (True) or threads (False)

    Returns:
        List of result dicts from each parameter combination

    Example:
        >>> param_grid = {
        ...     'maker_fee': [0.0001, 0.0002, 0.0003],
        ...     'spread_bps': [1.0, 2.0, 3.0],
        ... }
        >>> results = run_parameter_sweep(
        ...     base_config, load_data, my_strategy, param_grid
        ... )
        >>> # Find best parameters
        >>> best = max(results, key=lambda r: r['equity'])
        >>> print(f"Best config: {best['config']}")
    """
    import itertools

    # Generate all combinations
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    configs = []
    for combination in itertools.product(*param_values):
        config = base_config.copy()
        for name, value in zip(param_names, combination):
            config[name] = value
        configs.append(config)

    return run_parallel_backtests(
        configs=configs,
        data_loader=data_loader,
        strategy_fn=strategy_fn,
        n_workers=n_workers,
        use_processes=use_processes,
    )


__all__ = [
    'run_parallel_backtests',
    'run_monte_carlo',
    'run_parameter_sweep',
]
