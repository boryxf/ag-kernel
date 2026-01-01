"""
Visualization module for ag-backtester.

Generates dark-themed performance tearsheets with matplotlib.
"""

from .tearsheet import generate_tearsheet
from .metrics import calculate_metrics
from .style import setup_dark_theme, COLORS

__all__ = ["generate_tearsheet", "calculate_metrics", "setup_dark_theme", "COLORS"]
