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


class Structure(ABC):
    key = ""
    display_name = ""
    n_ports = 2          # required port count

    @abstractmethod
    def extract(self, net):
        """Return (CircuitIR, metrics, rows). Raises ValueError if not applicable."""

    def schematic_drawing(self, ir):
        """Return a schemdraw.Drawing for the extracted IR (or None)."""
        return None
