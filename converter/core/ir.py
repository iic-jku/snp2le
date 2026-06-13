"""ir.py - the dialect-agnostic Circuit IR.

Both the universal macromodel and the structure-specific extractors produce a
CircuitIR.  The netlist backends (ngspice SPICE3, VACASK Spectre) and the
schematic drawer all render *from* this single representation, so every output
stays consistent regardless of which mode produced the circuit.

Element kinds (SPICE-style):
    R  node+ node-                value          resistor
    C  node+ node-                value          capacitor
    L  node+ node-                value          inductor
    V  node+ node-                value          independent v-source (0 = probe)
    G  node+ node- ctrl+ ctrl-    gain           VCCS
    E  node+ node- ctrl+ ctrl-    gain           VCVS
    F  node+ node- vname          gain           CCCS (controlled by current in V)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Element:
    kind: str                       # R C L V G E F
    name: str
    nodes: tuple                    # connection nodes
    value: float = 0.0
    ctrl: tuple = ()                # controlling nodes (G/E) or (vname,) (F)
    label: str = ""                 # math spec for display, e.g. "L_s" (defaults to name)


@dataclass
class CircuitIR:
    name: str = "s_equivalent"
    ports: list = field(default_factory=list)     # ordered external port nodes
    elements: list = field(default_factory=list)  # list[Element]
    comments: list = field(default_factory=list)  # provenance / header notes
    physical: bool = False          # True for structure models (interpretable)

    def add(self, el: Element):
        self.elements.append(el)
        return el

    def value_rows(self):
        """(label, value, unit) rows for the values table (physical models)."""
        unit = {"R": "\u03a9", "C": "F", "L": "H"}
        rows = []
        for e in self.elements:
            if e.kind in unit:
                rows.append((e.label or e.name, e.value, unit[e.kind]))
        return rows
