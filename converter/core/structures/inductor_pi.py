"""structures/inductor_pi.py - 2-port inductor pi-model extraction.

Classic on-chip inductor pi-equivalent: a series R-L branch between the two ports
and a shunt C (with substrate R) at each port.  Series/shunt branches are split
from the Y-parameters using the averaged mutual term ymn=(y12+y21)/2, and values
are evaluated at the frequency of peak quality factor (network theory, in the
spirit of Volker Muehlhaus' pi_from_s2p).
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label


def pi_branches(net):
    """Split a 2-port into (Zseries, Zshunt1, Zshunt2) over frequency."""
    Y = net.y
    y11 = Y[:, 0, 0]; y12 = Y[:, 0, 1]; y21 = Y[:, 1, 0]; y22 = Y[:, 1, 1]
    ymn = 0.5 * (y12 + y21)
    Zseries = -1.0 / ymn
    Zshunt1 = 1.0 / (y11 + ymn)
    Zshunt2 = 1.0 / (y22 + ymn)
    return Zseries, Zshunt1, Zshunt2


class InductorPi(Structure):
    key = "inductor-pi"
    display_name = "Inductor (\u03c0-model)"
    n_ports = 2

    def extract(self, net):
        if net.nports != 2:
            raise ValueError("inductor π-model needs a 2-port (.s2p)")
        f = net.f
        good = f > 0
        w = 2 * np.pi * f
        Zs, Zsh1, Zsh2 = pi_branches(net)

        # differential series impedance -> Q over frequency; extract at peak Q
        Zdiff = net.z[:, 0, 0] - net.z[:, 0, 1] - net.z[:, 1, 0] + net.z[:, 1, 1]
        Q = np.where(Zdiff.real != 0, Zdiff.imag / Zdiff.real, 0.0)
        k = int(np.argmax(np.where(good, Q, -np.inf)))

        Rs = float(Zs.real[k])
        Ls = float(Zs.imag[k] / w[k])
        C1 = float(-1.0 / (w[k] * Zsh1.imag[k])) if Zsh1.imag[k] != 0 else 0.0
        C2 = float(-1.0 / (w[k] * Zsh2.imag[k])) if Zsh2.imag[k] != 0 else 0.0
        R1 = float(Zsh1.real[k]); R2 = float(Zsh2.real[k])
        R1 = R1 if R1 > 1.0 else 1e12                  # near-zero real -> lossless (open)
        R2 = R2 if R2 > 1.0 else 1e12

        ir = CircuitIR(name="inductor_pi", ports=["p1", "p2"], physical=True)
        ir.comments.append(f"inductor pi-model, extracted at peak-Q ({f[k]/1e9:.2f} GHz)")
        ir.add(Element("L", "Ls", ("p1", "n_s"), max(Ls, 0.0), label="L_s"))
        ir.add(Element("R", "Rs", ("n_s", "p2"), max(Rs, 0.0), label="R_s"))
        ir.add(Element("C", "C1", ("p1", "0"), max(C1, 0.0), label="C_p1"))
        ir.add(Element("R", "R1", ("p1", "0"), R1, label="R_p1"))
        ir.add(Element("C", "C2", ("p2", "0"), max(C2, 0.0), label="C_p2"))
        ir.add(Element("R", "R2", ("p2", "0"), R2, label="R_p2"))

        metrics = {"Q_peak": float(Q[k]), "f_extract": float(f[k]),
                   "Ls": max(Ls, 0.0), "Rs": max(Rs, 0.0)}
        rows = [("L_s", max(Ls, 0.0), "H"), ("R_s", max(Rs, 0.0), "\u03a9"),
                ("C_p1", max(C1, 0.0), "F"), ("R_p1", R1, "\u03a9"),
                ("C_p2", max(C2, 0.0), "F"), ("R_p2", R2, "\u03a9")]
        return ir, metrics, rows

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        d = sd.Drawing(show=False); d.config(unit=2.2, fontsize=13)
        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            d.push()
            elm.Capacitor().down().label(comp_label("C_p1", v.get("C1"), "F"))
            elm.Ground()
            d.pop()
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
