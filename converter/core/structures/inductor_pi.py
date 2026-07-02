"""structures/inductor_pi.py - 2-port inductor model extraction.

Classic on-chip inductor equivalent: a series R-L branch between the two ports
and, at each port, a shunt branch to ground made of a capacitor in *series* with
a substrate resistor (C_ox in series with R_sub).  Branches are split from the
Y-parameters via the averaged mutual term ymn=(y12+y21)/2.  The shunt C and R come
from the shunt impedance Zshunt = 1/(y+ymn) (series R-C), and values are taken at
the frequency of peak quality factor (below self-resonance).  Topology and
extraction follow Volker Muehlhaus' pi_from_s2p
(https://github.com/VolkerMuehlhaus/lumpedmodel).
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


def _pi_decomp(s, f, z0):
    """Pi-model quantities over frequency from S-parameters.

    Returns a dict with the differential parameters (Ldiff, Q, across the whole
    device, so Ldiff rises toward self-resonance) and the pi-branch values
    (Lseries, Rseries, Cshunt, Rshunt of port 1), matching Volker Muehlhaus'
    pi_from_s2p plots.
    """
    import skrf
    s = np.asarray(s)
    w = 2 * np.pi * f
    Y = skrf.network.s2y(s, z0=z0); Z = skrf.network.s2z(s, z0=z0)
    ymn = 0.5 * (Y[:, 0, 1] + Y[:, 1, 0])
    Zser = -1.0 / ymn
    Zsh = 1.0 / (Y[:, 0, 0] + ymn)                  # port-1 shunt (port 2 ~ equal)
    Zdiff = Z[:, 0, 0] - Z[:, 0, 1] - Z[:, 1, 0] + Z[:, 1, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "Ldiff": Zdiff.imag / w,
            "Q": np.where(Zdiff.real != 0, Zdiff.imag / Zdiff.real, np.nan),
            "Lseries": Zser.imag / w,
            "Rseries": Zser.real,
            "Cshunt": -1.0 / (w * Zsh.imag),
            "Rshunt": Zsh.real,
        }


class InductorPi(Structure):
    key = "inductor-pi"
    display_name = "Inductor"
    n_ports = 2

    def extract(self, net, f_extract, n_segments=None, iso_r=True):   # last two: not used
        if net.nports != 2:
            raise ValueError("inductor model needs a 2-port (.s2p)")
        f = net.f
        w = 2 * np.pi * f
        Zseries, Zshunt1, Zshunt2 = pi_branches(net)

        # read the element values off at the requested extraction frequency
        Zdiff = net.z[:, 0, 0] - net.z[:, 0, 1] - net.z[:, 1, 0] + net.z[:, 1, 1]
        Q = np.where(Zdiff.real != 0, Zdiff.imag / Zdiff.real, 0.0)
        k = self.nearest_index(f, f_extract)

        Rs = max(float(Zseries.real[k]), 0.0)
        Ls = max(float(Zseries.imag[k] / w[k]), 0.0)
        # shunt = capacitor in series with substrate R (read off the impedance).
        # The two ports are nominally equal, so average them for a symmetric model
        # (a noisy port can otherwise extract a negative R and drop the resistor).
        C1 = -1.0 / (w[k] * Zshunt1.imag[k]) if Zshunt1.imag[k] != 0 else 0.0
        C2 = -1.0 / (w[k] * Zshunt2.imag[k]) if Zshunt2.imag[k] != 0 else 0.0
        Csh = max(0.5 * (C1 + C2), 0.0)
        Rsh = max(0.5 * (float(Zshunt1.real[k]) + float(Zshunt2.real[k])), 0.0)

        ir = CircuitIR(name="inductor", ports=["p1", "p2"], physical=True)
        ir.comments.append(f"inductor model, extracted at {f[k]/1e9:.2f} GHz")
        ir.add(Element("L", "Ls", ("p1", "n_s"), Ls, label="L_s"))
        ir.add(Element("R", "Rs", ("n_s", "p2"), Rs, label="R_s"))
        self._add_shunt(ir, "p1", 1, Csh, Rsh)
        self._add_shunt(ir, "p2", 2, Csh, Rsh)

        metrics = {"Q_peak": float(Q[k]), "f_extract": float(f[k]),
                   "Ls": Ls, "Rs": Rs}
        rows = [("Q", float(Q[k]), ""),
                ("L_s", Ls, "H"), ("R_s", Rs, "Ω"),
                ("C_p1", Csh, "F"), ("R_p1", Rsh, "Ω"),
                ("C_p2", Csh, "F"), ("R_p2", Rsh, "Ω")]
        return ir, metrics, rows

    def default_plots(self):
        return ["Ldiff / Q", "Lseries / Cshunt", "Rseries / Rshunt", "S21"]

    def value_drift(self, net, value_rows, f_extract):
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _pi_decomp(net.s, net.f, z0)
        vals = {lab: v for lab, v, _ in value_rows}
        curves = {"Q": D["Q"], "L_s": D["Lseries"], "R_s": D["Rseries"],
                  "C_p1": D["Cshunt"], "R_p1": D["Rshunt"],
                  "C_p2": D["Cshunt"], "R_p2": D["Rshunt"]}
        return {lab: self.fext_tolerance_pct(c, vals[lab], net.f, f_extract)
                for lab, c in curves.items() if lab in vals}

    @staticmethod
    def _add_shunt(ir, port, idx, c, r):
        """Capacitor in series with the substrate R to ground.  R is always
        present (a 0 R simply acts as a wire in the MNA rebuild)."""
        mid = f"n_sh{idx}"
        ir.add(Element("C", f"C{idx}", (port, mid), c, label=f"C_p{idx}"))
        ir.add(Element("R", f"R{idx}", (mid, "0"), r, label=f"R_p{idx}"))

    def freq_traces(self, net, model_s):
        """Frequency-domain trace sets for the Plot view (data vs model).

        Three options:
          * 'Ldiff / Q',        effective inductance + Q across the device
          * 'Lseries / Cshunt', pi-model series L and shunt C over frequency
          * 'Rseries / Rshunt', pi-model series R and shunt R over frequency
        """
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _pi_decomp(net.s, f, z0)
        M = _pi_decomp(model_s, f, z0) if model_s is not None else None

        good = f > 0
        qd = np.nan_to_num(D["Q"], nan=-np.inf)
        k = int(np.argmax(np.where(good, qd, -np.inf)))      # peak-Q (fit point)

        def md(key, scale=1.0):
            return None if M is None else M[key] * scale

        def trace(title, ylabel, data, model, ylim):
            return {"title": title, "ylabel": ylabel, "data": data,
                    "model": model, "ylim": (0.0, float(max(ylim, 1e-12)))}

        # Ldiff: clamp the view to the stable (below-resonance) region
        Ld = D["Ldiff"] * 1e9
        lo = f < 0.5 * f[-1]
        base = np.nanmedian(Ld[lo & np.isfinite(Ld)]) if np.any(lo) else np.nanmedian(Ld)
        if not np.isfinite(base) or base <= 0:
            base = np.nanmax(np.abs(Ld[np.isfinite(Ld)])) or 1.0
        qfin = D["Q"][np.isfinite(D["Q"])]
        qmax = float(np.nanmax(qfin)) if qfin.size else 1.0

        return {
            "Ldiff / Q": {
                "top": trace("Differential inductance", r"$L_\mathrm{diff}$ (nH)",
                             Ld, md("Ldiff", 1e9), 3.0 * abs(base)),
                "bottom": trace("Quality factor", r"$Q$",
                                D["Q"], md("Q"), 1.3 * qmax),
            },
            "Lseries / Cshunt": {
                "top": trace("Series inductance", r"$L_\mathrm{series}$ (nH)",
                             D["Lseries"] * 1e9, md("Lseries", 1e9),
                             2.0 * abs(D["Lseries"][k]) * 1e9),
                "bottom": trace("Shunt capacitance", r"$C_\mathrm{shunt}$ (fF)",
                                D["Cshunt"] * 1e15, md("Cshunt", 1e15),
                                5.0 * abs(D["Cshunt"][k]) * 1e15),
            },
            "Rseries / Rshunt": {
                "top": trace("Series resistance", r"$R_\mathrm{series}\ (\Omega)$",
                             D["Rseries"], md("Rseries"),
                             2.0 * abs(D["Rseries"][k])),
                "bottom": trace("Shunt resistance", r"$R_\mathrm{shunt}\ (\Omega)$",
                                D["Rshunt"], md("Rshunt"),
                                5.0 * abs(D["Rshunt"][k])),
            },
        }

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        v = {e.name: e.value for e in ir.elements}
        d = sd.Drawing(show=False); d.config(unit=2.0, fontsize=13)
        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            elm.Line().right().length(1.0)      # P1 lead, same length as the P2 lead
            elm.Dot()
            d.push()
            elm.Capacitor().down().label(comp_label("C_p1", v.get("C1"), "F"))
            if "R1" in v:                       # substrate R in series with C
                elm.Resistor().down().label(comp_label("R_p1", v.get("R1"), "Ω"))
            elm.Ground()
            d.pop()
            elm.Inductor2().right().label(comp_label("L_s", v.get("Ls"), "H", sep="  "))
            # R_s stays on the L_s rail; nudge only its label up so it lines up with the
            # inductor label, which sits higher because the coil humps up
            elm.Resistor().right().label(comp_label("R_s", v.get("Rs"), "Ω", sep="  "),
                                         ofst=(0, 0.13))
            elm.Dot()
            d.push()
            elm.Capacitor().down().label(comp_label("C_p2", v.get("C2"), "F"))
            if "R2" in v:
                elm.Resistor().down().label(comp_label("R_p2", v.get("R2"), "Ω"))
            elm.Ground()
            d.pop()
            elm.Line().right().length(1.0)
            elm.Dot(open=True).label(port_label(2), loc="right")
        return d
