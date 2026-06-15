"""structures/mim_cap.py - 2-port MIM capacitor model extraction.

Series path: a main capacitor C_s with a small parasitic series L_s and loss R_s;
shunt path: a plate-to-substrate C at each port.  C_s is taken at low frequency
(where the series L has negligible effect); L_s/R_s at a higher frequency
(standard network-theory extraction, in the spirit of mim_from_s2p).
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label
from .inductor_pi import pi_branches


class MimCap(Structure):
    key = "mim-cap"
    display_name = "MIM capacitor"
    n_ports = 2

    def extract(self, net):
        if net.nports != 2:
            raise ValueError("MIM model needs a 2-port (.s2p)")
        f = net.f
        w = 2 * np.pi * f
        Zs, Zsh1, Zsh2 = pi_branches(net)

        lo = int(np.argmin(np.abs(f - max(f[-1] / 20.0, f[f > 0][0]))))
        hi = int(np.argmin(np.abs(f - 0.6 * f[-1])))
        Cs = float(-1.0 / (w[lo] * Zs.imag[lo]))          # series C at low f
        # series L from the residual reactance at the higher frequency
        Xres = Zs.imag[hi] + 1.0 / (w[hi] * Cs)
        Ls = float(Xres / w[hi])
        Rs = float(Zs.real[hi])
        Cp1 = float(-1.0 / (w[hi] * Zsh1.imag[hi])) if Zsh1.imag[hi] != 0 else 0.0
        Cp2 = float(-1.0 / (w[hi] * Zsh2.imag[hi])) if Zsh2.imag[hi] != 0 else 0.0

        ir = CircuitIR(name="mim_cap", ports=["p1", "p2"], physical=True)
        ir.comments.append(f"MIM model: C_s at {f[lo]/1e9:.2f} GHz, L_s/R_s at {f[hi]/1e9:.2f} GHz")
        ir.add(Element("C", "Cs", ("p1", "n1"), max(Cs, 0.0), label="C_s"))
        ir.add(Element("L", "Ls", ("n1", "n2"), max(Ls, 0.0), label="L_s"))
        ir.add(Element("R", "Rs", ("n2", "p2"), max(Rs, 0.0), label="R_s"))
        ir.add(Element("C", "C1", ("p1", "0"), max(Cp1, 0.0), label="C_p1"))
        ir.add(Element("C", "C2", ("p2", "0"), max(Cp2, 0.0), label="C_p2"))

        metrics = {"Cs": max(Cs, 0.0), "f_extract": float(f[hi])}
        rows = [("C_s", max(Cs, 0.0), "F"), ("L_s", max(Ls, 0.0), "H"),
                ("R_s", max(Rs, 0.0), "\u03a9"),
                ("C_p1", max(Cp1, 0.0), "F"), ("C_p2", max(Cp2, 0.0), "F")]
        return ir, metrics, rows

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        d = sd.Drawing(show=False); d.config(unit=2.0, fontsize=12)
        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            d.push()
            elm.Capacitor().down().label(comp_label("C_p1", v.get("C1"), "F"))
            elm.Ground()
            d.pop()
            elm.Capacitor().right().label(comp_label("C_s", v.get("Cs"), "F", sep="  "))
            elm.Inductor2().right().label(comp_label("L_s", v.get("Ls"), "H", sep="  "))
            elm.Resistor().right().label(comp_label("R_s", v.get("Rs"), "\u03a9", sep="  "))
            elm.Dot()
            d.push()
            elm.Capacitor().down().label(comp_label("C_p2", v.get("C2"), "F"))
            elm.Ground()
            d.pop()
            elm.Line().right().length(1.0)
            elm.Dot(open=True).label(port_label(2), loc="right")
        return d
