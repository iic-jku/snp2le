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

N_SEGMENTS = 2          # default number of L-cells in the ladder


def _rlgc_decomp(s, f, z0):
    """Distributed line parameters over frequency from S-parameters: series R'
    and L', shunt G' and C'.  Because the physical length is not supplied these
    are the whole-line values (R'l, L'l, G'l, C'l).  gamma*l is unwrapped so they
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

    def extract(self, net, f_extract, n_segments=N_SEGMENTS, iso_r=True):   # iso_r: not used
        if net.nports != 2:
            raise ValueError("transmission-line model needs a 2-port (.s2p)")
        f = net.f
        w = 2 * np.pi * f
        A = net.a[:, 0, 0]; B = net.a[:, 0, 1]; C = net.a[:, 1, 0]
        k = self.nearest_index(f, f_extract)               # extraction frequency
        wk = w[k]
        gl = np.arccosh(A[k])                               # electrical length gamma*l
        Zc = np.sqrt(B[k] / C[k]) if C[k] != 0 else np.sqrt(B[k])
        # whole-line series Z and shunt Y (the physical length cancels), shared
        # equally over N L-cells: each cell is series R+L then shunt C||G
        Ztot = gl * Zc                                      # R_tot + j w L_tot
        Ytot = gl / Zc                                      # G_tot + j w C_tot
        n = max(1, min(10, int(n_segments)))               # ladder stages are capped at 1..10
        R_seg = float(abs(Ztot.real)) / n
        L_seg = float(abs(Ztot.imag / wk)) / n
        G_seg = float(abs(Ytot.real)) / n
        C_seg = float(abs(Ytot.imag / wk)) / n
        Rsh = 1.0 / G_seg if G_seg > 1e-15 else 1e12

        ir = CircuitIR(name="tline_rlgc", ports=["p1", "p2"], physical=True)
        ir.comments.append(f"RLGC line, {n} L-cells, extracted at {f[k]/1e9:.2f} GHz")
        # N L-cells: series L+R, then a shunt C||G to ground after each cell.  The
        # output port (p2) keeps its shunt. The input port has none (rlgc_from_s2p).
        prev = "p1"
        for i in range(n):
            out = "p2" if i == n - 1 else f"n{i+1}"
            mid = f"s{i+1}"
            ir.add(Element("L", f"Ls{i+1}", (prev, mid), L_seg, label="L_s"))
            ir.add(Element("R", f"Rs{i+1}", (mid, out), R_seg, label="R_s"))
            ir.add(Element("C", f"Csh{i+1}", (out, "0"), C_seg, label="C_sh"))
            ir.add(Element("R", f"Rsh{i+1}", (out, "0"), Rsh, label="R_sh"))
            prev = out

        metrics = {"segments": n, "f_extract": float(f[k]),
                   "Zc": float(abs(Zc))}
        rows = [("N_seg", float(n), ""),
                ("Z_c", float(abs(Zc)), "Ω"),
                ("R_s", R_seg, "Ω"), ("L_s", L_seg, "H"),
                ("C_sh", C_seg, "F"), ("R_sh", Rsh, "Ω")]
        return ir, metrics, rows

    def default_plots(self):
        return ["R' / L'", "G' / C'", "S11", "S21"]

    def value_drift(self, net, value_rows, f_extract):
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _rlgc_decomp(net.s, net.f, z0)
        vals = {lab: v for lab, v, _ in value_rows}
        n = max(1, int(round(vals.get("N_seg", 1))))     # per-cell = whole-line / N
        with np.errstate(divide="ignore", invalid="ignore"):
            Rsh = 1.0 / np.maximum(D["Gp"] / n, 1e-30)
            Zc = np.sqrt(D["Lp"] / D["Cp"])
        curves = {"Z_c": Zc, "R_s": D["Rp"] / n, "L_s": D["Lp"] / n,
                  "C_sh": D["Cp"] / n, "R_sh": Rsh}
        return {lab: self.fext_tolerance_pct(c, vals[lab], net.f, f_extract)
                for lab, c in curves.items() if lab in vals}

    def freq_traces(self, net, model_s):
        """Frequency-domain trace sets for the Plot view (data vs model):
          * "R' / L'", series resistance and inductance of the line
          * "G' / C'", shunt conductance and capacitance of the line
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
        n = len([e for e in ir.elements if e.name.startswith("Ls")])     # L-cells
        d = sd.Drawing(show=False); d.config(unit=1.5, fontsize=11)
        def cell():
            """One L-cell: series L+R, then a shunt R_sh || C_sh to ground.  R_s stays on the
            L_s rail.  Only its label is nudged up to line up with the higher inductor label."""
            elm.Inductor2().right().label(comp_label("L_s"))
            elm.Resistor().right().label(comp_label("R_s"), ofst=(0, 0.10))
            elm.Dot()
            d.push()                              # shunt below the rail: R_sh || C_sh,
            elm.Line().down().length(0.4)         # spread symmetrically so they do not overlap
            d.push()
            elm.Line().left().length(0.5)
            elm.Resistor().down().label(comp_label("R_sh"))
            elm.Ground()
            d.pop()
            elm.Line().right().length(0.65)       # C_sh sits a little further right of the node
            cap = elm.Capacitor().down()
            elm.Ground()
            # +0.1 in y cancels elm.Label's built-in downward offset, so the C_sh label lines
            # up with R_sh's centred label rather than sitting slightly below it
            elm.Label().at((cap.center[0] + 0.55, cap.center[1] + 0.1)).label(comp_label("C_sh"))
            d.pop()

        with d:
            elm.Dot(open=True).label(port_label(1), loc="left")
            elm.Line().right().length(0.6)        # P1 input lead
            if n <= 4:                            # small ladder: draw every stage
                for _ in range(n):
                    cell()
            else:                                 # large ladder: abbreviate the middle
                cell(); cell()
                elm.Line().right().length(0.6).label(r"$\cdots$")
                cell()                            # last cell keeps the output shunt
            elm.Line().right().length(1.2)        # output trace to P2 (twice the P1 input lead)
            elm.Dot(open=True).label(port_label(2), loc="right")
        return d
