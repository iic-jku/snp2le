"""structures/tline.py - 2-port transmission-line (RLGC) ladder model.

From the ABCD matrix we recover the electrical length gamma*l and characteristic
impedance Zc, then synthesise N cascaded pi-cells whose cascade exactly matches
the line at the extraction frequency: series Z_cell = Zc*sinh(theta), shunt
Y_cell = (2/Zc)*tanh(theta/2) with theta = gamma*l/N.  Each cell is an R-L series
branch plus a shunt capacitor C' in parallel with a substrate/dielectric
conductance G' (drawn as R_sh = 1/G').  In the spirit of Volker Muehlhaus'
rlgc_from_s2p (https://github.com/VolkerMuehlhaus/lumpedmodel).
"""
from __future__ import annotations
import numpy as np

from .base import Structure
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label

N_SEGMENTS = 4          # number of pi-cells in the ladder


def _rlgc_decomp(s, f, z0):
    """Distributed line parameters over frequency from S-parameters: series R'
    and L', shunt G' and C'.  Because the physical length is not supplied these
    are the whole-line values (R'l, L'l, G'l, C'l); gamma*l is unwrapped so they
    stay continuous past the first electrical half-wave.
    """
    import skrf
    s = np.asarray(s)
    w = 2 * np.pi * f
    Z = skrf.network.s2z(s, z0=z0); Y = skrf.network.s2y(s, z0=z0)
    z11 = Z[:, 0, 0]; y11 = Y[:, 0, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        Zc = np.sqrt(z11 / y11)
        glw = np.arctanh(1.0 / (Zc * y11))               # gamma*l, wrapped mod j*pi
        gl = glw.real + 1j * np.unwrap(glw.imag, period=np.pi)
        Zser = gl * Zc                                   # R'l + j w L'l
        Ysh = gl / Zc                                    # G'l + j w C'l
    return {"Rp": Zser.real, "Lp": Zser.imag / w,
            "Gp": Ysh.real, "Cp": Ysh.imag / w}


class TransmissionLine(Structure):
    key = "tline-rlgc"
    display_name = "Tline (RLGC)"
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
                ("Z_c", float(abs(Zc)), "Ω"),
                ("R_s", R_seg, "Ω"), ("L_s", L_seg, "H"),
                ("C_sh", C_seg, "F"), ("R_sh", Rsh, "Ω")]
        return ir, metrics, rows

    def default_plots(self):
        return ["R' / L'", "G' / C'", "S11", "S21"]

    def freq_traces(self, net, model_s):
        """Frequency-domain trace sets for the Plot view (data vs model):
          * "R' / L'" - series resistance and inductance of the line
          * "G' / C'" - shunt conductance and capacitance of the line
        """
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _rlgc_decomp(net.s, f, z0)
        M = _rlgc_decomp(model_s, f, z0) if model_s is not None else None
        k = int(np.argmin(np.abs(f - 0.5 * f[-1])))

        def md(key, scale=1.0):
            return None if M is None else M[key] * scale

        def trace(title, ylabel, data, model, ylim):
            return {"title": title, "ylabel": ylabel, "data": data,
                    "model": model, "ylim": (0.0, float(max(ylim, 1e-12)))}

        return {
            "R' / L'": {
                "top": trace("Series resistance", r"$R'\ (\Omega)$",
                             D["Rp"], md("Rp"), 3.0 * abs(D["Rp"][k])),
                "bottom": trace("Series inductance", r"$L'\ (\mathrm{pH})$",
                                D["Lp"] * 1e12, md("Lp", 1e12), 2.0 * abs(D["Lp"][k]) * 1e12),
            },
            "G' / C'": {
                "top": trace("Shunt conductance", r"$G'\ (\mu\mathrm{S})$",
                             D["Gp"] * 1e6, md("Gp", 1e6), 3.0 * abs(D["Gp"][k]) * 1e6),
                "bottom": trace("Shunt capacitance", r"$C'\ (\mathrm{fF})$",
                                D["Cp"] * 1e15, md("Cp", 1e15), 2.0 * abs(D["Cp"][k]) * 1e15),
            },
        }

    def schematic_drawing(self, ir):
        import schemdraw as sd
        import schemdraw.elements as elm
        sd.use("matplotlib")
        segs = sorted({int(e.name[2:]) for e in ir.elements if e.name.startswith("Ls")})
        show = min(len(segs), 2)
        d = sd.Drawing(show=False); d.config(unit=1.5, fontsize=11)
        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            for i in range(show):
                elm.Inductor2().right().label(comp_label("L_s"))
                elm.Resistor().right().label(comp_label("R_s"))
                elm.Dot()
                # shunt cell: G' (R_sh) in parallel with C' (C_sh) to ground,
                # drawn below the rail so it clears the series line
                d.push()
                elm.Line().down().length(0.4)
                d.push()
                elm.Resistor().down().label(comp_label("R_sh"))
                elm.Ground()
                d.pop()
                elm.Line().right().length(0.8)
                elm.Capacitor().down().label(comp_label("C_sh"))
                elm.Ground()
                d.pop()
            elm.Inductor2().right().label(comp_label("L_s"))
            elm.Resistor().right().label(comp_label("R_s"))
            elm.Dot()
            elm.Line().right().length(0.5).label(r"$\cdots$")
            elm.Dot(open=True).label(port_label(2), loc="right")
        return d
