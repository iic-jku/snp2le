"""mpl_style.py - global matplotlib styling to match the app."""
from __future__ import annotations
import matplotlib


def apply_style():
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans"],
        "axes.titlesize": 9,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.edgecolor": "#c4ccd6",
        "axes.linewidth": 0.8,
        "grid.color": "#dbe2ea",
        "grid.linewidth": 0.6,
        "axes.labelcolor": "#000000",
        "text.color": "#000000",
        "xtick.color": "#7d828c",
        "ytick.color": "#7d828c",
        "figure.facecolor": "white",
        "svg.fonttype": "path",
    })
