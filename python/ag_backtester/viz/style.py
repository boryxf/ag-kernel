"""
Dark theme styling for matplotlib visualizations.
"""

import matplotlib.pyplot as plt

# GitHub dark theme inspired colors
COLORS = {
    'background': '#0d1117',
    'grid': '#30363d',
    'buy': '#2ea043',
    'sell': '#f85149',
    'equity': '#58a6ff',
    'text': '#c9d1d9',
    'text_secondary': '#8b949e'
}


def setup_dark_theme():
    """
    Configure matplotlib to use dark theme with professional styling.

    Returns:
        dict: Color palette for consistent theming across plots
    """
    plt.style.use('dark_background')

    # Set global rcParams for consistent styling
    plt.rcParams.update({
        'figure.facecolor': COLORS['background'],
        'axes.facecolor': COLORS['background'],
        'axes.edgecolor': COLORS['grid'],
        'axes.labelcolor': COLORS['text'],
        'axes.grid': True,
        'grid.color': COLORS['grid'],
        'grid.alpha': 0.3,
        'grid.linestyle': '--',
        'grid.linewidth': 0.5,
        'text.color': COLORS['text'],
        'xtick.color': COLORS['text'],
        'ytick.color': COLORS['text'],
        'legend.facecolor': COLORS['background'],
        'legend.edgecolor': COLORS['grid'],
        'font.size': 9,
        'axes.titlesize': 10,
        'axes.labelsize': 9,
        'xtick.labelsize': 8,
        'ytick.labelsize': 8,
        'legend.fontsize': 8,
    })

    return COLORS
