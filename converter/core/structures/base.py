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
        that use one (the RLGC line).  `iso_r` toggles the isolation resistor for the
        Wilkinson dividers.  Other structures ignore them.  Raises ValueError if not
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

    def value_drift(self, net, value_rows, f_extract):
        """Per-element tolerance at the extraction frequency: {label: percent}.

        Returns, per value-row label, how far the parameter the measured data implies
        at f_ext differs from the model value (see `fext_tolerance_pct`).  Directly
        read reciprocal terms (e.g. the series L, R) match exactly (0 %).  Terms the
        model can only approximate (e.g. a shunt averaged over two asymmetric ports)
        carry the residual.  Frequency dispersion away from f_ext is left to the
        plots.  Default: no tolerance info (a purely synthesised model with no
        data-side decomposition)."""
        return {}

    @staticmethod
    def fext_tolerance_pct(curve, x0, f, f_extract):
        """Tolerance of a data-derived parameter `curve` (over frequency) against the
        model value `x0`, evaluated at the extraction frequency, in percent:

            |curve(f_ext) - x0| / |x0| * 100

        taken at the (positive) frequency sample nearest f_extract.  NaN when undefined."""
        c = np.asarray(curve, dtype=float)
        if not np.isfinite(x0) or x0 == 0:
            return float("nan")
        fa = np.asarray(f, dtype=float)
        pos = np.where(fa > 0)[0]
        if pos.size == 0:
            return float("nan")
        k = int(pos[np.argmin(np.abs(fa[pos] - float(f_extract)))])
        val = c[k]
        if not np.isfinite(val):
            return float("nan")
        return float(abs(val - x0) / abs(x0) * 100.0)
