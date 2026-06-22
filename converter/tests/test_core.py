"""test_core.py - core tests (no Qt). Run with:  pytest -q

Covers the unit helpers, both conversion modes, all structures, netlist rendering
and the awkward edge cases (DC sample, wrong port count).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import skrf

from core import io, engine
from core.state import ConverterState
from core.units import parse_eng, format_eng
from core.structures import structure_items, get_structure


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


# ---------------------------------------------------------------- universal
def test_universal_fits_and_renders():
    net = inductor_2port()
    res = engine.convert(ConverterState(mode="universal", max_order=10), net)
    assert res.ok and res.error == ""
    assert res.n_poles > 0
    assert res.rms_error < 1e-2                       # good fit on a clean network
    assert ".SUBCKT" in res.ngspice and "subckt" in res.vacask
    assert res.model_s.shape == (len(net.f), 2, 2)


def test_universal_high_order_resistors_above_ngspice_floor():
    """Regression: scikit-rf's fast-pole state resistors can fall below ngspice's
    1e-12 floor at higher orders; rounding them up corrupts S11/S22.  They must be
    rescaled (not clamped) so the exported netlist has no near-floor resistors."""
    bpf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "bpf_ihp-sg13g2.s2p")
    net = io.load_touchstone(bpf)
    res = engine.convert(ConverterState(mode="universal", max_order=14), net)
    assert res.ok
    rvals = [e.value for e in res.ir.elements if e.kind == "R"]
    assert rvals and min(rvals) >= 1e-10        # clamp would leave one at 1e-12


# ---------------------------------------------------------------- structures
def _example(name):
    return io.load_touchstone(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", name))


def test_all_structures_extract():
    example = {2: lambda: inductor_2port(),
               3: lambda: _example("wpd_ihp-sg13g2.s3p"),
               4: lambda: _example("balun_ihp-sg13cmos5l.s4p")}
    for key, _name, nports in structure_items():
        net = example[nports]()
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
    (in phase) at the centre frequency - the lumped quarter-wave divider."""
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


def test_mna_coupled_inductors_match_mutual_impedance():
    """Two magnetically coupled inductors to ground form a 2-port whose Z-matrix is
    the textbook [[jwL1, jwM],[jwM, jwL2]] with M = k*sqrt(L1*L2)."""
    from core.ir import CircuitIR, Element
    from core import mna
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
    assert "mutual K1" in res.vacask                   # VACASK lists couplings as notes


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
    from core import netlist
    tline = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "examples", "tline_100um_ihp-sg13g2.s2p")
    net = io.load_touchstone(tline)
    res = engine.convert(ConverterState(mode="structure", structure_key="tline-rlgc"), net)
    res.ir.name = "tline_le"
    vc = netlist.render_vacask(res.ir)
    assert "subckt tline_le ( p1 p2 )" in vc and vc.rstrip().endswith("ends")
    assert "( p1 s1 ) inductor l=" in vc               # name ( nodes ) model param=value
    assert "resistor r=" in vc and "capacitor c=" in vc
    assert "load " not in vc                           # loads/models come from the testbench
    assert "\nmodel " not in vc and "simulator lang=spectre" not in vc


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


if __name__ == "__main__":
    # allow running without pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
