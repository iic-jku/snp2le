"""structures/branchline.py - 4-port lumped-element branch-line (quadrature) coupler.

The classic pi-LP-pi-LP parallel-branch design: the distributed branch-line hybrid
is a square of four quarter-wave lines (two series (main-line) arms of Zc = Z0/sqrt2
and two shunt (branch) arms of Zc = Z0), each replaced by a lumped low-pass pi-section
(shunt C, series L, shunt C).  The corner shunt capacitors of the two arms meeting at
each port merge, leaving one capacitor per corner:

    series arm   L_se = (Z0/sqrt2)/w0          (ports 1-2 and 4-3)
    shunt arm    L_sh =  Z0/w0                  (ports 1-4 and 2-3)
    corner cap   C    = (1 + sqrt2)/(Z0*w0)     (one per port node)

This is a 3 dB quadrature coupler: |S21|=|S31|=-3 dB with the direct (port 2) and
coupled (port 3) outputs 90 deg apart, a matched input (port 1) and an isolated
port 4 (the paper's -90 deg / 180 deg phase class).  Synthesised at the device
centre frequency f0 (the requested f_extract if in band, else the best overall
match) and the port impedance Z0.

With `iso_r` (the "arm loss" option) the ideal lossless arms get a series resistance
R = w0*L/Q, with a single arm quality factor Q fitted so the model dissipates the
same power as the device at f0.  This lifts the reflection terms off the ideal null
toward the measured values.  The residual finite isolation/directivity is asymmetry,
not loss, and is left to the ideal model.

Reference: R. Knoechel and W. Taute, "Characteristics of Lumped Element Branch Line
Couplers," (Christian-Albrechts-Universitaet zu Kiel).  The pi-LP-pi-LP parallel
branch design of Table I.
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label

# square arms: (node a, node b, tag), series 1-2 & 4-3, shunt 1-4 & 2-3
_ARMS = (("p1", "p2", "se"), ("p4", "p3", "se"),
         ("p1", "p4", "sh"), ("p2", "p3", "sh"))


class BranchLineCoupler(Structure):
    key = "branchline"
    display_name = "Branch-line coupler"
    n_ports = 4

    @staticmethod
    def _build_ir(L_se, L_sh, R_se, R_sh, C):
        """Assemble the coupler IR.  Each arm is a series L (+ series R when lossy)."""
        ir = CircuitIR(name="branchline", ports=["p1", "p2", "p3", "p4"], physical=True)
        LR = {"se": (L_se, R_se), "sh": (L_sh, R_sh)}
        for i, (a, b, tag) in enumerate(_ARMS):
            L, R = LR[tag]
            if R > 0:
                mid = f"n{i}"
                ir.add(Element("L", f"L{i}", (a, mid), L, label=f"L_{tag}"))
                ir.add(Element("R", f"R{i}", (mid, b), R, label=f"R_{tag}"))
            else:
                ir.add(Element("L", f"L{i}", (a, b), L, label=f"L_{tag}"))
        for i, p in enumerate(("p1", "p2", "p3", "p4"), 1):
            ir.add(Element("C", f"C{i}", (p, "0"), C, label="C"))
        return ir

    def extract(self, net, f_extract, n_segments=None, iso_r=True):   # n_segments: unused
        if net.nports != 4:
            raise ValueError("branch-line coupler model needs a 4-port (.s4p)")
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        # centre frequency f0: requested f_extract if in band, else the best overall
        # match (minimum total reflection), which is the coupler's design point
        if f[0] <= f_extract <= f[-1]:
            k = self.nearest_index(f, f_extract)
        else:
            refl = np.sum(np.abs(net.s[:, range(4), range(4)]) ** 2, axis=1)
            k = int(np.argmin(refl))
        f0 = float(f[k]); w0 = 2 * np.pi * f0

        L_se = z0 / (np.sqrt(2.0) * w0)         # series (main-line) arm, Z0/sqrt2
        L_sh = z0 / w0                          # shunt (branch) arm, Z0
        C = (1.0 + np.sqrt(2.0)) / (z0 * w0)    # merged corner capacitor

        R_se = R_sh = 0.0; Q = None
        if iso_r:                               # arm loss: fit a single arm Q
            Q = self._fit_arm_q(net, k, f0, z0, L_se, L_sh, C)
            R_se = w0 * L_se / Q; R_sh = w0 * L_sh / Q

        ir = self._build_ir(L_se, L_sh, R_se, R_sh, C)
        note = f"lumped branch-line (quadrature) coupler, f0 = {f0/1e9:.2f} GHz"
        if iso_r:
            note += f", arm Q = {Q:.0f}"
        ir.comments.append(note)

        metrics = {"f_extract": f0}
        rows = [("L_se", float(L_se), "H"), ("L_sh", float(L_sh), "H"),
                ("C", float(C), "F")]
        if iso_r:
            rows += [("R_se", float(R_se), "Ω"), ("R_sh", float(R_sh), "Ω"),
                     ("Q", float(Q), "")]
        return ir, metrics, rows

    def _fit_arm_q(self, net, k, f0, z0, L_se, L_sh, C):
        """Single arm quality factor Q whose dissipation matches the device at f0."""
        from .. import mna
        w0 = 2 * np.pi * f0
        target = 1.0 - float(np.sum(np.abs(net.s[k, :, 0]) ** 2))   # data dissipation
        if target <= 2e-3:
            return 1e6                          # essentially lossless data
        def diss(Q):
            ir = self._build_ir(L_se, L_sh, w0 * L_se / Q, w0 * L_sh / Q, C)
            S = mna.rlc_sparams(ir, np.array([f0]), z0=z0)[0]
            return 1.0 - float(np.sum(np.abs(S[:, 0]) ** 2))
        lo, hi = 2.0, 1000.0                    # dissipation decreases with Q
        if diss(lo) < target:                   # device lossier than Q=2 can model
            return lo
        for _ in range(40):                     # geometric bisection
            mid = np.sqrt(lo * hi)
            if diss(mid) > target:
                lo = mid
            else:
                hi = mid
        return float(np.sqrt(lo * hi))

    def default_plots(self):
        return ["S11", "S21", "S31", "S41"]    # match, through, coupled, isolation

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        has_R = any(e.kind == "R" for e in ir.elements)     # lossy arms
        Lse = comp_label("L_se"); Lsh = comp_label("L_sh"); Cl = comp_label("C")
        Rse = comp_label("R_se"); Rsh = comp_label("R_sh")
        d = sd.Drawing(show=False); d.config(unit=1.6, fontsize=11)
        W, H = 4.8, 3.6
        p1, p2, p3, p4 = (0, H), (W, H), (W, 0), (0, 0)

        def harm(a, b, Ll, Rl, loc):            # horizontal arm: series L (+ R)
            if has_R:
                sp = (a[0] + 0.58 * (b[0] - a[0]), a[1])
                elm.Inductor2().endpoints(a, sp).label(Ll, loc=loc)
                elm.Resistor().endpoints(sp, b).label(Rl, loc=loc)
            else:
                elm.Inductor2().endpoints(a, b).label(Ll, loc=loc)

        def varm(a, b, Ll, Rl, xs):             # vertical arm (a top, b bottom)
            if has_R:
                sp = (a[0], a[1] + 0.55 * (b[1] - a[1]))
                elm.Inductor2().endpoints(a, sp)
                elm.Resistor().endpoints(sp, b)
                elm.Label().at((a[0] + xs, (a[1] + sp[1]) / 2)).label(Ll)
                elm.Label().at((a[0] + xs, (sp[1] + b[1]) / 2)).label(Rl)
            else:
                elm.Inductor2().endpoints(a, b)
                elm.Label().at((a[0] + xs, (a[1] + b[1]) / 2)).label(Ll)

        def corner(pt, up, side, n):
            d.push()
            cap = elm.Capacitor().at(pt)
            (cap.up() if up else cap.down()).label(Cl)
            elm.Ground()
            d.pop()
            elm.Dot(open=True).at(pt).label(port_label(n), loc=side)

        with d:
            harm(p1, p2, Lse, Rse, "top")       # top series arm
            harm(p4, p3, Lse, Rse, "bottom")    # bottom series arm
            varm(p1, p4, Lsh, Rsh, -0.62)       # left shunt arm
            varm(p2, p3, Lsh, Rsh, +0.62)       # right shunt arm
            corner(p1, True, "left", 1)         # input
            corner(p2, True, "right", 2)        # through
            corner(p3, False, "right", 3)       # coupled
            corner(p4, False, "left", 4)        # isolated
        return d
