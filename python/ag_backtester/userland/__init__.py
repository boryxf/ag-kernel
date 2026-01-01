"""
User-facing utilities and helpers.

This module contains convenience functions for backtesting setup
and configuration.
"""

from .auto_ticksize import calculate_auto_ticksize

__all__ = ["calculate_auto_ticksize"]
