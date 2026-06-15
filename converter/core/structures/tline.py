"""structures/tline.py - 2-port transmission-line (RLGC) ladder model.

From the ABCD matrix we recover the electrical length gamma*l and characteristic
impedance Zc, then synthesise N cascaded pi-cells whose cascade exactly matches
the line at the extraction frequency: series Z_cell = Zc*sinh(theta), shunt
Y_cell = (2/Zc)*tanh(theta/2) with theta = gamma*l/N.  Each cell is an R-L series
branch plus shunt C and a shunt R (the dielectric loss G -> R = 1/G).
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label

N_SEGMENTS = 4          # number of pi-cells in the ladder


class TransmissionLine(Structure):
    key = "tline-rlgc"
    display_name = "Transmission line (RLGC)"
    n_ports = 2

    def extract(self, net):
        if net.nports != 2:
            raise ValueError("transmission-line model needs a 2-port (.s2p)")
        f = net.f
        w = 2 * np.pi * f
        A = net.a[:, 0, 0]; B = net.a[:, 0, 1]; C = net.a[:, 1, 0]
        k = int(np.argmin(np.abs(f - 0.5 * f[-1])))        # mid-band extraction
        gl = np.arccosh(A[k])
        Zc = np.sqrt(B[k] / C[k]) if C[k] != 0 else np.sqrt(B[k])
        n = N_SEGMENTS
        theta = gl / n
        Zcell = Zc * np.sinh(theta)
        Ycell = (2.0 / Zc) * np.tanh(theta / 2.0)
        wk = w[k]
        R_seg = float(abs(Zcell.real)); L_seg = float(abs(Zcell.imag / wk))
        G_seg = float(abs(Ycell.real)); C_seg = float(abs(Ycell.imag / wk))
        Rsh = 1.0 / G_seg if G_seg > 1e-15 else 1e12

        ir = CircuitIR(name="tline_rlgc", ports=["p1", "p2"], physical=True)
        ir.comments.append(f"RLGC line, {n} pi-cells, extracted at {f[k]/1e9:.2f} GHz")
        nodes = ["p1"] + [f"n{i}" for i in range(1, n)] + ["p2"]
        for i in range(n):                                  # series branches
            a, b = nodes[i], nodes[i + 1]
            mid = f"s{i}"
            ir.add(Element("L", f"Ls{i+1}", (a, mid), L_seg, label="L_s"))
            ir.add(Element("R", f"Rs{i+1}", (mid, b), R_seg, label="R_s"))
        for i, node in enumerate(nodes):                    # shunt branches
            half = 0.5 if (i == 0 or i == len(nodes) - 1) else 1.0
            ir.add(Element("C", f"Csh{i}", (node, "0"), C_seg * half, label="C_sh"))
            ir.add(Element("R", f"Rsh{i}", (node, "0"), Rsh / half, label="R_sh"))

        metrics = {"segments": n, "f_extract": float(f[k]),
                   "Zc": float(abs(Zc))}
        rows = [("N_seg", float(n), ""),
                ("Z_c", float(abs(Zc)), "\u03a9"),
                ("R_s", R_seg, "\u03a9"), ("L_s", L_seg, "H"),
                ("C_sh", C_seg, "F"), ("R_sh", Rsh, "\u03a9")]
        return ir, metrics, rows

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        segs = sorted({int(e.name[2:]) for e in ir.elements if e.name.startswith("Ls")})
        L_seg = next(e.value for e in ir.elements if e.name == "Ls1")
        R_seg = next(e.value for e in ir.elements if e.name == "Rs1")
        C_sh = next(e.value for e in ir.elements if e.name == "Csh1")
        show = min(len(segs), 3)
        d = sd.Drawing(show=False); d.config(unit=1.6, fontsize=11)
        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            for i in range(show):
                d.push(); elm.Capacitor().down().label(comp_label("C_sh")); elm.Ground(); d.pop()
                elm.Inductor2().right().label(comp_label("L_s"))
                elm.Resistor().right().label(comp_label("R_s"))
                elm.Dot()
            if len(segs) > show:
                elm.Line().right().length(0.6).label(r"$\cdots$")
            d.push(); elm.Capacitor().down().label(comp_label("C_sh")); elm.Ground(); d.pop()
            elm.Line().right().length(0.8)
            elm.Dot(open=True).label(port_label(2), loc="right")
        return d
