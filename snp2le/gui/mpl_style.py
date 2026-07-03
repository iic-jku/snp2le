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
        # LaTeX-style maths for the axis labels (|S_{11}|, arg S_{11}, ...)
        # rendered with matplotlib's built-in Computer Modern, so no external
        # LaTeX install is needed.
        "mathtext.fontset": "cm",
        "xtick.color": "#7d828c",
        "ytick.color": "#7d828c",
        "figure.facecolor": "white",
        "svg.fonttype": "path",
    })
