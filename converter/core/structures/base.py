"""structures/base.py - interface for structure-specific physical extractors.

A Structure assumes a known topology and fits its real component values to the
S-parameters, producing an interpretable CircuitIR whose elements map to physical
reality.  This is the opposite philosophy to the universal macromodel:
interpretable, but only valid for the matching structure and port count.

extract(net) returns (CircuitIR, metrics: dict, rows: list[(label, value, unit)]),
where `rows` is the concise, nicely-labelled set of values shown in the UI.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import numpy as np


class Structure(ABC):
    key = ""
    display_name = ""
    n_ports = 2          # required port count

    @abstractmethod
    def extract(self, net, f_extract, n_segments=None, iso_r=True):
        """Return (CircuitIR, metrics, rows) with the lumped values read off near
        `f_extract` [Hz].  `n_segments` sets the ladder stage count for structures
        that use one (the RLGC line); `iso_r` toggles the isolation resistor for the
        Wilkinson dividers; other structures ignore them.  Raises ValueError if not
        applicable."""

    @staticmethod
    def nearest_index(f, f_extract):
        """Index of the (positive) frequency sample closest to `f_extract` [Hz]."""
        f = np.asarray(f, float)
        idx = np.where(f > 0)[0]
        if idx.size == 0:
            return 0
        return int(idx[np.argmin(np.abs(f[idx] - float(f_extract)))])

    def schematic_drawing(self, ir):
        """Return a schemdraw.Drawing for the extracted IR (or None)."""
        return None

    def freq_traces(self, net, model_s):
        """Optional extra frequency-domain traces for the Plot view.

        Returns a dict {label: {"top": spec, "bottom": spec}} or None, where each
        spec is {"title", "ylabel", "data", "model"} with data/model arrays over
        the network's frequency grid.  Default: no extra traces.
        """
        return None

    def default_plots(self):
        """Preferred initial plot selectors (list of 4 labels), or None to use
        the default S-parameter set."""
        return None
