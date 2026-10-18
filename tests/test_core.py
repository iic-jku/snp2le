# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_core.py - core tests (no Qt). Run with:  pytest -q

Covers the unit helpers, both conversion modes, all structures, netlist rendering
and the awkward edge cases (DC sample, wrong port count).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import skrf

from snp2le.core import io, engine
from snp2le.core.state import ConverterState
from snp2le.core.units import parse_eng, format_eng
from snp2le.core.structures import structure_items, get_structure


# ---------------------------------------------------------------- fixtures
def inductor_2port(with_dc=False):
    """Synthetic series-RL + shunt-C 2-port (a clean pi-network)."""
    start = 0 if with_dc else 0.1
    f = skrf.Frequency(start, 20, 101, "ghz")
    w = 2 * np.pi * f.f
    with np.errstate(divide="ignore", invalid="ignore"):
        ys = np.where(w > 0, 1.0 / (1.4 + 1j * w * 0.82e-9), 0)
    yp = 1j * w * 40e-15
    Y = np.zeros((len(w), 2, 2), complex)
    Y[:, 0, 0] = ys + yp; Y[:, 0, 1] = -ys
    Y[:, 1, 0] = -ys;     Y[:, 1, 1] = ys + yp
    return skrf.Network(frequency=f, y=Y, z0=50, name="ind2")


# ---------------------------------------------------------------- units
def test_units_roundtrip():
    assert abs(parse_eng("0.82n") - 0.82e-9) < 1e-21
    assert abs(parse_eng("50") - 50) < 1e-9
    assert abs(parse_eng("100 k") - 1e5) < 1
    assert format_eng(40e-15, "F").startswith("40")
    assert format_eng(float("nan")) == "\u2014"


def test_format_eng_rounds_before_it_picks_the_prefix():
    """0.9996 used to print as "1e+03 m", the CLI's --values showed state resistors so."""
    assert format_eng(0.9996, "H") == "1 H"
    assert format_eng(999.6, "H") == "1 kH"
    assert format_eng(-0.0009996, "F") == "-1 mF"
    assert format_eng(0.9994, "H") == "999 mH"


# ---------------------------------------------------------------- universal
def test_universal_fits_and_renders():
    net = inductor_2port()
    res = engine.convert(ConverterState(mode="universal", max_order=10), net)
    assert res.ok and res.error == ""
    assert res.n_poles > 0
    assert res.rms_error < 1e-2                       # good fit on a clean network
    assert ".SUBCKT" in res.ngspice and "subckt" in res.vacask
    assert res.model_s.shape == (len(net.f), 2, 2)


def test_netlist_values_read_back_as_the_same_doubles():
    """A universal realisation relies on cancellation between its controlled-source gains,
    so every value is written as the shortest text that reads back as the same double.  With
    10 significant digits a synthetic 2-port fitted at order 24 missed its own model by 1.0
    in S, while the text written now reproduces the circuit exactly."""
    import re
    from snp2le.core import netlist
    res = engine.convert(ConverterState(mode="universal", max_order=13, thermal_noise=True),
                         _example("bpf_ihp-sg13g2.s2p"))
    assert res.ok and res.noise.ok
    back = netlist.parse_spice_subckt(res.ngspice)
    assert [(e.name, e.value) for e in back.elements] == \
        [(e.name, e.value) for e in res.ir.elements]
    written = {float(v) for v in re.findall(r"\b(?:r|c|l|gain|dc|k)=(\S+)", res.vacask)}
    assert {float(e.value) for e in res.ir.elements} <= written


def test_universal_high_order_resistors_above_ngspice_floor():
    """Regression: scikit-rf's fast-pole state resistors can fall below ngspice's
    1e-12 floor at higher orders. Rounding them up corrupts S11/S22.  They must be
    rescaled (not clamped) so the exported netlist has no near-floor resistors."""
    bpf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "snp2le", "examples", "bpf_ihp-sg13g2.s2p")
    net = io.load_touchstone(bpf)
    res = engine.convert(ConverterState(mode="universal", max_order=14), net)
    assert res.ok
    rvals = [e.value for e in res.ir.elements if e.kind == "R"]
    assert rvals and min(rvals) >= 1e-10        # clamp would leave one at 1e-12


def test_dc_operating_point_check():
    """A well-posed universal macromodel passes the DC operating-point check. A network
    with a floating internal node (no DC path to ground) is flagged singular."""
    from snp2le.core import dc, universal
    net = inductor_2port()
    res = engine.convert(ConverterState(mode="universal", max_order=10), net)
    assert res.dc is not None and res.dc.ok            # healthy fit -> well-posed
    assert res.dc.margin > 1e-9

    fit = universal.fit_universal(net, max_order=10, enforce_passivity=False)
    cap_nodes = {e.nodes[0] if e.nodes[1] == "0" else e.nodes[1]
                 for e in fit.ir.elements if e.kind == "C" and "0" in e.nodes}
    fit.ir.elements = [e for e in fit.ir.elements       # strip self-resistors -> nodes float
                       if not (e.kind == "R" and "0" in e.nodes
                               and (e.nodes[0] in cap_nodes or e.nodes[1] in cap_nodes))]
    health = dc.dc_check(fit.ir)
    assert not health.ok and health.margin < 1e-12


# ---------------------------------------------------------------- structures
def _example(name):
    return io.load_touchstone(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snp2le", "examples", name))


def test_all_structures_extract():
    example = {2: lambda: inductor_2port(),
               3: lambda: _example("wpd_ihp-sg13g2.s3p"),
               4: lambda: _example("balun_ihp-sg13cmos5l.s4p")}
    own = {"inductor-ct": lambda: _example("ind_ct_n2_d82_w4_s4_ihp-sg13g2.s3p")}
    for key, _name, nports in structure_items():
        net = own.get(key, example[nports])()
        res = engine.convert(ConverterState(mode="structure", structure_key=key), net)
        assert res.ok, (key, res.error)
        assert res.value_rows                         # has labelled values
        assert res.model_s is not None
        assert res.model_s.shape == (len(net.f), nports, nports)


def test_wilkinson_synthesises_quadrature_divider():
    """The Wilkinson model is the full quadrature divider of the paper: all eight
    elements present, matched input, -3 dB equal split, isolation, and 90 deg between
    the two outputs at the detected centre frequency."""
    net = _example("wpd_ihp-sg13g2.s3p")
    res = engine.convert(ConverterState(mode="structure", structure_key="wilkinson"), net)
    vals = {lab: v for lab, v, _ in res.value_rows}
    assert set(vals) >= {"L_1", "C_1", "L_2", "C_2", "L_3", "C_3", "L_int", "R_int"}
    assert abs(vals["R_int"] - 50.0) < 1.0                 # Rint = Z0 (normalised 1)
    k = int(np.argmin(np.abs(net.s[:, 0, 0])))             # centre frequency index
    m = res.model_s
    assert 20 * np.log10(abs(m[k, 0, 0])) < -20            # matched input
    s21 = 20 * np.log10(abs(m[k, 1, 0])); s31 = 20 * np.log10(abs(m[k, 2, 0]))
    assert abs(s21 - (-3.0)) < 0.3 and abs(s31 - (-3.0)) < 0.3   # equal -3 dB split
    dphi = (np.angle(m[k, 1, 0]) - np.angle(m[k, 2, 0])) * 180 / np.pi
    dphi = (dphi + 180) % 360 - 180
    assert abs(abs(dphi) - 90.0) < 5.0                     # quadrature outputs


def test_wilkinson_inphase_is_quarter_wave():
    """In-phase Wilkinson: matched, -3 dB equal split, and both outputs at -90 deg
    (in phase) at the centre frequency, the lumped quarter-wave divider."""
    net = _example("wpd_ihp-sg13g2.s3p")
    res = engine.convert(ConverterState(mode="structure",
                                        structure_key="wilkinson-inphase"), net)
    vals = {lab: v for lab, v, _ in res.value_rows}
    assert abs(vals["Z_c"] - np.sqrt(2) * 50.0) < 1.0 and abs(vals["R_iso"] - 100.0) < 1.0
    k = int(np.argmin(np.abs(net.s[:, 0, 0])))
    m = res.model_s
    assert 20 * np.log10(abs(m[k, 0, 0])) < -20            # matched input
    s21 = 20 * np.log10(abs(m[k, 1, 0])); s31 = 20 * np.log10(abs(m[k, 2, 0]))
    assert abs(s21 - (-3.0)) < 0.3 and abs(s31 - (-3.0)) < 0.3       # -3 dB split
    p21 = np.angle(m[k, 1, 0], deg=True); p31 = np.angle(m[k, 2, 0], deg=True)
    assert abs(p21 - (-90.0)) < 5.0 and abs(p31 - (-90.0)) < 5.0     # both -90 deg


def test_wilkinson_isolation_resistor_toggle():
    """Dropping the isolation resistor removes it from the model and degrades the
    output match (S22) from a deep null to the resistor-less ~-6 dB."""
    net = _example("wpd_ihp-sg13g2.s3p")
    k = int(np.argmin(np.abs(net.s[:, 0, 0])))

    on = engine.convert(ConverterState(mode="structure",
                        structure_key="wilkinson-inphase", iso_resistor=True), net)
    off = engine.convert(ConverterState(mode="structure",
                         structure_key="wilkinson-inphase", iso_resistor=False), net)

    assert any(lab == "R_iso" for lab, _, _ in on.value_rows)
    assert not any(lab == "R_iso" for lab, _, _ in off.value_rows)
    assert not any(e.kind == "R" for e in off.ir.elements)          # no resistor at all
    s22_on = 20 * np.log10(abs(on.model_s[k, 1, 1]) + 1e-12)
    s22_off = 20 * np.log10(abs(off.model_s[k, 1, 1]) + 1e-12)
    assert s22_on < -40.0                                            # matched output
    assert s22_off > s22_on + 20.0                                  # un-matched without R


def test_value_tolerance_at_fext():
    """Per-element tolerance is taken at f_ext: directly-read reciprocal terms match
    exactly (0 %). A symmetrised shunt carries the small port-asymmetry residual."""
    net = _example("ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p")
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi",
                                        f_extract=10e9), net)
    tol = res.value_drift
    assert tol["L_s"] < 1e-3 and tol["R_s"] < 1e-3        # series: exact at f_ext
    assert 0.0 < tol["C_p1"] < 5.0                        # shunt: symmetry residual
    # the balun extracts everything directly -> all match at f_ext
    bres = engine.convert(ConverterState(mode="structure", structure_key="balun",
                                         f_extract=7e9), net=_example("balun_ihp-sg13cmos5l.s4p"))
    assert all(v < 1e-3 for v in bres.value_drift.values())
    # clamped-placeholder values are dropped (no meaningless relative tolerance)
    mres = engine.convert(ConverterState(mode="structure", structure_key="mim-cap"),
                          _example("mim_cap_170fF_ihp-sg13g2.s2p"))
    assert "L_s" not in mres.value_drift                  # L_s clamped to ~0 -> dropped
    # universal macromodel exposes no per-element tolerance
    ures = engine.convert(ConverterState(mode="universal", max_order=6), inductor_2port())
    assert not ures.value_drift
    # the line's G' at 10 GHz sits a hair below zero.  R_sh reads it as the extractor does,
    # |G'| per cell, where a clip at 1e-30 had made it 1e30 ohm and the tolerance 1e24 %
    from snp2le.core.structures.tline import _rlgc_decomp
    line = _example("tline_100um_ihp-sg13g2.s2p")
    tres = engine.convert(ConverterState(mode="structure", structure_key="tline-rlgc",
                                         f_extract=10e9), line)
    k = int(np.argmin(np.abs(line.f - 10e9)))
    assert _rlgc_decomp(line.s, line.f, 50.0)["Gp"][k] < 0
    assert tres.value_drift["R_sh"] < 1e-3
    assert any(m.startswith("the data's G' at") and m.endswith("so R_sh is built from |G'|")
               for m in tres.messages), tres.messages
    # R' below zero at 300 GHz read 200 %, and Z_c, which the lossless sqrt(L'/C') stood
    # for, 28.5 % at 875 MHz.  Every term of the line now reads ~0 % at f_ext.
    for fx in (0.875e9, 300e9):
        r = engine.convert(ConverterState(mode="structure", structure_key="tline-rlgc",
                                          f_extract=fx), line)
        assert all(v < 1e-3 for v in r.value_drift.values()), (fx, r.value_drift)
    assert any("R' at 300 GHz is below zero" in m and m.endswith("so R_s is built from |R'|")
               for m in r.messages)
    # a negative L' means the model's reactance has the wrong sign: a capacitor fed to the
    # line model misses its data by |dS| 0.7 at 10 GHz, and L_s says so with 200 %
    mom = _example("mom_cap_74fF_02_ihp-sg13cmos5l.s2p")
    cap = engine.convert(ConverterState(mode="structure", structure_key="tline-rlgc",
                                        f_extract=10e9), mom)
    assert abs(cap.value_drift["L_s"] - 200.0) < 5.0
    assert any("L' at" in m and "L_s is built from |L'|" in m for m in cap.messages)


def test_the_line_note_names_the_terms_the_data_puts_below_zero():
    """A line with gain (G' < 0, R' > 0): arccosh(A) and sqrt(B/C) at one sample picked the
    other branch and named R', L' and C' instead of G'.  The note reads the signs off the
    same unwrapped decomposition as the plots."""
    import skrf
    f = np.linspace(1e9, 20e9, 39)
    w = 2 * np.pi * f
    z = 1e-3 + 1j * w * 60e-12                      # R' and L' of the whole line
    y = -1e-5 + 1j * w * 25e-15                     # G' below zero, C'
    zc = np.sqrt(z / y)
    gl = z / zc
    abcd = np.array([[np.cosh(gl), zc * np.sinh(gl)], [np.sinh(gl) / zc, np.cosh(gl)]])
    s = skrf.network.a2s(np.moveaxis(abcd, -1, 0), z0=50.0)
    net = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"), s=s, z0=50.0)
    res = engine.convert(ConverterState(mode="structure", structure_key="tline-rlgc",
                                        f_extract=10e9), net)
    notes = [m for m in res.messages if m.startswith("the data's")]
    assert len(notes) == 1 and notes[0].startswith("the data's G' at"), notes
    assert notes[0].endswith("so R_sh is built from |G'|")


def test_the_line_shunt_r_follows_the_resistor_limit():
    """The netlist clamps a resistor at 1e12 ohm, so R_sh does too, from 1e-12 S down, and
    an absurdly small conductance raises no overflow."""
    from snp2le.core.structures.tline import _shunt_r
    assert _shunt_r(1e-13) == 1e12 and _shunt_r(-1e-13) == 1e12 and _shunt_r(0.0) == 1e12
    assert _shunt_r(2e-12) == 5e11 and _shunt_r(-0.5) == 2.0
    with np.errstate(all="raise"):
        assert _shunt_r(5e-324) == 1e12


def test_mna_coupled_inductors_match_mutual_impedance():
    """Two magnetically coupled inductors to ground form a 2-port whose Z-matrix is
    the textbook [[jwL1, jwM],[jwM, jwL2]] with M = k*sqrt(L1*L2)."""
    from snp2le.core.ir import CircuitIR, Element
    from snp2le.core import mna
    L1, L2, k = 2e-9, 8e-9, 0.6
    ir = CircuitIR(name="xfmr", ports=["p1", "p2"])
    ir.add(Element("L", "L1", ("p1", "0"), L1))
    ir.add(Element("L", "L2", ("p2", "0"), L2))
    ir.add_coupling("L1", "L2", k)
    f = np.array([1e9, 5e9])
    Z = skrf.network.s2z(mna.rlc_sparams(ir, f, z0=50.0), z0=50.0)
    w = 2 * np.pi * f
    M = k * np.sqrt(L1 * L2)
    for i, wi in enumerate(w):
        assert abs(Z[i, 0, 0].imag - wi * L1) < 1e-4 * wi * L1
        assert abs(Z[i, 1, 1].imag - wi * L2) < 1e-4 * wi * L2
        assert abs(Z[i, 0, 1].imag - wi * M) < 1e-4 * wi * M
        assert abs(Z[i, 1, 0].imag - wi * M) < 1e-4 * wi * M


def test_balun_extracts_transformer():
    """4-port transformer balun: differential L/k/n extracted, the coupled-inductor
    model rebuilds finite, and both netlists carry the mutual coupling."""
    net = _example("balun_ihp-sg13cmos5l.s4p")
    res = engine.convert(ConverterState(mode="structure", structure_key="balun",
                                        f_extract=7e9), net)
    assert res.ok, res.error
    vals = {lab: v for lab, v, _ in res.value_rows}
    assert 0.5e-9 < vals["L_p"] < 1e-9 and 0.5e-9 < vals["L_s"] < 1e-9
    assert abs(abs(vals["k"]) - 0.694) < 0.05          # coupling matches balun.spice
    assert abs(vals["n"] - 1.0) < 0.05                 # symmetric 1:1 balun
    assert abs(vals["Q_p"] - 5.91) < 0.2 and abs(vals["Q_s"] - 5.96) < 0.2
    assert abs(vals["M"] - (-0.516e-9)) < 0.05e-9      # negative mutual, not clamped
    assert res.model_s.shape == (len(net.f), 4, 4) and np.isfinite(res.model_s).all()
    assert len(res.ir.couplings) == 2
    assert "K1 L5 L9" in res.ngspice and "K2 L7 L8" in res.ngspice
    # VACASK builtin mutual inductance: K1 () mutual k=.. ind1="L5" ind2="L9"
    assert 'K1 () mutual' in res.vacask and 'ind1="L5" ind2="L9"' in res.vacask


def test_vacask_turns_a_negative_coupling_into_a_swapped_coil():
    """VACASK's mutual refuses k < 0 ("Parameter 'k' must be between 0 and 1"), which the
    balun extracts.  Its netlist swaps one coil's terminals instead, so every k is positive.
    Rebuilt from the coil terminals and k values in the VACASK text, it is the same circuit."""
    import copy
    import re
    from snp2le.core import mna, netlist
    res = engine.convert(ConverterState(mode="structure", structure_key="balun",
                                        f_extract=7e9), _example("balun_ihp-sg13cmos5l.s4p"))
    assert res.ok and all(k < 0 for _a, _b, k in res.ir.couplings)
    coils = {m[0]: (m[1], m[2]) for m in re.findall(r"^\s+(L\w+) \((\S+) (\S+)\) inductor",
                                                     res.vacask, re.M)}
    ks = re.findall(r'mutual k=(\S+) ind1="(\w+)" ind2="(\w+)"', res.vacask)
    assert ks and all(float(k) > 0 for k, _a, _b in ks)
    rebuilt = copy.deepcopy(res.ir)
    for e in rebuilt.elements:
        if e.kind == "L":
            e.nodes = tuple("0" if n == "GND" else n for n in coils[e.name])
    rebuilt.couplings = [(a, b, float(k)) for k, a, b in ks]
    f = np.linspace(1e9, 40e9, 40)
    assert np.allclose(mna.rlc_sparams(rebuilt, f), mna.rlc_sparams(res.ir, f),
                       rtol=1e-9, atol=1e-12)
    # no negative k, nothing swapped; an odd loop of negative k cannot be balanced
    assert netlist._vc_swapped_coils([("La", "Lb", 0.3)]) == set()
    assert netlist._vc_swapped_coils([("La", "Lb", -0.3), ("Lb", "Lc", -0.3),
                                      ("La", "Lc", -0.3)]) == set()
    assert "mutual" in res.vacask.split("models needed")[1].split("\n")[0]  # in models list


def test_branchline_synthesises_quadrature_coupler():
    """Branch-line coupler: the canonical pi-LP design synthesises a 3 dB quadrature
    hybrid: matched input, isolated port 4, equal through/coupled split 90 deg apart."""
    net = _example("blc_ihp-sg13g2.s4p")
    res = engine.convert(ConverterState(mode="structure", structure_key="branchline",
                                        iso_resistor=False), net)    # ideal lossless
    assert res.ok, res.error
    vals = {lab: v for lab, v, _ in res.value_rows}
    z0 = 50.0; w0 = 2 * np.pi * res.metrics["f_extract"]
    assert np.isclose(vals["L_se"], z0 / (np.sqrt(2) * w0), rtol=1e-6)
    assert np.isclose(vals["L_sh"], z0 / w0, rtol=1e-6)
    assert np.isclose(vals["C"], (1 + np.sqrt(2)) / (z0 * w0), rtol=1e-6)
    k = int(np.argmin(np.abs(net.f - res.metrics["f_extract"])))
    m = res.model_s
    assert 20 * np.log10(abs(m[k, 0, 0])) < -40        # matched input
    assert 20 * np.log10(abs(m[k, 3, 0])) < -40        # isolated port 4
    s21 = 20 * np.log10(abs(m[k, 1, 0])); s31 = 20 * np.log10(abs(m[k, 2, 0]))
    assert abs(s21 + 3.0) < 0.3 and abs(s31 + 3.0) < 0.3            # equal -3 dB split
    dphi = (np.angle(m[k, 1, 0]) - np.angle(m[k, 2, 0])) * 180 / np.pi
    dphi = (dphi + 180) % 360 - 180
    assert abs(abs(dphi) - 90.0) < 5.0                             # quadrature


def test_branchline_arm_loss_improves_fit():
    """The 'arm loss' option fits a series R (single arm Q) so the model dissipates
    like the device: reflection terms lift off the ideal null and the RMS improves."""
    net = _example("blc_ihp-sg13g2.s4p")
    k_ref = engine.convert(ConverterState(mode="structure", structure_key="branchline",
                                          iso_resistor=False), net)
    lossy = engine.convert(ConverterState(mode="structure", structure_key="branchline",
                                          iso_resistor=True), net)
    lv = {lab: v for lab, v, _ in lossy.value_rows}
    assert {"R_se", "R_sh", "Q"} <= set(lv) and lv["R_se"] > 0 and 1 < lv["Q"] < 1e4
    assert any(e.kind == "R" for e in lossy.ir.elements)
    assert "R0" in lossy.ngspice                       # arm resistors emitted
    k = int(np.argmin(np.abs(net.f - lossy.metrics["f_extract"])))
    assert 20 * np.log10(abs(lossy.model_s[k, 0, 0])) > -35    # S11 lifted off the null
    assert lossy.rms_error < k_ref.rms_error                   # closer to the data


def test_inductor_values_recovered():
    """The inductor model should recover Ls=0.82 nH, Rs=1.4 ohm, C=40 fF closely."""
    net = inductor_2port()
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"), net)
    vals = {lab: v for lab, v, _ in res.value_rows}
    assert abs(vals["L_s"] - 0.82e-9) / 0.82e-9 < 0.05
    assert abs(vals["R_s"] - 1.4) < 0.3
    assert abs(vals["C_p1"] - 40e-15) / 40e-15 < 0.1
    assert res.rms_error < 1e-6                        # near-exact rebuild


# ---------------------------------------------------------------- VACASK export
def test_vacask_rlgc_netlist():
    """The RLGC structure exports a valid VACASK (Spectre) netlist: OSDI default
    models for the passives and `name (nodes) model param=value` instances."""
    from snp2le.core import netlist
    tline = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "snp2le", "examples", "tline_100um_ihp-sg13g2.s2p")
    net = io.load_touchstone(tline)
    res = engine.convert(ConverterState(mode="structure", structure_key="tline-rlgc"), net)
    res.ir.name = "tline_le"
    vc = netlist.render_vacask(res.ir)
    assert "subckt tline_le (p1 p2)" in vc and vc.rstrip().endswith("ends")
    assert "(p1 s1) inductor l=" in vc                 # name (nodes) model param=value
    assert "resistor r=" in vc and "capacitor c=" in vc
    assert "load " not in vc                           # loads/models come from the testbench
    assert "\nmodel " not in vc and "simulator lang=spectre" not in vc


# ---------------------------------------------------------------- resistor noise
def test_universal_resistors_are_noiseless_in_both_dialects():
    """A vector-fit model's resistors carry noisy=0, and nothing else does.

    They are scikit-rf state self-resistors and port sensors realising the fitted
    response, not devices, so their 4kTR is meaningless (on the committed 2-port it beat
    the terminations by seven decades).  ngspice and VACASK's resistor.va happen to
    spell the switch the same way, noisy."""
    from snp2le.core import netlist
    res = engine.convert(ConverterState(mode="universal", max_order=6),
                         _example("bpf_ihp-sg13g2.s2p"))
    res.ir.name = "bpf_le"
    assert not res.ir.physical
    ng = netlist.render_ngspice(res.ir)
    vc = netlist.render_vacask(res.ir)
    n_res = sum(1 for e in res.ir.elements if e.kind == "R")
    assert n_res > 0
    assert ng.count("noisy=0") == n_res and vc.count("noisy=0") == n_res   # one per resistor
    for line in ng.splitlines():                       # never on a C, L, V or a source
        assert ("noisy=0" in line) == line.startswith("R")
    for line in vc.splitlines():
        assert ("noisy=0" in line) == (" resistor r=" in line)


def test_structure_resistors_keep_their_noise():
    """Structure models are the opposite case: their resistors are real devices.

    Riso is a physical 100 ohm resistor on the die, Rs is a coil's conductor loss and the
    shunt R its substrate loss, so silencing them would understate a divider's or an LNA
    match's noise.  Only the non-physical universal fit gets noisy=0."""
    from snp2le.core import netlist
    wpd = engine.convert(ConverterState(mode="structure", structure_key="wilkinson-inphase",
                                        iso_resistor=True), _example("wpd_ihp-sg13g2.s3p"))
    ind = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"),
                         _example("ind_500pH_ihp-sg13cmos5l.s2p"))
    for res in (wpd, ind):
        assert res.ir.physical
        assert any(e.kind == "R" for e in res.ir.elements)
        for text in (netlist.render_ngspice(res.ir), netlist.render_vacask(res.ir)):
            assert "noisy" not in text               # real loss keeps its thermal noise


# ---------------------------------------------------------------- fit range
def test_fit_range_restricts_the_data():
    """A sub-band fit sees only the points inside it, in both modes, and everything
    downstream (plot payload, model response) is on that same grid."""
    net = inductor_2port()                       # 0.1 to 20 GHz, 101 points
    band = ConverterState(mode="universal", max_order=8, f_min=5e9, f_max=10e9)
    res = engine.convert(band, net)
    assert res.ok, res.error
    assert res.band_limited
    assert res.freq[0] >= 5e9 and res.freq[-1] <= 10e9
    assert len(res.freq) < len(net.f)
    assert res.data_s.shape == (len(res.freq), 2, 2)
    assert res.model_s.shape == (len(res.freq), 2, 2)
    assert any("fit range" in m for m in res.messages)

    st = ConverterState(mode="structure", structure_key="inductor-pi",
                        f_extract=7e9, f_min=5e9, f_max=10e9)
    res = engine.convert(st, net)
    assert res.ok, res.error
    assert res.band_limited and res.freq[0] >= 5e9 and res.freq[-1] <= 10e9


def test_full_range_is_the_default():
    """No band given: identical result to before the option existed."""
    net = inductor_2port()
    res = engine.convert(ConverterState(mode="universal", max_order=8), net)
    assert res.ok and not res.band_limited
    assert len(res.freq) == len(net.f)
    assert not any("fit range" in m for m in res.messages)


def test_fit_range_open_on_one_side():
    net = inductor_2port()
    lo = engine.convert(ConverterState(mode="universal", max_order=6, f_min=10e9), net)
    assert lo.ok and lo.freq[0] >= 10e9 and lo.freq[-1] == net.f[-1]
    hi = engine.convert(ConverterState(mode="universal", max_order=6, f_max=10e9), net)
    assert hi.ok and hi.freq[0] == net.f[0] and hi.freq[-1] <= 10e9


def test_fit_range_edges_outside_the_data_are_clamped():
    """A band wider than the file is not an error: it is clamped to the data and noted."""
    net = inductor_2port()
    res = engine.convert(ConverterState(mode="universal", max_order=6,
                                        f_min=1e6, f_max=100e9), net)
    assert res.ok and not res.band_limited
    assert len(res.freq) == len(net.f)
    assert any("below the data" in m for m in res.messages)
    assert any("above the data" in m for m in res.messages)


def test_invalid_fit_range_is_reported():
    """Inverted, off-the-data and too-thin bands fail with a readable message rather
    than a model fitted to nonsense."""
    net = inductor_2port()
    inverted = engine.convert(
        ConverterState(mode="universal", f_min=10e9, f_max=5e9), net)
    assert not inverted.ok and "empty" in inverted.error

    outside = engine.convert(ConverterState(mode="universal", f_min=200e9), net)
    assert not outside.ok and "outside the data" in outside.error

    thin = engine.convert(
        ConverterState(mode="universal", f_min=10e9, f_max=10.05e9), net)
    assert not thin.ok and "at least" in thin.error


def test_fit_range_survives_a_design_round_trip():
    st = ConverterState(mode="universal", f_min=110e9, f_max=170e9)
    back = ConverterState.from_json(st.to_json())
    assert (back.f_min, back.f_max) == (110e9, 170e9)
    assert ConverterState.from_json('{"mode": "universal"}').f_min is None


def test_a_failed_conversion_leaves_no_output_from_an_earlier_run(tmp_path, capsys,
                                                                  monkeypatch):
    """A refused --thermal-noise used to leave the previous noiseless netlist in place,
    which passes for the result (a Makefile takes it as up to date).  A failed input now
    removes the files at its output paths and says so, except files the same run wrote, and
    a successful run overwrites as before."""
    import shutil
    from snp2le import cli
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "snp2le", "examples", "wpd_ihp-sg13g2.s3p")
    out = tmp_path / "wpd_le.spice"
    for path in (out, tmp_path / "wpd_le.inc"):
        path.write_text("* stale\n")
    assert cli.main(["convert", src, "--order", "6", "--no-passive", "--thermal-noise",
                     "--format", "both", "-o", str(out), "--quiet"]) == 1
    assert not out.exists() and not (tmp_path / "wpd_le.inc").exists()
    assert "removed" in capsys.readouterr().err
    assert cli.main(["convert", src, "--order", "6", "--format", "both", "-o", str(out),
                     "--quiet"]) == 0
    assert "stale" not in out.read_text() and "removed" not in capsys.readouterr().err
    # two inputs with one output name: the second fails, the first's netlist stays
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
    shutil.copy(src, tmp_path / "a" / "wpd.s3p")
    (tmp_path / "b" / "wpd.s3p").write_text("not a touchstone file\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["convert", str(tmp_path / "a" / "wpd.s3p"),
                     str(tmp_path / "b" / "wpd.s3p"), "--order", "6", "--quiet"]) == 1
    assert (tmp_path / "wpd.spice").read_text().startswith("* wpd")
    assert "removed" not in capsys.readouterr().err


def test_a_hand_edited_design_reads_its_tick_boxes_as_written():
    """bool("no") is True, so a design saying "thermal_noise": "no" used to tick the box.
    Words, 0/1 and null now read as meant, anything else refuses to load with the field's
    name (the GUI shows it in its Load failed dialog), and a saved design is unchanged."""
    import json
    import pytest
    load = lambda **kw: ConverterState.from_json(json.dumps(kw))     # noqa: E731
    assert load(thermal_noise="no").thermal_noise is False
    assert load(thermal_noise=" Yes ").thermal_noise is True
    assert load(enforce_passivity="false").enforce_passivity is False
    assert load(iso_resistor=0).iso_resistor is False
    assert load(basic_model=1).basic_model is True
    assert load(enforce_passivity=None).enforce_passivity is True       # null: the default
    for bad in ("maybe", 2, [], {}):
        with pytest.raises(ValueError, match="thermal_noise must be true or false"):
            load(thermal_noise=bad)
    st = ConverterState(thermal_noise=True, enforce_passivity=False, basic_model=True,
                        iso_resistor=False)
    assert ConverterState.from_json(st.to_json()) == st


def test_restrict_band_keeps_the_network_intact():
    """The cropped network is a real skrf Network, not a view: same ports and z0."""
    net = inductor_2port()
    out, notes = io.restrict_band(net, 5e9, 10e9)
    assert out.nports == net.nports
    assert float(np.real(out.z0.flatten()[0])) == float(np.real(net.z0.flatten()[0]))
    assert len(out.f) == int(np.count_nonzero((net.f >= 5e9) & (net.f <= 10e9)))
    assert notes and "fit range" in notes[0]
    same, notes = io.restrict_band(net, None, None)
    assert same is net and notes == []


# ---------------------------------------------------------------- port references
def _referred(net, z0):
    """The same device with its ports referred to `z0`, one value or one per port."""
    out = net.copy()
    out.renormalize(z0)
    return out


def test_a_network_with_one_real_reference_is_left_alone():
    import glob
    paths = glob.glob(os.path.join(os.path.dirname(io.__file__), "..", "examples", "*.s*p"))
    assert paths
    for path in paths:
        net = io.load_touchstone(path)
        same, notes = io.uniform_reference(net)
        assert same is net and notes == [], path


def test_mixed_references_are_renormalised_before_a_structure_extraction():
    """The extractors, the model rebuild and the traces read port 1's z0 for every port.  At
    50 / 75 ohm the wideband coil's RMS error read 0.127 instead of 5.0e-3, the pi model's
    data traces were off by a median 128 %, and its tolerances moved."""
    truth = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    mixed = _referred(truth, np.array([50.0, 75.0]))
    # the pi model is read off in closed form, the wideband one is a least-squares fit whose
    # R_skin2 moves by 0.2 % when the data move by the renormalisation's 1e-12
    for key, rtol in (("inductor-pi", 1e-6), ("inductor-wideband", 1e-2)):
        st = ConverterState(mode="structure", structure_key=key)
        a, b = engine.convert(st, truth), engine.convert(st, mixed)
        assert b.ok, key
        assert b.messages[0] == "port references 50 ohm, 75 ohm renormalised to 50 ohm"
        if key == "inductor-pi":
            assert b.messages[1:] == a.messages
        assert np.allclose(b.data_s, a.data_s, rtol=0, atol=1e-10)
        assert np.isclose(b.rms_error, a.rms_error, rtol=rtol), key
        for (la, va, ua), (lb, vb, ub) in zip(a.value_rows, b.value_rows):
            assert (la, ua) == (lb, ub) and np.isclose(va, vb, rtol=rtol), (key, la)
        for lab, tol in a.value_drift.items():
            assert np.isclose(b.value_drift[lab], tol, rtol=rtol, atol=1e-9), (key, lab)
        for name, panels in a.aux_traces.items():
            for side in ("top", "bottom"):
                assert np.allclose(b.aux_traces[name][side]["data"], panels[side]["data"],
                                   rtol=1e-5, equal_nan=True), (key, name, side)
    assert np.allclose(mixed.z0[0], [50, 75])           # the caller's network is untouched


def test_mixed_references_reach_a_universal_fit_at_50_ohm():
    truth = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    res = engine.convert(ConverterState(max_order=6), _referred(truth, np.array([50.0, 75.0])))
    assert res.ok and res.messages[0] == "port references 50 ohm, 75 ohm renormalised to 50 ohm"
    assert np.allclose(res.data_s, truth.s, rtol=0, atol=1e-10)
    sensors = [l.split()[3] for l in res.ngspice.splitlines() if l.startswith(("R1 s1", "R2 s2"))]
    assert sensors == ["50.0", "50.0"]


def test_complex_and_frequency_dependent_references_are_renormalised():
    truth = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    for z0, what in ((50 + 10j, "complex port references"),
                     (np.linspace(40, 60, len(truth.f))[:, None] * np.ones(2),
                      "port references that vary with frequency"),
                     (np.array([50.0, 50.04]), "port references 50 ohm, 50.04 ohm")):
        out, notes = io.uniform_reference(_referred(truth, z0))
        assert notes == [f"{what} renormalised to 50 ohm"]
        assert np.all(out.z0 == 50) and np.allclose(out.s, truth.s, rtol=0, atol=1e-10)


def test_a_row_without_finite_data_is_kept_and_the_rest_renormalised():
    """renormalize rejects NaN, so a mixed-reference file with a solver's NaN at 0 Hz stopped
    the conversion with an exception, and the CLI with it."""
    truth = _example("tline_100um_ihp-sg13g2.s2p")
    plain = truth.copy()
    plain.s[0] = np.nan
    mixed = _referred(truth, np.array([50.0, 75.0]))
    mixed.s[0] = np.nan
    out, _ = io.uniform_reference(mixed)
    assert np.isnan(out.s[0]).all() and np.all(out.z0 == 50)
    assert np.allclose(out.s[1:], truth.s[1:], rtol=0, atol=1e-10)
    a, b = engine.convert(ConverterState(), plain), engine.convert(ConverterState(), mixed)
    assert a.ok and b.ok, b.error
    assert np.isclose(b.rms_error, a.rms_error, rtol=1e-6)


def test_load_touchstone_still_takes_a_file_object():
    with open(_example_path("bpf_ihp-sg13g2.s2p")) as fh:
        assert io.load_touchstone(fh).nports == 2


def test_an_hfss_export_with_imaginary_port_impedances_gives_a_finite_netlist(tmp_path):
    """An HFSS export that is not renormalised carries each port's impedance per frequency,
    imaginary below cutoff.  Port 1's real part, 0 ohm, became both port resistors and put
    inf and nan into a netlist the conversion returned as ok."""
    import re
    truth = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    net = truth[np.arange(len(truth.f)) % 10 == 0]
    z = 1j * np.stack([np.linspace(29, 31, len(net.f)), np.linspace(57, 61, len(net.f))], axis=1)
    exported = net.copy()
    exported.renormalize(z, s_def="traveling")         # the wave definition scikit-rf gives HFSS
    path = tmp_path / "hfss.s2p"
    with open(path, "w") as fh:
        fh.write("!Data is not renormalized\n# GHZ S MA\n")
        for k, fr in enumerate(net.f):
            fh.write(f"{fr / 1e9:.15g} " + " ".join(
                f"{abs(v):.15e} {np.degrees(np.angle(v)):.15e}" for v in exported.s[k].T.flatten()))
            fh.write("\n! Gamma ! 1.0 0.0 1.0 0.0\n! Port Impedance "
                     + " ".join(f"{v.real:.15e} {v.imag:.15e}" for v in z[k]) + "\n")
    loaded = io.load_touchstone(str(path))
    assert np.allclose(loaded.z0, z)
    res = engine.convert(ConverterState(max_order=6), loaded)
    assert res.ok
    assert res.messages[0] == "port references that vary with frequency renormalised to 50 ohm"
    assert np.allclose(res.data_s, net.s, rtol=0, atol=1e-10)
    assert not re.search(r"\b(inf|nan)\b", res.ngspice + res.vacask, re.I)


def _touchstone_11(tmp_path, refs, name="refs.s2p"):
    """The 500 pH coil as a Touchstone 1.1 file with one reference resistance per port."""
    truth = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    s = _referred(truth, np.array(refs, float)).s
    path = tmp_path / name
    with open(path, "w") as fh:
        fh.write("# Hz S RI R " + " ".join(f"{r:g}" for r in refs) + "\n")
        for fr, m in zip(truth.f, s):
            fh.write(f"{fr:.9e} " + " ".join(f"{v.real:.15e} {v.imag:.15e}" for v in m.T.flatten())
                     + "\n")
    return str(path), truth


def test_an_option_line_with_one_reference_per_port_is_read_as_written_or_refused(tmp_path):
    """scikit-rf below 2.2 reads only the first R, and the coil's universal netlist then
    missed the device by 0.126 rms against a fit error of 7e-5, without a word."""
    path, truth = _touchstone_11(tmp_path, (50, 75))
    try:
        net = io.load_touchstone(path)
    except ValueError as exc:                           # scikit-rf below 2.2
        assert "one reference resistance per port (50 ohm, 75 ohm)" in str(exc)
        assert "scikit-rf 2.2 and later read it as written" in str(exc)
    else:                                               # scikit-rf 2.2 and later
        assert np.allclose(net.z0[0], [50, 75])
        st = ConverterState(mode="structure", structure_key="inductor-pi")
        assert np.isclose(engine.convert(st, net).rms_error, engine.convert(st, truth).rms_error,
                          rtol=1e-6)


def test_a_per_port_option_line_read_as_one_reference_is_refused(tmp_path):
    """The refusal on any scikit-rf, given the network as one below 2.2 hands it over."""
    import pytest
    path, truth = _touchstone_11(tmp_path, (50, 75))
    with pytest.raises(ValueError, match=r"reads as 50 ohm, 50 ohm\. scikit-rf 2\.2"):
        io._check_option_references(path, truth)          # truth has 50 ohm on both ports
    with pytest.raises(ValueError, match="2 reference resistances .* for 3 ports"):
        io._check_option_references(path, _example("wpd_ihp-sg13g2.s3p"))
    one = skrf.Network(frequency=truth.frequency, s=truth.s[:, :1, :1], z0=50)
    with pytest.raises(ValueError, match="for 1 port$"):
        io._check_option_references(path, one)
    io._check_option_references(_touchstone_11(tmp_path, (50, 50), "same.s2p")[0], truth)
    io._check_option_references(_example_path("bpf_ihp-sg13g2.s2p"), truth)


def test_the_option_line_references_are_read_in_any_order(tmp_path):
    for line, want in (("# GHz S RI R 50 75 ! two ports", [50, 75]),
                       ("# R 50 75 GHz S RI", [50, 75]),
                       ("#GHZ S MA R 50", [50]),
                       ("# GHz S MA", [])):
        path = tmp_path / "head.s2p"
        path.write_text(f"! a comment # with a hash\n{line}\n1 0 0 1 0 1 0 0 0\n")
        assert io._option_references(str(path)) == want, line


# ---------------------------------------------------------------- edge cases
def test_dc_point_is_dropped():
    net = inductor_2port(with_dc=True)
    assert net.f[0] == 0
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"), net)
    assert res.ok
    assert res.freq[0] > 0                              # DC removed downstream


def test_structure_rejects_wrong_port_count():
    f = skrf.Frequency(1, 20, 21, "ghz")
    one = skrf.Network(frequency=f, s=0.2 * np.ones((21, 1, 1)), z0=50)
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"), one)
    assert not res.ok and "2-port" in res.error


def test_no_network():
    res = engine.convert(ConverterState(), None)
    assert not res.ok and res.error


# ---------------------------------------------------------------- sim import
def test_load_ngspice_sim():
    import tempfile
    text = (" frequency  s11_db  s21_db  s11_deg  s21_deg \n"
            " 1.0e9  -3.0  -0.5  10.0  -20.0 \n"
            " 2.0e9  -6.0  -1.0  15.0  -25.0 \n")
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        sim = io.load_ngspice_sim(path)
    finally:
        os.unlink(path)
    assert list(sim["f"]) == [1.0e9, 2.0e9]
    assert sim["S11"]["db"][0] == -3.0
    assert sim["S21"]["deg"][1] == -25.0          # phase column keyed correctly
    assert "S12" not in sim                        # only present columns parsed


def test_load_ngspice_sim_mixed_case_headers():
    """The .sch testbenches declare s11_dB; ngspice happens to lower-case the
    wrdata header, but the parser must not rely on it."""
    import tempfile
    text = (" frequency  s11_dB  S11_DEG \n"
            " 1.0e9  -3.0  45.0 \n"
            " 2.0e9  -6.0  90.0 \n")
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        sim = io.load_ngspice_sim(path)
    finally:
        os.unlink(path)
    assert sim["S11"]["db"][1] == -6.0
    assert sim["S11"]["deg"][0] == 45.0


# ------------------------------------------------------------- passivity bound
def test_passivity_ceiling_is_clamped_and_applies_only_when_enforcing():
    """An out-of-range number clamps to the limit it overshot, so the GUI can show the
    user what the limit is.  Something that is not a number has no edge to clamp to and
    falls back to the strict default.  Without enforcement nothing aims at the ceiling, so
    the model is judged strictly."""
    from snp2le.core import universal as u
    assert u.clamp_passivity_ceiling(1.05) == 1.05
    assert u.clamp_passivity_ceiling("1.05") == 1.05
    assert u.clamp_passivity_ceiling(u.PASSIVITY_CEILING_MIN) == u.PASSIVITY_CEILING_MIN
    assert u.clamp_passivity_ceiling(u.PASSIVITY_CEILING_MAX) == u.PASSIVITY_CEILING_MAX
    # too large clamps up to the ceiling, too small down to the floor
    for big in (1.201, 9.9, float("inf")):
        assert u.clamp_passivity_ceiling(big) == u.PASSIVITY_CEILING_MAX, big
    for small in (0.999, 0.5, -3.0, float("-inf")):
        assert u.clamp_passivity_ceiling(small) == u.PASSIVITY_CEILING_MIN, small
    # not a number at all: no edge to pick, so the strict default
    for bad in (None, "", "abc", float("nan")):
        assert u.clamp_passivity_ceiling(bad) == u.PASSIVITY_CEILING_DEFAULT, bad

    # the ceiling is what the enforcement aims at, so it only applies while enforcing
    assert u.effective_ceiling(True, 1.05) == 1.05
    assert u.effective_ceiling(True, 5.0) == u.PASSIVITY_CEILING_MAX
    assert u.effective_ceiling(False, u.PASSIVITY_CEILING_MAX) == u.PASSIVITY_CEILING_DEFAULT


def test_sigma_max_is_measured_without_enforcement():
    """The raw fit of the bundled BPF is slightly non-passive.  With enforcement off the
    model is exported exactly as fitted, and sigma_max says by how much it misses."""
    from snp2le.core import universal
    net = io.without_dc(_example("bpf_ihp-sg13g2.s2p"))
    raw = universal.fit_universal(net, max_order=13, enforce_passivity=False)
    assert raw.sigma_max == raw.sigma_max                  # a real number, not NaN
    assert raw.sigma_max > 1.0                             # this file does violate
    assert not raw.passive                                 # judged strictly, so it fails
    assert raw.passivity_ceiling == universal.PASSIVITY_CEILING_DEFAULT

    # the ceiling is ignored without enforcement: nothing aims at it, nothing is modified
    ignored = universal.fit_universal(net, max_order=13, enforce_passivity=False,
                                      passivity_ceiling=universal.PASSIVITY_CEILING_MAX)
    assert ignored.passivity_ceiling == universal.PASSIVITY_CEILING_DEFAULT
    assert abs(ignored.sigma_max - raw.sigma_max) < 1e-9
    assert abs(ignored.rms_error - raw.rms_error) < 1e-12
    assert not ignored.passive


def test_a_relaxed_target_is_reached_and_costs_less_accuracy():
    """The point of the ceiling: enforcing down to 1.05 instead of 1.0 reaches 1.05 and
    keeps a fit closer to the data than strict enforcement would.  The Wilkinson is the
    example where all three outcomes are distinguishable."""
    from snp2le.core import universal
    net = io.without_dc(_example("wpd_ihp-sg13g2.s3p"))
    raw = universal.fit_universal(net, max_order=6, enforce_passivity=False)
    strict = universal.fit_universal(net, max_order=6, enforce_passivity=True,
                                     passivity_ceiling=1.00)
    mid = universal.fit_universal(net, max_order=6, enforce_passivity=True,
                                  passivity_ceiling=1.05)

    assert raw.sigma_max > 1.05                            # there is something to correct
    assert strict.sigma_max <= 1.0 + 1e-6 and strict.passive
    assert mid.sigma_max <= 1.05 + 1e-6 and mid.passive    # the ceiling was reached
    assert mid.sigma_max > 1.0                             # and not overshot to strict
    # the whole reason for the control: a raised ceiling costs less accuracy
    assert raw.rms_error < mid.rms_error < strict.rms_error


def test_a_target_above_the_fit_leaves_the_model_untouched():
    """Aiming above what the fit already measures must not *add* gain to reach it."""
    from snp2le.core import universal
    net = io.without_dc(_example("bpf_ihp-sg13g2.s2p"))
    raw = universal.fit_universal(net, max_order=13, enforce_passivity=False)
    high = universal.fit_universal(net, max_order=13, enforce_passivity=True,
                                   passivity_ceiling=universal.PASSIVITY_CEILING_MAX)
    assert raw.sigma_max < universal.PASSIVITY_CEILING_MAX
    assert abs(high.sigma_max - raw.sigma_max) < 1e-9      # untouched
    assert abs(high.rms_error - raw.rms_error) < 1e-12     # accuracy fully kept
    assert high.passive                                    # and it meets the ceiling


def test_passivity_ceiling_flows_through_engine_and_state():
    from snp2le.core import universal
    net = _example("wpd_ihp-sg13g2.s3p")
    st = ConverterState(mode="universal", max_order=6, enforce_passivity=True,
                        passivity_ceiling=1.05)
    res = engine.convert(st, net)
    assert res.ok
    assert res.passivity_ceiling == 1.05
    assert res.sigma_max == res.sigma_max and res.passive
    assert res.sigma_max <= 1.05 + 1e-6
    # the setting survives a design save/load round trip
    assert ConverterState.from_json(st.to_json()).passivity_ceiling == st.passivity_ceiling


def test_structure_mode_reports_no_sigma_max():
    """A structure model is an RLC network, passive by construction, so it carries no
    measured sigma_max and its bound stays at the strict default."""
    res = engine.convert(ConverterState(mode="structure", structure_key="mim-cap",
                                        f_extract=10e9),
                         _example("mim_cap_170fF_ihp-sg13g2.s2p"))
    assert res.ok and res.passive
    assert res.sigma_max != res.sigma_max                  # NaN
    assert res.passivity_ceiling == 1.0


def test_cli_passivity_ceiling_argument():
    """--passivity-ceiling parses inside the range, is refused outside it, and stays None
    when it is not given, so the CLI can tell 'default' from 'explicitly 1.0'."""
    from snp2le import cli
    p = cli.build_parser()
    assert p.parse_args(["convert", "x.s2p", "--no-passive",
                         "--passivity-ceiling", "1.05"]).passivity_ceiling == 1.05
    assert p.parse_args(["convert", "x.s2p"]).passivity_ceiling is None
    for bad in ("0.9", "1.5", "abc"):
        try:
            p.parse_args(["convert", "x.s2p", "--passivity-ceiling", bad])
        except SystemExit:
            continue
        raise AssertionError(f"--passivity-ceiling {bad} should have been refused")


def test_max_order_bounds_the_model_order():
    """`Max order` caps the model order, n_real + 2 x n_complex, so the pole count the
    GUI reports (a conjugate pair counted once) can never exceed it.

    Issue #7: below scikit-rf 1.12 `model_order_max` was only the growth loop's exit
    test, so a cap under the order 9 of auto_fit's default initial pole set did nothing
    and order 6 came back as 7 poles."""
    from skrf.vectorFitting import VectorFitting
    from snp2le.core import universal
    net = io.without_dc(_example("ind_500pH_ihp-sg13cmos5l.s2p"))
    for order in (2, 6, 9):
        res = universal.fit_universal(net, max_order=order, enforce_passivity=False)
        assert VectorFitting.get_model_order(np.atleast_1d(res.vf.poles)) <= order, order
        # what the GUI reports: the order is what the cap is set in, the pole count
        # counts a conjugate pair once, so it is the smaller of the two
        assert res.model_order <= order, order
        assert res.n_poles <= res.model_order <= 2 * res.n_poles, order
        assert res.model_order == VectorFitting.get_model_order(
            np.atleast_1d(res.vf.poles)), order


def test_model_order_reaches_the_results():
    """The order the panel and the CLI print comes through the engine, not just the fit."""
    res = engine.convert(ConverterState(mode="universal", max_order=6), inductor_2port())
    assert res.ok and 0 < res.n_poles <= res.model_order <= 6
    # structure mode has no fit, so it reports no order at all
    struct = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"),
                            inductor_2port())
    assert struct.ok and struct.model_order == 0


def test_auto_fit_starts_inside_the_requested_order():
    """The initial pole set is clamped to the cap, which is what makes the cap hold on
    scikit-rf below 1.12.  On 1.12 and later the same two numbers are what scikit-rf
    computes itself, so passing them changes nothing.  Above the default initial order
    nothing is passed and the adaptive growth path is untouched."""
    from snp2le.core import universal
    seen = {}

    class Recorder:
        def __init__(self, net):
            pass

        def auto_fit(self, **kwargs):
            seen.update(kwargs)

    real = universal.VectorFitting
    universal.VectorFitting = Recorder
    try:
        universal._auto_fit(None, 6)
        assert seen == {"model_order_max": 6, "n_poles_init_real": 0,
                        "n_poles_init_cmplx": 3}, seen
        seen.clear()
        universal._auto_fit(None, 7)
        assert seen == {"model_order_max": 7, "n_poles_init_real": 1,
                        "n_poles_init_cmplx": 3}, seen
        seen.clear()
        universal._auto_fit(None, 13)
        assert seen == {"model_order_max": 13}, seen
    finally:
        universal.VectorFitting = real


def test_a_cycling_auto_fit_is_stopped_and_refitted(monkeypatch):
    """scikit-rf's auto_fit can alternate between two pole sets for good (6 of 3,200 ORCA
    fits at model_order_max=20).  Past the relocation limit the fit is stopped and redone
    with vector_fit at the pole counts it had reached, and the result says so.  A limit of
    5 stands in for the cycle: the BPF needs 20 relocations at order 20."""
    from snp2le.core import universal
    monkeypatch.setattr(universal, "_AUTO_FIT_MAX_RELOCATIONS", 5)
    res = engine.convert(ConverterState(mode="universal", max_order=20, enforce_passivity=False),
                         _example("bpf_ihp-sg13g2.s2p"))
    assert res.ok, res.error
    notes = [m for m in res.messages if "did not settle" in m]
    assert len(notes) == 1 and "refitted with vector_fit" in notes[0], res.messages
    assert 0 < res.model_order <= 20 and res.rms_error < 0.1


def test_the_relocation_limit_stays_with_its_own_fit():
    """The limit wraps the fit instance, so another fit, in this thread or a parallel one,
    neither shares its count nor finds scikit-rf's class patched."""
    from snp2le.core import universal
    from skrf.vectorFitting import VectorFitting
    net = io.without_dc(_example("bpf_ihp-sg13g2.s2p"))
    on_class = VectorFitting.__dict__["_pole_relocation"]
    first, second = VectorFitting(net), VectorFitting(net)
    universal._RelocationLimit(first)
    assert "_pole_relocation" in vars(first) and "_pole_relocation" not in vars(second)
    assert VectorFitting.__dict__["_pole_relocation"] is on_class


def test_the_fit_handed_back_carries_no_relocation_limit():
    """The limit comes off once auto_fit returns, so a caller who refits the returned model
    later is not stopped by a count this fit left behind."""
    from snp2le.core import universal
    fit = universal.fit_universal(io.without_dc(_example("bpf_ihp-sg13g2.s2p")), max_order=13)
    assert "_pole_relocation" not in vars(fit.vf)


def test_a_failure_without_a_message_still_names_the_error(monkeypatch):
    """str() of some exceptions is empty, and an empty Results.error leaves the caller with
    a failure and no word on what failed."""
    def fail(*args, **kwargs):
        raise RuntimeError()
    monkeypatch.setattr(engine, "_convert_universal", fail)
    res = engine.convert(ConverterState(mode="universal"), inductor_2port())
    assert not res.ok and res.error == "RuntimeError"


def test_the_result_names_how_passivity_enforcement_went():
    """Results.passivity_path says which branch produced the model, so a caller does not
    have to read it out of the messages."""
    cases = (("bpf_ihp-sg13g2.s2p", dict(max_order=6), "not needed"),
             ("wpd_ihp-sg13g2.s3p", dict(max_order=6), "perturbed"),
             ("balun_ihp-sg13cmos5l.s4p", dict(max_order=6), "near-passive"),
             ("wpd_ihp-sg13g2.s3p", dict(max_order=6, enforce_passivity=False), "off"))
    for name, kw, path in cases:
        res = engine.convert(ConverterState(mode="universal", **kw), _example(name))
        assert res.ok and res.passivity_path == path, (name, kw, res.passivity_path)
    struct = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"),
                            inductor_2port())
    assert struct.ok and struct.passivity_path == ""


def test_a_constant_term_above_the_ceiling_is_named():
    """The balun at order 6 has a constant term D above 1, a violation band that runs to
    infinity and that the residue perturbation cannot move.  The message names D and the
    knob that is left.  A model that violates elsewhere (the raw WPD, at 0 Hz) gets no
    such line, and the line never reads as an enforcement the GUI would call near-passive."""
    import re

    def d_lines(res):
        return [m for m in res.messages if "constant term D" in m]

    free = engine.convert(ConverterState(mode="universal", max_order=6, enforce_passivity=False),
                          _example("balun_ihp-sg13cmos5l.s4p"))
    (line,) = d_lines(free)
    sigma_d = float(re.search(r"has sigma ([0-9.]+)", line).group(1))
    assert sigma_d > 1.0 and "would have to refit at a lower order" in line
    assert not any("passivity enforced" in m for m in free.messages)
    tried = engine.convert(ConverterState(mode="universal", max_order=6),
                           _example("balun_ihp-sg13cmos5l.s4p"))
    (line,) = d_lines(tried)
    assert tried.passivity_path == "near-passive" and line.endswith("try another Max order")
    wpd = engine.convert(ConverterState(mode="universal", max_order=6, enforce_passivity=False),
                         _example("wpd_ihp-sg13g2.s3p"))
    assert wpd.sigma_max > 1.0 and not d_lines(wpd)


def test_cli_picks_the_simulator_from_the_file_name():
    """As the GUI does: a folder named vacask_runs/ must not pick VACASK for an Ngspice
    testbench."""
    from snp2le import cli
    assert cli._simulator_for("tb/two_port_tb_acsp_vacask.sch") == "vacask"
    assert cli._simulator_for("vacask_runs/two_port_tb_acsp_ngspice.sch") == "ngspice"


def test_every_structure_has_a_solvable_dc_operating_point():
    """VACASK aborts on a singular DC operating point where Ngspice falls back to gmin
    stepping, so every extracted model must solve at DC on the data it is meant for (an
    inductor model on the band-pass filter clamps its values and is not).  The lossless
    branch-line coupler's four arm inductors used to form a loop with an undetermined
    current."""
    from snp2le.core import dc
    pairs = {"ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p": ("inductor-pi",),
             "ind_500pH_ihp-sg13cmos5l.s2p": ("inductor-pi",),
             "mim_cap_170fF_ihp-sg13g2.s2p": ("mim-cap",),
             "mom_cap_74fF_02_ihp-sg13cmos5l.s2p": ("mim-cap",),
             "tline_100um_ihp-sg13g2.s2p": ("tline-rlgc",),
             "wpd_ihp-sg13g2.s3p": ("wilkinson", "wilkinson-inphase"),
             "blc_ihp-sg13g2.s4p": ("branchline",),
             "balun_ihp-sg13cmos5l.s4p": ("balun", "branchline")}
    # the wideband fits are checked in test_inductor_wideband.py, on its module fixtures
    assert ({k for keys in pairs.values() for k in keys}
            == {k for k, _, _ in structure_items() if not get_structure(k).wideband})
    for name, keys in pairs.items():
        net = _example(name)
        for key in keys:
            for iso in (True, False):
                res = engine.convert(ConverterState(mode="structure", structure_key=key,
                                                    iso_resistor=iso), net)
                assert res.ok and dc.dc_check(res.ir).ok, (name, key, iso)


def test_the_lossless_branchline_keeps_its_response():
    """The loop resistor moves S by about 1e-8 and stays out of the noise and the values."""
    import copy
    from snp2le.core import mna
    net = _example("blc_ihp-sg13g2.s4p")
    res = engine.convert(ConverterState(mode="structure", structure_key="branchline",
                                        iso_resistor=False), net)
    loop = next(e for e in res.ir.elements if e.name == "Rloop")
    assert loop.value == 1e-6 and loop.noisy is False
    assert "Rloop n0 p2 1e-06 noisy=0" in res.ngspice
    assert all(lab != "R_loop" for lab, _, _ in res.value_rows)
    ideal = copy.deepcopy(res.ir)                     # the same model with the loop closed
    ideal.elements = [e for e in ideal.elements if e.name != "Rloop"]
    for e in ideal.elements:
        e.nodes = tuple("p2" if n == "n0" else n for n in e.nodes)
    f = net.f[::10]
    assert np.max(np.abs(mna.rlc_sparams(res.ir, f) - mna.rlc_sparams(ideal, f))) < 1e-6


def _example_path(name):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "snp2le", "examples", name)


def test_cli_refuses_numbers_out_of_range():
    import pytest
    from snp2le import cli
    p = cli.build_parser()
    for bad in (["--order", "1"], ["--order", "x"], ["--fmin", "-5GHz"], ["--fmax", "-1"],
                ["--fmax", "0"], ["--timeout", "0"], ["--timeout", "-1"]):
        with pytest.raises(SystemExit):
            p.parse_args(["convert", "x.s2p", *bad])
    a = p.parse_args(["convert", "x.s2p"])
    assert (a.order, a.stages, a.timeout) == (6, None, 180.0)
    # 0 Hz is an open lower edge, while a top edge of 0 Hz would fit the whole band unasked
    assert p.parse_args(["convert", "x.s2p", "--fmin", "0"]).fmin == 0.0


def test_cli_warns_about_options_that_do_nothing(tmp_path, capsys):
    from snp2le import cli
    out = str(tmp_path / "a.spice")
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "--fext", "7GHz",
                     "--stages", "4", "-o", out, "--quiet"]) == 0
    assert "--fext, --stages ignored in universal mode" in capsys.readouterr().err
    # a structure the mode ignores is named too, and an ignored --tolerances prints no table
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "--structure", "balun",
                     "--tolerances", "-o", out, "--quiet"]) == 0
    got = capsys.readouterr()
    assert "--structure, --tolerances ignored in universal mode" in got.err
    assert "tolerances" not in got.out
    assert cli.build_parser().parse_args(["convert", "x.s2p"]).structure is None
    # the default stays out of args, so a caller can run one Namespace twice
    ns = cli.build_parser().parse_args(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "-o",
                                        out, "--quiet"])
    for _ in range(2):
        assert cli.cmd_convert(ns) == 0 and "--structure" not in capsys.readouterr().err
    # an extracted structure still prints its table, and structure mode still means
    # inductor-pi without --structure
    assert cli.main(["convert", _example_path("ind_500pH_ihp-sg13cmos5l.s2p"), "--mode",
                     "structure", "--tolerances", "-o", out, "--quiet"]) == 0
    assert "tolerances (|data-model|/model at f_ext):" in capsys.readouterr().out
    assert "* inductor model, extracted at" in open(out).read()
    assert cli.main(["convert", _example_path("wpd_ihp-sg13g2.s3p"), "--mode", "structure",
                     "--structure", "wilkinson", "--stages", "3", "--no-iso-r", "-o", out,
                     "--quiet"]) == 0
    assert ("--stages, --no-iso-r ignored, wilkinson has no such option"
            in capsys.readouterr().err)
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "--basic", "-o", out,
                     "--quiet"]) == 0
    assert ("--basic ignored, it applies to the wideband inductor structures"
            in capsys.readouterr().err)
    assert cli.main(["convert", _example_path("ind_500pH_ihp-sg13cmos5l.s2p"), "--mode",
                     "structure", "--structure", "inductor-wideband", "--basic", "--stages",
                     "3", "--no-iso-r", "-o", out, "--quiet"]) == 0
    assert ("--stages, --no-iso-r ignored, inductor-wideband has no such option"
            in capsys.readouterr().err)


def test_cli_says_when_it_renames_the_subcircuit(tmp_path, capsys, monkeypatch):
    from snp2le import cli
    out = tmp_path / "my-model.spice"
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "-o", str(out),
                     "--quiet"]) == 0
    assert ".SUBCKT my_model " in out.read_text()
    assert "the subcircuit is named my_model" in capsys.readouterr().err
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "-o",
                     str(tmp_path / "plain.spice"), "--quiet"]) == 0
    assert "subcircuit is named" not in capsys.readouterr().err
    # without -o the name follows the source file, which the user did not pick
    monkeypatch.chdir(tmp_path)
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "--quiet"]) == 0
    assert ".SUBCKT bpf_ihp_sg13g2 " in (tmp_path / "bpf_ihp-sg13g2.spice").read_text()
    assert "subcircuit is named" not in capsys.readouterr().err


def test_cli_quiet_names_each_file_before_its_tables(tmp_path, capsys, monkeypatch):
    """--quiet drops the status line that names the file, so with several inputs each set of
    tables gets the file's name.  One input prints as before."""
    from snp2le import cli
    monkeypatch.chdir(tmp_path)
    srcs = [_example_path("ind_500pH_ihp-sg13cmos5l.s2p"),
            _example_path("ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p")]
    assert cli.main(["convert", *srcs, "--mode", "structure", "--values", "--tolerances",
                     "--quiet"]) == 0
    out = capsys.readouterr().out.splitlines()
    heads = [i for i, ln in enumerate(out) if ln.strip() == "element values:"]
    assert [out[i - 1] for i in heads] == [f"{s}:" for s in srcs]
    assert cli.main(["convert", srcs[0], "--mode", "structure", "--values", "--quiet"]) == 0
    assert capsys.readouterr().out.splitlines()[0].strip() == "element values:"


def test_a_file_that_breaks_the_engine_does_not_end_the_batch(tmp_path, capsys, monkeypatch):
    """An exception out of engine.convert ended the CLI with a traceback, and the files after
    it were never converted (the NaN row the port-reference fix first did not handle)."""
    from snp2le import cli
    monkeypatch.chdir(tmp_path)
    real = engine.convert

    def convert(state, net, progress=None):
        if net.nports == 4:
            progress(0.4, "fitting")                  # a live progress bar, then the failure
            raise ValueError("Array must not contain infs or NaNs")
        return real(state, net, progress)

    monkeypatch.setattr(engine, "convert", convert)
    stale = tmp_path / "blc_ihp-sg13g2.spice"
    stale.write_text("left by an earlier run\n")
    srcs = [_example_path("blc_ihp-sg13g2.s4p"), _example_path("bpf_ihp-sg13g2.s2p")]
    assert cli.main(["convert", *srcs, "--order", "6", "--progress"]) == 1
    err = capsys.readouterr().err
    assert f"[FAIL] {srcs[0]}: Array must not contain infs or NaNs" in err
    assert "fitting[FAIL]" not in err                 # printed after the bar cleared its line
    assert "Traceback" not in err
    assert not stale.exists() and (tmp_path / "bpf_ihp-sg13g2.spice").exists()


def test_cli_input_and_output_mistakes_get_one_clear_message(tmp_path, capsys):
    from snp2le import cli
    rc = cli.main(["convert", str(tmp_path / "nothing*.s2p"), "--quiet"])
    err = capsys.readouterr().err
    assert rc == 1 and err.count("no file matches") == 1 and "Errno" not in err
    folder = tmp_path / "outdir"
    folder.mkdir()
    assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "-o", str(folder),
                     "--quiet"]) == 1
    assert "that is a folder, -o takes a file name" in capsys.readouterr().err
    # also with both dialects, which wrote outdir.spice beside the folder or a hidden .spice
    # after a trailing separator, and a folder named my-dir drew the rename warning first
    dashed = tmp_path / "my-dir"
    dashed.mkdir()
    for out in (str(folder), str(dashed), str(tmp_path / "new") + os.sep):
        assert cli.main(["convert", _example_path("bpf_ihp-sg13g2.s2p"), "-o", out,
                         "--format", "both", "--quiet"]) == 1
        err = capsys.readouterr().err
        assert err.count("that is a folder, -o takes a file name") == 1, err
        assert "subcircuit is named" not in err
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == []


def test_the_netlist_names_the_snp2le_version():
    """So a netlist in a testbench or a paper can be traced to the tool that wrote it."""
    import snp2le
    res = engine.convert(ConverterState(max_order=6), _example("bpf_ihp-sg13g2.s2p"))
    want = f"generated by snp2le {snp2le.__version__}"
    assert res.ngspice.splitlines()[1] == f"* {want}"
    assert res.vacask.splitlines()[0].endswith(want)


if __name__ == "__main__":
    # allow running without pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
