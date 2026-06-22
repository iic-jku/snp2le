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
def test_all_structures_extract():
    net = inductor_2port()
    for key, _name, nports in structure_items():
        assert nports == 2
        res = engine.convert(ConverterState(mode="structure", structure_key=key), net)
        assert res.ok, (key, res.error)
        assert res.value_rows                         # has labelled values
        assert res.model_s is not None


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
