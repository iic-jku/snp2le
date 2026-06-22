"""structures/balun.py - 4-port lumped-element transformer balun.

A symmetric coupled-coil balun (primary ports 1-2, secondary ports 3-4).  From the
4-port Z-matrix we read the *differential* primary / secondary impedances and the
primary-to-secondary mutual via the differential port vectors a = (1,-1,0,0) and
b = (0,0,1,-1):

    Zpp = a Z a,  Zss = b Z b,  Zps = a Z b
    Lp = Im(Zpp)/w,  Rp = Re(Zpp),   Ls = Im(Zss)/w,  Rs = Re(Zss)
    M  = Im(Zps)/w,  k = M/sqrt(Lp*Ls),  n = sqrt(Lp/Ls)

Each winding is then split into two equal halves about a (floating) centre tap and
the same-side halves are magnetically coupled with k - exactly the reference
sym_balun model (each half L = Lp/2, series R = Rp/2, K1: L5<->L9, K2: L7<->L8).
The extraction follows extract_balun_lumped.py; the netlist matches balun.spice.
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label

# differential port combinations: primary = ports (1,2), secondary = ports (3,4)
_A = np.array([1.0, -1.0, 0.0, 0.0])
_B = np.array([0.0, 0.0, 1.0, -1.0])


def _balun_decomp(s, f, z0):
    """Differential balun quantities over frequency from the 4-port S-parameters."""
    import skrf
    Z = skrf.network.s2z(np.asarray(s), z0=z0)
    w = 2 * np.pi * f
    Zpp = np.einsum("i,kij,j->k", _A, Z, _A)
    Zss = np.einsum("i,kij,j->k", _B, Z, _B)
    Zps = np.einsum("i,kij,j->k", _A, Z, _B)
    with np.errstate(divide="ignore", invalid="ignore"):
        Lp = Zpp.imag / w; Ls = Zss.imag / w; M = Zps.imag / w
        k = M / np.sqrt(Lp * Ls)
        Qp = Zpp.imag / Zpp.real; Qs = Zss.imag / Zss.real
    return {"Lp": Lp, "Rp": Zpp.real, "Ls": Ls, "Rs": Zss.real,
            "M": M, "k": k, "Qp": Qp, "Qs": Qs}


class Balun(Structure):
    key = "balun"
    display_name = "Balun (transformer)"
    n_ports = 4

    def extract(self, net, f_extract, n_segments=None, iso_r=True):   # last two: unused
        if net.nports != 4:
            raise ValueError("balun model needs a 4-port (.s4p)")
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        if f[0] <= f_extract <= f[-1]:
            k = self.nearest_index(f, f_extract)
        else:                                          # default to mid-band
            k = int(np.argmin(np.abs(f - 0.5 * (f[0] + f[-1]))))
        f0 = float(f[k]); w0 = 2 * np.pi * f0

        Z = net.z[k]                                   # 4x4 Z at f0
        Zpp = _A @ Z @ _A; Zss = _B @ Z @ _B; Zps = _A @ Z @ _B
        Lp = max(float(Zpp.imag / w0), 1e-15); Rp = max(float(Zpp.real), 0.0)
        Ls = max(float(Zss.imag / w0), 1e-15); Rs = max(float(Zss.real), 0.0)
        M = float(Zps.imag / w0)
        kc = float(np.clip(M / np.sqrt(Lp * Ls), -0.999, 0.999))
        n = float(np.sqrt(Lp / Ls))
        Qp = w0 * Lp / Rp if Rp > 0 else float("inf")   # winding quality factors
        Qs = w0 * Ls / Rs if Rs > 0 else float("inf")

        # split each winding into two equal halves about a floating centre tap
        Lph = Lp / 2.0; Lsh = Ls / 2.0; Rph = Rp / 2.0; Rsh = Rs / 2.0
        ir = CircuitIR(name="balun", ports=["p1", "p2", "p3", "p4"], physical=True)
        ir.comments.append(
            f"transformer balun, f0 = {f0/1e9:.2f} GHz, k = {kc:.3f}, n = {n:.3f}")
        ir.comments.append("each winding split L/2 about a floating centre tap")
        # primary winding:   p1 -Rp/2- L5 -cp- L7 -Rp/2- p2
        ir.add(Element("R", "Rp1", ("p1", "n5"), Rph, label="R_p"))
        ir.add(Element("L", "L5", ("n5", "cp"), Lph, label="L_p"))
        ir.add(Element("L", "L7", ("cp", "n4"), Lph, label="L_p"))
        ir.add(Element("R", "Rp2", ("n4", "p2"), Rph, label="R_p"))
        # secondary winding: p3 -Rs/2- L8 -cs- L9 -Rs/2- p4
        ir.add(Element("R", "Rs1", ("p3", "n7"), Rsh, label="R_s"))
        ir.add(Element("L", "L8", ("n7", "cs"), Lsh, label="L_s"))
        ir.add(Element("L", "L9", ("cs", "n8"), Lsh, label="L_s"))
        ir.add(Element("R", "Rs2", ("n8", "p4"), Rsh, label="R_s"))
        # same-side halves couple (p1-side<->p4-side, p2-side<->p3-side)
        ir.add_coupling("L5", "L9", kc)
        ir.add_coupling("L7", "L8", kc)

        metrics = {"f_extract": f0, "k": kc, "n": n, "Qp": Qp, "Qs": Qs}
        rows = [("L_p", Lp, "H"), ("R_p", Rp, "Ω"), ("Q_p", Qp, ""),
                ("L_s", Ls, "H"), ("R_s", Rs, "Ω"), ("Q_s", Qs, ""),
                ("M", M, "H"), ("k", kc, ""), ("n", n, "")]
        return ir, metrics, rows

    def default_plots(self):
        return ["Lp / Rp", "Ls / Rs", "Qp / Qs", "k / M"]   # the four transformer views

    def freq_traces(self, net, model_s):
        """Frequency-domain trace sets for the Plot view (data vs model):
          * 'Lp / Rp' - primary differential inductance and resistance
          * 'Ls / Rs' - secondary differential inductance and resistance
          * 'Qp / Qs' - primary and secondary quality factors
          * 'k / M'   - coupling factor and mutual inductance
        """
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _balun_decomp(net.s, f, z0)
        M = _balun_decomp(model_s, f, z0) if model_s is not None else None
        k0 = int(np.argmin(np.abs(f - 0.5 * f[-1])))

        def md(key, scale=1.0):
            return None if M is None else M[key] * scale

        def trace(title, ylabel, data, model, ylim):
            return {"title": title, "ylabel": ylabel, "data": data,
                    "model": model, "ylim": (0.0, float(max(ylim, 1e-12)))}

        return {
            "Lp / Rp": {
                "top": trace("Primary inductance", r"$L_p$ (pH)",
                             D["Lp"] * 1e12, md("Lp", 1e12), 2.0 * abs(D["Lp"][k0]) * 1e12),
                "bottom": trace("Primary resistance", r"$R_p\ (\Omega)$",
                                D["Rp"], md("Rp"), 3.0 * abs(D["Rp"][k0]) + 1.0),
            },
            "Ls / Rs": {
                "top": trace("Secondary inductance", r"$L_s$ (pH)",
                             D["Ls"] * 1e12, md("Ls", 1e12), 2.0 * abs(D["Ls"][k0]) * 1e12),
                "bottom": trace("Secondary resistance", r"$R_s\ (\Omega)$",
                                D["Rs"], md("Rs"), 3.0 * abs(D["Rs"][k0]) + 1.0),
            },
            "Qp / Qs": {
                "top": trace("Primary quality factor", r"$Q_p$",
                             D["Qp"], md("Qp"), 1.5 * abs(D["Qp"][k0]) + 1.0),
                "bottom": trace("Secondary quality factor", r"$Q_s$",
                                D["Qs"], md("Qs"), 1.5 * abs(D["Qs"][k0]) + 1.0),
            },
            "k / M": {
                "top": trace("Coupling factor", r"$k$", D["k"], md("k"), 1.0),
                "bottom": trace("Mutual inductance", r"$M$ (pH)",
                                D["M"] * 1e12, md("M", 1e12), 1.5 * abs(D["M"][k0]) * 1e12),
            },
        }

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        Lp = v["L5"] + v["L7"]; Ls = v["L8"] + v["L9"]
        Rp = v["Rp1"] + v["Rp2"]; Rs = v["Rs1"] + v["Rs2"]
        d = sd.Drawing(show=False); d.config(unit=1.3, fontsize=11)
        with d:
            T = elm.Transformer(t1=4, t2=4, loop=False).label(comp_label("k"), loc="top")
            # primary leads (left): port1 - R_p - top, bottom - R_p - port2
            elm.Resistor().at(T.p1).left().label(comp_label("R_p", Rp, "Ω", sep="  "))
            elm.Dot(open=True).label(port_label(1), loc="left")
            elm.Resistor().at(T.p2).left().label(comp_label("R_p", Rp, "Ω", sep="  "))
            elm.Dot(open=True).label(port_label(2), loc="left")
            # secondary leads (right): top - R_s - port3, bottom - R_s - port4
            elm.Resistor().at(T.s1).right().label(comp_label("R_s", Rs, "Ω", sep="  "))
            elm.Dot(open=True).label(port_label(3), loc="right")
            elm.Resistor().at(T.s2).right().label(comp_label("R_s", Rs, "Ω", sep="  "))
            elm.Dot(open=True).label(port_label(4), loc="right")
            # winding inductances, at each coil's mid-height, set outward
            pmid = ((T.p1[0] + T.p2[0]) / 2.0, (T.p1[1] + T.p2[1]) / 2.0)
            smid = ((T.s1[0] + T.s2[0]) / 2.0, (T.s1[1] + T.s2[1]) / 2.0)
            elm.Label().at(pmid).label(comp_label("L_p", Lp, "H"), ofst=(-0.55, 0))
            elm.Label().at(smid).label(comp_label("L_s", Ls, "H"), ofst=(0.55, 0))
        return d
