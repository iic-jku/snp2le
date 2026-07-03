"""structures/mim_cap.py - 2-port MIM capacitor model extraction.

Series path: a main capacitor C_s with a small parasitic series L_s and loss R_s.
Shunt path: a plate-to-substrate C at each port.  C_s is taken at low frequency
(where the series L has negligible effect), L_s/R_s at a higher frequency
(standard network-theory extraction, in the spirit of mim_from_s2p).
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label
from .inductor_pi import pi_branches


def _mim_decomp(s, f, z0):
    """MIM-model quantities over frequency from S-parameters: effective series C,
    shunt C (port 1), series R and parasitic series L.  Follows Volker Muehlhaus'
    mim_from_s2p (series C taken at low frequency, L from the residual reactance).
    """
    import skrf
    s = np.asarray(s)
    w = 2 * np.pi * f
    Y = skrf.network.s2y(s, z0=z0)
    y11 = Y[:, 0, 0]; ymn = 0.5 * (Y[:, 0, 1] + Y[:, 1, 0])
    Zser = -1.0 / ymn
    Zsh = 1.0 / (y11 + ymn)                          # port-1 shunt (port 2 ~ equal)
    good = f > 0
    lo = int(np.argmin(np.abs(f - max(f[-1] / 20.0, f[good][0]))))
    with np.errstate(divide="ignore", invalid="ignore"):
        Cseries = 1.0 / (-Zser.imag * w)            # effective series C
        Cser_low = Cseries[lo]                       # series C where L is negligible
        Lseries = (Zser.imag + 1.0 / (w * Cser_low)) / w
        Cshunt = -1.0 / (w * Zsh.imag)
        Rseries = Zser.real
    return {"Cseries": Cseries, "Cshunt": Cshunt, "Rseries": Rseries, "Lseries": Lseries}


class MimCap(Structure):
    key = "mim-cap"
    display_name = "MIM capacitor"
    n_ports = 2

    def extract(self, net, f_extract, n_segments=None, iso_r=True):   # last two: not used
        if net.nports != 2:
            raise ValueError("MIM model needs a 2-port (.s2p)")
        f = net.f
        w = 2 * np.pi * f
        Zs, Zsh1, Zsh2 = pi_branches(net)

        lo = int(np.argmin(np.abs(f - max(f[-1] / 20.0, f[f > 0][0]))))
        # series C read off at low f, L / R / shunt C at the extraction frequency
        hi = self.nearest_index(f, f_extract)

        Cs = float(-1.0 / (w[lo] * Zs.imag[lo]))          # series C at low f
        # series L from the residual reactance at the higher frequency
        Xres = Zs.imag[hi] + 1.0 / (w[hi] * Cs)
        Ls = float(Xres / w[hi])
        Rs = float(Zs.real[hi])
        cp1 = -1.0 / (w[hi] * Zsh1.imag[hi]) if Zsh1.imag[hi] != 0 else 0.0
        cp2 = -1.0 / (w[hi] * Zsh2.imag[hi]) if Zsh2.imag[hi] != 0 else 0.0
        # the two ports can't be separated precisely, so distribute equally
        Csh = max(0.5 * (cp1 + cp2), 0.0)
        Cs = max(Cs, 0.0); Ls = max(Ls, 0.0); Rs = max(Rs, 0.0)

        ir = CircuitIR(name="mim_cap", ports=["p1", "p2"], physical=True)
        ir.comments.append(f"MIM model: C_s at {f[lo]/1e9:.2f} GHz, L_s/R_s at {f[hi]/1e9:.2f} GHz")
        ir.add(Element("C", "Cs", ("p1", "n1"), Cs, label="C_s"))
        ir.add(Element("L", "Ls", ("n1", "n2"), Ls, label="L_s"))
        ir.add(Element("R", "Rs", ("n2", "p2"), Rs, label="R_s"))
        ir.add(Element("C", "C1", ("p1", "0"), Csh, label="C_p1"))
        ir.add(Element("C", "C2", ("p2", "0"), Csh, label="C_p2"))

        metrics = {"Cs": Cs, "f_extract": float(f[hi])}
        rows = [("C_s", Cs, "F"), ("L_s", Ls, "H"), ("R_s", Rs, "\u03a9"),
                ("C_p1", Csh, "F"), ("C_p2", Csh, "F")]
        return ir, metrics, rows

    def default_plots(self):
        return ["Cseries / Cshunt", "Rseries / Lseries", "S11", "S21"]

    def value_drift(self, net, value_rows, f_extract):
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _mim_decomp(net.s, net.f, z0)
        vals = {lab: v for lab, v, _ in value_rows}
        curves = {"C_s": D["Cseries"], "L_s": D["Lseries"], "R_s": D["Rseries"],
                  "C_p1": D["Cshunt"], "C_p2": D["Cshunt"]}
        return {lab: self.fext_tolerance_pct(c, vals[lab], net.f, f_extract)
                for lab, c in curves.items() if lab in vals}

    def freq_traces(self, net, model_s):
        """Frequency-domain trace sets for the Plot view (data vs model):
          * 'Cseries / Cshunt', effective series C and shunt C over frequency
          * 'Rseries / Lseries', series R and parasitic series L over frequency
        """
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _mim_decomp(net.s, f, z0)
        M = _mim_decomp(model_s, f, z0) if model_s is not None else None
        good = f > 0
        lo = int(np.argmin(np.abs(f - max(f[-1] / 20.0, f[good][0]))))
        hi = int(np.argmin(np.abs(f - 0.6 * f[-1])))

        def md(key, scale=1.0):
            return None if M is None else M[key] * scale

        def trace(title, ylabel, data, model, ylim):
            return {"title": title, "ylabel": ylabel, "data": data,
                    "model": model, "ylim": (0.0, float(max(ylim, 1e-12)))}

        return {
            "Cseries / Cshunt": {
                "top": trace("Effective series C", r"$C_\mathrm{series}$ (fF)",
                             D["Cseries"] * 1e15, md("Cseries", 1e15),
                             2.0 * abs(D["Cseries"][lo]) * 1e15),
                "bottom": trace("Shunt capacitance", r"$C_\mathrm{shunt}$ (fF)",
                                D["Cshunt"] * 1e15, md("Cshunt", 1e15),
                                5.0 * abs(D["Cshunt"][hi]) * 1e15),
            },
            "Rseries / Lseries": {
                "top": trace("Series resistance", r"$R_\mathrm{series}\ (\Omega)$",
                             D["Rseries"], md("Rseries"), 2.0 * abs(D["Rseries"][hi])),
                "bottom": trace("Parasitic series L", r"$L_\mathrm{series}$ (pH)",
                                D["Lseries"] * 1e12, md("Lseries", 1e12),
                                2.0 * abs(D["Lseries"][hi]) * 1e12),
            },
        }

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        d = sd.Drawing(show=False); d.config(unit=2.0, fontsize=12)
        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            elm.Line().right().length(1.0)      # P1 lead, same length as the P2 lead
            elm.Dot()
            d.push()
            elm.Capacitor().down().label(comp_label("C_p1", v.get("C1"), "F"))
            elm.Ground()
            d.pop()
            elm.Capacitor().right().label(comp_label("C_s", v.get("Cs"), "F", sep="  "))
            elm.Inductor2().right().label(comp_label("L_s", v.get("Ls"), "H", sep="  "))
            elm.Resistor().right().label(comp_label("R_s", v.get("Rs"), "\u03a9", sep="  "))
            elm.Line().right().length(0.33)     # match node<->R_s gap to the node<->C_s gap
            elm.Dot()
            d.push()
            elm.Capacitor().down().label(comp_label("C_p2", v.get("C2"), "F"))
            elm.Ground()
            d.pop()
            elm.Line().right().length(1.0)
            elm.Dot(open=True).label(port_label(2), loc="right")
        return d
