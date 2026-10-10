# SPDX-FileCopyrightText: 2026 Volker Muehlhaus
# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""structures/inductor_wideband.py - inductor models fitted over the whole band.

`inductor-wideband` (2-port) and `inductor-ct` (center-tapped 3-port) run the global fit in
inductor_fit.py and turn its result into a CircuitIR.  Unlike the other structures they
have no extraction frequency: the values hold from DC to past the self-resonance, so
`wideband = True` tells the engine, the GUI and the CLI that f_ext does not apply.

Each coil segment gets its own elements, with values equal to the totals divided by the
segment count.  The substrate network sits on every coil node, and the half coils of the
center-tapped model are coupled cell by cell with k/segments, which is the same mutual
inductance M/segments^2 per cell pair as in the fit.  Topology and netlist layout follow
Volker Muehlhaus' inductor_fit (https://github.com/VolkerMuehlhaus/lumpedmodel).
"""
from __future__ import annotations
import re

import numpy as np

from .base import Structure
from . import inductor_fit as _fit
from .inductor_pi import InductorPi
from ..ir import CircuitIR, Element
from ..units import comp_label, port_label


def _seg_text(n, per_half=False):
    return f"{n} coil segment{'' if n == 1 else 's'}" + (" per half" if per_half else "")


def _header(ir, kind, fit, per_half=False):
    lo, hi = fit.f_fit
    ir.comments.append(f"{kind}, fitted {lo / 1e9:.4g} to {hi / 1e9:.4g} GHz, "
                       f"{_seg_text(fit.segments, per_half)}"
                       + (", basic model" if fit.basic else ""))
    if fit.segments > 1:
        ir.comments.append("element values per segment are the totals divided by "
                           f"{fit.segments}")
    ir.comments.append("after Volker Muehlhaus' inductor_fit")


def _add_coil_cell(ir, sfx, n_in, n_out, v, num_skin, n, half=""):
    """Rs, Ls and the skin sections of one coil cell from n_in to n_out (totals / n)."""
    ir.add(Element("R", f"Rs{sfx}", (n_in, f"a{sfx}"), v["Rs" + half] / n))
    ir.add(Element("L", f"Ls{sfx}", (f"a{sfx}", f"b{sfx}"), v["Ls" + half] / n))
    n_skin1 = f"d{sfx}" if num_skin == 2 else n_out
    ir.add(Element("R", f"Rskin1{sfx}", (f"b{sfx}", n_skin1), v["Rskin1" + half] / n))
    ir.add(Element("L", f"Lskin1{sfx}", (f"b{sfx}", n_skin1), v["Lskin1" + half] / n))
    if num_skin == 2:
        ir.add(Element("R", f"Rskin2{sfx}", (f"d{sfx}", n_out), v["Rskin2" + half] / n))
        ir.add(Element("L", f"Lskin2{sfx}", (f"d{sfx}", n_out), v["Lskin2" + half] / n))


def _add_substrate(ir, sfx, node, k, cox, rsi, csi):
    ir.add(Element("C", f"Cox{sfx}", (node, f"s{k}"), float(cox)))
    ir.add(Element("R", f"Rsi{sfx}", (f"s{k}", "0"), float(rsi)))
    ir.add(Element("C", f"Csi{sfx}", (f"s{k}", "0"), float(csi)))


def coil_segments(ir):
    """Coil segments of a wideband inductor IR, per half coil for the center-tapped one."""
    return sum(1 for e in ir.elements if re.fullmatch(r"Ls(_h1)?(_[0-9]+)?", e.name))


def _row(name, value):
    """(label, value, unit) for an element of the fit, 'Cox1' -> 'C_ox1', 'Rs_h1' -> 'R_s,h1'."""
    base, _, half = name.partition("_")
    if len(base) == 1:                            # the coupling factor k
        return base, float(value), ""
    sub = base[1:].replace("ct", ",ct") if base[1:] != "ct" else "ct"
    label = f"{base[0]}_{sub}" + (f",{half}" if half else "")
    unit = {"R": "Ω", "L": "H", "C": "F"}.get(name[0], "")
    return label, float(value), unit


class _WidebandInductor(Structure):
    wideband = True

    def extract(self, net, f_extract=None, n_segments=None, iso_r=True,
                basic=False, progress=None):              # f_extract .. iso_r: unused
        if net.nports != self.n_ports:
            raise ValueError(f"{self.display_name} needs a {self.n_ports}-port "
                             f"(.s{self.n_ports}p)")
        fit = self._fit(net, basic=basic, progress=progress)
        ir = self._build_ir(fit)
        rows = [_row(name, fit.values[name]) for name in self._row_names(fit)]
        metrics = dict(fit.metrics, messages=list(fit.messages))
        return ir, metrics, rows


class InductorWideband(_WidebandInductor):
    key = "inductor-wideband"
    display_name = "Inductor (wideband)"
    n_ports = 2

    @staticmethod
    def _fit(net, basic=False, progress=None):
        return _fit.fit_two_port(net, basic=basic, progress=progress)

    @staticmethod
    def _row_names(fit):
        return [n for n in fit.active if fit.coupling or n not in ("Rsub12", "Csub12")]

    @staticmethod
    def _build_ir(fit):
        v, n = fit.values, fit.segments
        ir = CircuitIR(name="inductor", ports=["p1", "p2"], physical=True)
        _header(ir, "wideband inductor model", fit)

        def coil_node(k):
            return "p1" if k == 0 else "p2" if k == n else f"c{k}"

        for k in range(n):
            _add_coil_cell(ir, f"_{k + 1}" if n > 1 else "", coil_node(k), coil_node(k + 1),
                           v, fit.num_skin, n)
        ir.add(Element("C", "Cs", ("p1", "p2"), v["Cs"]))
        p = np.array([v[name] for name in _fit.PARAM_NAMES])
        for k, (cox, rsi, csi) in enumerate(zip(*_fit.segment_shunt_values(p, n))):
            _add_substrate(ir, str(k + 1) if n == 1 else f"_n{k}", coil_node(k), k,
                           cox, rsi, csi)
        if fit.coupling:
            ir.add(Element("R", "Rsub12", ("s0", f"s{n}"), v["Rsub12"]))
            ir.add(Element("C", "Csub12", ("s0", f"s{n}"), v["Csub12"]))
        return ir

    def default_plots(self):
        return ["Ldiff / Q", "L11 / Q11", "Lseries / Cshunt", "S21"]

    def freq_traces(self, net, model_s):
        """The inductor-pi views (Ldiff / Q, Lseries / Cshunt, Rseries / Rshunt), plus the
        single-ended L and Q at port 1 with port 2 grounded, which the fit also targets."""
        traces = InductorPi().freq_traces(net, model_s)
        f = net.f
        z0 = float(np.real(net.z0.flatten()[0]))
        L, Q = _l_q(net.s, f, z0, 0)
        ML, MQ = _l_q(model_s, f, z0, 0) if model_s is not None else (None, None)
        traces["L11 / Q11"] = _lq_pair("Inductance, port 1, port 2 grounded",
                                       "Quality factor, port 1, port 2 grounded",
                                       "L_{11}", "Q_{11}", f, L, Q, ML, MQ)
        return traces

    def schematic_drawing(self, ir):
        names = {e.name for e in ir.elements}
        segments = coil_segments(ir)
        two_skin = any(nm.startswith("Rskin2") for nm in names)
        return _draw_two_port(two_skin, "Rsub12" in names, segments)


class InductorCenterTap(_WidebandInductor):
    key = "inductor-ct"
    display_name = "Inductor (center tap)"
    n_ports = 3

    @staticmethod
    def _fit(net, basic=False, progress=None):
        return _fit.fit_center_tap(net, basic=basic, progress=progress)

    @staticmethod
    def _row_names(fit):
        return list(fit.active)

    @staticmethod
    def _build_ir(fit):
        v, n = fit.values, fit.segments
        # the EM port order is the pin order: coil ends on p1, p2, the center tap on p3
        ir = CircuitIR(name="inductor_ct", ports=["p1", "p2", "p3"], physical=True)
        _header(ir, "wideband center-tapped inductor model (center tap p3)", fit,
                per_half=True)

        def coil_node(k):
            return "p1" if k == 0 else "p2" if k == 2 * n else "m" if k == n else f"c{k}"

        def cell(h, i):
            return f"_h{h}" + (f"_{i + 1}" if n > 1 else "")

        for h in (1, 2):
            for i in range(n):
                b = (h - 1) * n + i
                _add_coil_cell(ir, cell(h, i), coil_node(b), coil_node(b + 1), v,
                               fit.num_skin, n, half=f"_h{h}")
        # every cell of half 1 couples to every cell of half 2 (dot at the first node,
        # aiding for differential current p1 -> m -> p2)
        for i in range(n):
            for j in range(n):
                ir.add_coupling(f"Ls{cell(1, i)}", f"Ls{cell(2, j)}", v["k"] / n)
        ir.add(Element("C", "Cs", ("p1", "p2"), v["Cs"]))
        ir.add(Element("R", "Rct", ("m", "p3"), v["Rct"]))
        p = np.array([v[name] for name in _fit.CT_PARAM_NAMES])
        for k, (cox, rsi, csi) in enumerate(zip(*_fit.ct_node_shunt_values(p, n))):
            sfx = {0: "1", n: "ct", 2 * n: "2"}[k] if n == 1 else f"_n{k}"
            _add_substrate(ir, sfx, coil_node(k), k, cox, rsi, csi)
        return ir

    def default_plots(self):
        return ["Ldiff / Qdiff", "Lcm / Qcm", "L11 / Q11", "S21"]

    def freq_traces(self, net, model_s):
        """Differential L and Q with the center tap AC grounded and open, common mode at the
        center tap (p1, p2 grounded), and single-ended at port 1 (p2, ct grounded)."""
        f = net.f
        w = 2 * np.pi * f
        z0 = float(np.real(net.z0.flatten()[0]))
        D = _ct_responses(net.s, w, z0)
        M = _ct_responses(model_s, w, z0) if model_s is not None else None

        def pair(key, where, sym):
            return _lq_pair(f"Inductance, {where}", f"Quality factor, {where}",
                            f"L_{{{sym}}}", f"Q_{{{sym}}}", f, D["L" + key], D["Q" + key],
                            None if M is None else M["L" + key],
                            None if M is None else M["Q" + key])

        return {"Ldiff / Qdiff": pair("dd_gnd", "differential, center tap grounded", "diff"),
                "Ldiff / Qdiff (ct open)": pair("dd_open", "differential, center tap open",
                                                "diff"),
                "Lcm / Qcm": pair("cm", "common mode at the center tap", "cm"),
                "L11 / Q11": pair("11", "port 1, ports 2 and 3 grounded", "11")}

    def schematic_drawing(self, ir):
        names = {e.name for e in ir.elements}
        segments = coil_segments(ir)
        two_skin = any(nm.startswith("Rskin2") for nm in names)
        return _draw_center_tap(two_skin, segments)


# ---------------- plot traces ----------------

def _l_q(s, f, z0, port):
    """L and Q at `port` with every other port grounded, over frequency."""
    import skrf
    Y = skrf.network.s2y(np.asarray(s), z0=z0)
    with np.errstate(divide="ignore", invalid="ignore"):
        L, Q = _fit.l_and_q(Y[:, port, port], 2 * np.pi * f)
    return L, Q


def _ct_responses(s, w, z0):
    import skrf
    Y = skrf.network.s2y(np.asarray(s), z0=z0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return _fit.ct_quantities(Y, w)


def _lq_pair(l_title, q_title, l_sym, q_sym, f, L, Q, ML, MQ):
    """A Plot view trace set: L (nH) on top, Q below, y-limits from the low-frequency L and
    the peak Q, which the view uses when the model curve gives none."""
    Ln = L * 1e9
    lo = f < 0.5 * f[-1]
    base = np.nanmedian(np.abs(Ln[lo & np.isfinite(Ln)])) if np.any(lo) else 1.0
    qfin = Q[np.isfinite(Q)]
    qmax = float(np.nanmax(qfin)) if qfin.size else 1.0
    return {"top": {"title": l_title, "ylabel": rf"${l_sym}$ (nH)", "data": Ln,
                    "model": None if ML is None else ML * 1e9,
                    "ylim": (0.0, float(max(3.0 * base, 1e-12)))},
            "bottom": {"title": q_title, "ylabel": rf"${q_sym}$", "data": Q, "model": MQ,
                       "ylim": (0.0, float(max(1.3 * qmax, 1e-12)))}}


# ---------------- schematics ----------------

_U = 2.0          # element length


def _drawing():
    import schemdraw as sd
    sd.use("matplotlib")
    d = sd.Drawing(show=False)
    d.config(unit=_U, fontsize=12)
    return d


def _line(d, a, b, **kw):
    import schemdraw.elements as elm
    d.add(elm.Line(**kw).endpoints(a, b))


def _parallel(d, a, top, bottom, gap=1.0):
    """`top` and `bottom` in parallel from point a to the right, returns the right node."""
    from schemdraw.util import Point
    a = Point(a)
    b = a + Point((_U + 1.0, 0))
    _line(d, a, a + Point((0.5, 0)))
    _line(d, b - Point((0.5, 0)), b)
    for el, dy in ((top, gap / 2), (bottom, -gap / 2)):
        p, q = a + Point((0.5, dy)), b + Point((-0.5, dy))
        _line(d, a + Point((0.5, 0)), p)
        d.add(el.endpoints(p, q))
        _line(d, q, b + Point((-0.5, 0)))
    return b


def _series_coil(d, start, two_skin, half=""):
    """Rs, Ls and the skin sections to the right of `start`.  Returns the end point and the
    centre of Ls (where the coupling bracket attaches)."""
    import schemdraw.elements as elm
    from schemdraw.util import Point
    h = f",{half}" if half else ""
    a = start + Point((_U, 0))
    d.add(elm.Resistor().endpoints(start, a).label(comp_label(f"R_s{h}")))
    b = a + Point((_U, 0))
    d.add(elm.Inductor2(loops=3).endpoints(a, b).label(comp_label(f"L_s{h}")))
    e = _parallel(d, b, elm.Inductor2(loops=2).label(comp_label(f"L_skin1{h}")),
                  elm.Resistor().label(comp_label(f"R_skin1{h}"), "bottom"))
    if two_skin:
        e = _parallel(d, e, elm.Inductor2(loops=2).label(comp_label(f"L_skin2{h}")),
                      elm.Resistor().label(comp_label(f"R_skin2{h}"), "bottom"))
    return e, Point(((a.x + b.x) / 2, a.y))


def _cs_across(d, n1, n2, h):
    import schemdraw.elements as elm
    from schemdraw.util import Point
    _line(d, n1, n1 + Point((0, h)))
    _line(d, n2, n2 + Point((0, h)))
    mid = (n1.x + n2.x) / 2
    left, right = Point((mid - _U / 2, n1.y + h)), Point((mid + _U / 2, n1.y + h))
    _line(d, n1 + Point((0, h)), left)
    d.add(elm.Capacitor().endpoints(left, right).label(comp_label("C_s")))
    _line(d, right, n2 + Point((0, h)))
    return mid


def _shunt(d, top, loc, side):
    """Cox down from `top` to the substrate node, then Rsi || Csi to ground.  Returns the
    substrate node."""
    import schemdraw.elements as elm
    from schemdraw.util import Point
    s = Point(top) - Point((0, _U + 0.6))

    def where(sd):
        return "top" if sd == "left" else "bottom"   # label sides of downward elements

    d.add(elm.Capacitor().endpoints(top, s).label(comp_label(f"C_ox{loc}"), where(side)))
    d.add(elm.Dot().at(s))
    w = 0.8
    for el, dx, sym, sd in ((elm.Resistor(), -w, f"R_si{loc}", "left"),
                            (elm.Capacitor(), w, f"C_si{loc}", "right")):
        p = s + Point((dx, -0.5))
        q = p - Point((0, _U))
        _line(d, s, s + Point((dx, 0)))
        _line(d, s + Point((dx, 0)), p)
        d.add(el.endpoints(p, q).label(comp_label(sym), where(sd)))
        _line(d, q, q - Point((0, 0.3)))
        _line(d, q - Point((0, 0.3)), s + Point((0, -_U - 0.8)))
    d.add(elm.Ground().at(s + Point((0, -_U - 0.8))))
    return s


def _segment_note(d, at, segments, per_half=False):
    import schemdraw.elements as elm
    if segments > 1:
        d.add(elm.Label().at(at).label(
            f"{_seg_text(segments, per_half)}, values are totals", fontsize=11))


def _draw_two_port(two_skin, coupling, segments):
    import schemdraw.elements as elm
    from schemdraw.util import Point
    d = _drawing()
    p1 = Point((0, 0))
    d.add(elm.Dot(open=True).at(p1).label(port_label(1), "left"))
    n1 = p1 + Point((1.2, 0))
    _line(d, p1, n1)
    d.add(elm.Dot().at(n1))
    e, _ = _series_coil(d, n1, two_skin)
    n2 = e + Point((0.5, 0))
    _line(d, e, n2)
    d.add(elm.Dot().at(n2))
    p2 = n2 + Point((1.2, 0))
    _line(d, n2, p2)
    d.add(elm.Dot(open=True).at(p2).label(port_label(2), "right"))
    mid = _cs_across(d, n1, n2, 1.8)
    s1 = _shunt(d, n1, "1", "left")
    s2 = _shunt(d, n2, "2", "right")
    if coupling:
        left = Point((mid - (_U + 1.0) / 2, s1.y))
        _line(d, s1, left)
        right = _parallel(d, left, elm.Resistor().label(comp_label("R_sub12")),
                          elm.Capacitor().label(comp_label("C_sub12"), "bottom"), gap=1.4)
        _line(d, right, s2)
    _segment_note(d, Point((mid, 3.0)), segments)
    return d


def _draw_center_tap(two_skin, segments):
    import schemdraw.elements as elm
    from schemdraw.util import Point
    d = _drawing()
    p1 = Point((0, 0))
    d.add(elm.Dot(open=True).at(p1).label(port_label(1), "left"))
    n1 = p1 + Point((1.2, 0))
    _line(d, p1, n1)
    d.add(elm.Dot().at(n1))
    e1, ls1 = _series_coil(d, n1, two_skin, "h1")
    m = e1 + Point((0.5, 0))
    _line(d, e1, m)
    d.add(elm.Dot().at(m))
    m2 = m + Point((2.0, 0))
    _line(d, m, m2)
    d.add(elm.Dot().at(m2))
    e2, ls2 = _series_coil(d, m2 + Point((0.5, 0)), two_skin, "h2")
    _line(d, m2, m2 + Point((0.5, 0)))
    n2 = e2 + Point((0.5, 0))
    _line(d, e2, n2)
    d.add(elm.Dot().at(n2))
    p2 = n2 + Point((1.2, 0))
    _line(d, n2, p2)
    d.add(elm.Dot(open=True).at(p2).label(port_label(2), "right"))
    # magnetic coupling of the two Ls
    hk = 1.4
    for ls in (ls1, ls2):
        _line(d, ls + Point((0, 0.8)), ls + Point((0, hk)), ls="--")
    _line(d, ls1 + Point((0, hk)), ls2 + Point((0, hk)), ls="--")
    d.add(elm.Label().at(Point(((ls1.x + ls2.x) / 2, hk + 0.3))).label(comp_label("k")))
    _cs_across(d, n1, n2, 2.4)
    # center tap lead, down from the coil midpoint
    ct = Point((m.x, -_U - 0.6))
    d.add(elm.Resistor().endpoints(m, ct).label(comp_label("R_ct"), "top"))
    d.add(elm.Dot(open=True).at(ct).label(port_label(3), "bottom"))
    _shunt(d, n1, "1", "left")
    _shunt(d, m2, "ct", "right")
    _shunt(d, n2, "2", "right")
    _segment_note(d, Point(((n1.x + n2.x) / 2, 3.6)), segments, per_half=True)
    return d
