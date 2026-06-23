"""structures/wilkinson.py - 3-port lumped-element Wilkinson power dividers.

Two selectable models:

  * Wilkinson (quadrature) - the full circuit of Fig. 1 of Kawai et al.: a parallel
    LC-ladder divider (shunt L1, a series C1 into each arm), a series Rint+Lint
    isolation network, and +/-45 deg phase shifters on the outputs (a T-network
    series C2 / shunt L2 / series C2 to port 2, a Pi-network shunt C3 / series L3 /
    shunt C3 to port 3) -> |S21|=|S31|=-3 dB with 90 deg between the outputs.

  * Wilkinson (in-phase) - the classic divider: each quarter-wave arm is a lumped
    pi-section (shunt C, series L, shunt C) of Zc = sqrt(2)*Z0, the two outputs
    bridged by a 2*Z0 isolation resistor -> |S21|=|S31|=-3 dB *in phase* (both at
    -90 deg at f0, matching a real quarter-wave Wilkinson).

Both synthesise from the device centre frequency f0 (the input-match minimum, or the
requested f_extract if in band) and the port impedance Z0:
    L = L_norm * Z0/w0,   C = C_norm / (Z0*w0),   R = R_norm * Z0.

Reference: T. Kawai, H. Mizuno, I. Ohta and A. Enokihara, "Lumped-element quadrature
Wilkinson power divider," 2009 Asia Pacific Microwave Conference, pp. 1012-1015,
doi:10.1109/APMC.2009.5384352  (https://ieeexplore.ieee.org/document/5384352).
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label


class Wilkinson(Structure):
    key = "wilkinson"
    display_name = "Wilkinson (quadrature)"
    n_ports = 3

    def extract(self, net, f_extract, n_segments=None, iso_r=True):   # both: unused here
        # The quadrature divider always keeps its Rint+Lint isolation network. The
        # iso_r toggle applies only to the in-phase model (see WilkinsonInphase).
        if net.nports != 3:
            raise ValueError("Wilkinson model needs a 3-port (.s3p)")
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        # centre frequency f0: the requested f_extract if it is in band, otherwise
        # the best input match (|S11| minimum), which is the divider's design point
        if f[0] <= f_extract <= f[-1]:
            k = self.nearest_index(f, f_extract)
        else:
            k = int(np.argmin(np.abs(net.s[:, 0, 0])))
        f0 = float(f[k])
        w0 = 2 * np.pi * f0

        Lu = z0 / w0                            # normalised-1 inductor
        Cu = 1.0 / (z0 * w0)                    # normalised-1 capacitor
        r2 = np.sqrt(2.0)
        L1 = Lu; C1 = Cu; Lint = Lu; Rint = z0          # divider + isolation
        L2 = r2 * Lu; C2 = (1.0 + r2) * Cu              # T-network (-45 deg)
        L3 = (1.0 / r2) * Lu; C3 = (r2 - 1.0) * Cu      # Pi-network (+45 deg)

        ir = CircuitIR(name="wilkinson", ports=["p1", "p2", "p3"], physical=True)
        ir.comments.append(
            f"lumped quadrature Wilkinson divider, f0 = {f0/1e9:.2f} GHz")
        # parallel LC-ladder divider
        ir.add(Element("L", "L1", ("p1", "0"), L1, label="L_1"))     # shunt L1
        ir.add(Element("C", "C1t", ("p1", "nA"), C1, label="C_1"))   # series C1, top
        ir.add(Element("C", "C1b", ("p1", "nB"), C1, label="C_1"))   # series C1, bottom
        # series Rint + Lint isolation between the two arms (always present)
        ir.add(Element("R", "Rint", ("nA", "iso"), Rint, label="R_int"))
        ir.add(Element("L", "Lint", ("iso", "nB"), Lint, label="L_int"))
        # T-network (series C2, shunt L2, series C2) -> port 2
        ir.add(Element("C", "C2a", ("nA", "nT"), C2, label="C_2"))
        ir.add(Element("L", "L2", ("nT", "0"), L2, label="L_2"))
        ir.add(Element("C", "C2b", ("nT", "p2"), C2, label="C_2"))
        # Pi-network (shunt C3, series L3, shunt C3) -> port 3
        ir.add(Element("C", "C3a", ("nB", "0"), C3, label="C_3"))
        ir.add(Element("L", "L3", ("nB", "p3"), L3, label="L_3"))
        ir.add(Element("C", "C3b", ("p3", "0"), C3, label="C_3"))

        metrics = {"f_extract": f0}
        rows = [("L_1", L1, "H"), ("C_1", C1, "F"),
                ("L_2", L2, "H"), ("C_2", C2, "F"),
                ("L_3", L3, "H"), ("C_3", C3, "F"),
                ("L_int", Lint, "H"), ("R_int", Rint, "Ω")]
        return ir, metrics, rows

    def default_plots(self):
        return ["S11", "S21", "S31", "S23"]    # match, the two splits, isolation

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        d = sd.Drawing(show=False); d.config(unit=1.5, fontsize=11)

        def shunt(el, val, lab):
            d.push()
            el().down().label(comp_label(lab, val, _unit(lab)))
            elm.Ground()
            d.pop()

        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            elm.Line().right().length(0.6)
            elm.Dot()
            shunt(elm.Inductor2, v["L1"], "L_1")            # shunt L1 (its own node)
            elm.Line().right().length(0.8)
            split = elm.Dot()
            # ---- top arm: series C1 -> nA -> T-network (C2, shunt L2, C2) -> P2 ----
            d.push()
            elm.Line().up().length(2.4)
            elm.Capacitor().right().label(comp_label("C_1", v["C1t"], "F"))
            nA = elm.Dot()
            elm.Capacitor().right().label(comp_label("C_2", v["C2a"], "F"))
            elm.Dot()
            shunt(elm.Inductor2, v["L2"], "L_2")
            elm.Capacitor().right().label(comp_label("C_2", v["C2b"], "F"))
            elm.Line().right().length(0.5)
            elm.Dot(open=True).label(port_label(2), loc="right")
            d.pop()                                         # back to the split node
            # ---- bottom arm: series C1 -> nB -> Pi-network (C3, L3, C3) -> P3 ----
            elm.Line().down().length(2.4)
            elm.Capacitor().right().label(comp_label("C_1", v["C1b"], "F"))
            nB = elm.Dot()
            shunt(elm.Capacitor, v["C3a"], "C_3")
            elm.Inductor2().right().label(comp_label("L_3", v["L3"], "H"))
            elm.Dot()
            shunt(elm.Capacitor, v["C3b"], "C_3")
            elm.Line().right().length(0.5)
            elm.Dot(open=True).label(port_label(3), loc="right")
            # ---- Rint + Lint isolation between nA (top) and nB (bottom) ----
            if "Rint" in v:
                ax, ay = nA.center; bx, by = nB.center
                mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
                elm.Resistor().endpoints((ax, ay), (mx, my)).label(
                    comp_label("R_int", v["Rint"], "Ω"))
                elm.Inductor2().endpoints((mx, my), (bx, by)).label(
                    comp_label("L_int", v["Lint"], "H"))
        return d


class WilkinsonInphase(Structure):
    """Classic in-phase Wilkinson: two lumped quarter-wave pi-section arms."""
    key = "wilkinson-inphase"
    display_name = "Wilkinson (in-phase)"
    n_ports = 3

    def extract(self, net, f_extract, n_segments=None, iso_r=True):   # n_segments: unused
        if net.nports != 3:
            raise ValueError("Wilkinson model needs a 3-port (.s3p)")
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        if f[0] <= f_extract <= f[-1]:
            k = self.nearest_index(f, f_extract)
        else:
            k = int(np.argmin(np.abs(net.s[:, 0, 0])))
        f0 = float(f[k])
        w0 = 2 * np.pi * f0

        Zc = np.sqrt(2.0) * z0                  # quarter-wave arm impedance
        L = Zc / w0                             # pi-section series inductor
        C = 1.0 / (Zc * w0)                     # pi-section shunt capacitor
        R = 2.0 * z0                            # output isolation resistor

        ir = CircuitIR(name="wilkinson_inphase", ports=["p1", "p2", "p3"], physical=True)
        ir.comments.append(
            f"lumped in-phase Wilkinson divider, f0 = {f0/1e9:.2f} GHz, Zc = {Zc:.1f} ohm")
        for p in ("p2", "p3"):                  # two pi-section quarter-wave arms
            ir.add(Element("C", f"Cin_{p}", ("p1", "0"), C, label="C"))
            ir.add(Element("L", f"L_{p}", ("p1", p), L, label="L"))
            ir.add(Element("C", f"Cout_{p}", (p, "0"), C, label="C"))
        if iso_r:                               # optional output isolation resistor
            ir.add(Element("R", "Riso", ("p2", "p3"), R, label="R_iso"))

        metrics = {"f_extract": f0, "Zc": float(Zc)}
        rows = [("Z_c", float(Zc), "Ω"), ("L", float(L), "H"), ("C", float(C), "F")]
        if iso_r:
            rows.append(("R_iso", float(R), "Ω"))
        return ir, metrics, rows

    def default_plots(self):
        return ["S11", "S21", "S31", "S23"]    # match, the two splits, isolation

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        Cl = comp_label("C", v["Cin_p2"], "F"); Ll = comp_label("L", v["L_p2"], "H")
        R = v.get("Riso")
        d = sd.Drawing(show=False); d.config(unit=1.5, fontsize=10)

        def cap(up):
            """Shunt C to ground, pointing away from the centre rail."""
            d.push()
            (elm.Capacitor().up() if up else elm.Capacitor().down()).label(
                Cl, loc="top" if up else "bottom")
            elm.Ground()
            d.pop()

        def arm(up):
            """One pi-section arm: shunt C, series L, shunt C, then the run out to
            the output port.  Shunt caps point away from the centre; the series-L
            label sits on the inner side so it stays clear of the cap labels.  A
            junction node is only drawn when the isolation resistor connects there."""
            (elm.Line().up() if up else elm.Line().down()).length(2.0)
            elm.Dot(); cap(up)                          # input-side shunt C (at p1)
            elm.Inductor2().right().length(2.0).label(Ll, loc="bottom" if up else "top")
            elm.Dot(); cap(up)                          # output-side shunt C
            if R is None:                               # no resistor -> plain run, no node
                elm.Line().right().length(1.4)
                return None
            elm.Line().right().length(0.8)
            node = elm.Dot()                            # isolation-resistor node
            elm.Line().right().length(0.6)
            return node

        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            elm.Line().right().length(0.7)
            elm.Dot()
            d.push()
            nA = arm(True)                              # top arm -> P2
            elm.Dot(open=True).label(port_label(2), loc="right")
            d.pop()
            nB = arm(False)                             # bottom arm -> P3
            elm.Dot(open=True).label(port_label(3), loc="right")
            if R is not None:                           # optional isolation resistor
                elm.Resistor().endpoints(nA.center, nB.center).label(
                    comp_label("R_iso", R, "Ω"), loc="right")
        return d


def _unit(label):
    return "H" if label.startswith("L") else "F" if label.startswith("C") else "Ω"
