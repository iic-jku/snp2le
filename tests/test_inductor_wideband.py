# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_inductor_wideband.py - the wideband inductor structures (no Qt).

`inductor-wideband` and `inductor-ct` port Volker Muehlhaus' inductor_fit.  The reference
values below are the ones his script prints for the same files, so a change to the port
that moves the fit shows up here first.  The second half checks what snp2le adds around
the fit: the CircuitIR per coil segment, the coupled half coils, f_ext being ignored, the
progress reports and the notes.  The full center-tapped fit takes about 15 s, so it runs
once per module.  Run with:  pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                            # noqa: E402
import pytest                                                 # noqa: E402
import skrf                                                   # noqa: E402

from snp2le.core import engine, io                            # noqa: E402
from snp2le.core.state import ConverterState                  # noqa: E402
from snp2le.core.structures import STRUCTURES, structure_items  # noqa: E402
from snp2le.core.structures import inductor_fit as fitmod     # noqa: E402
from snp2le.core.structures.inductor_wideband import _row, coil_segments  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "snp2le", "examples")
IND = "ind_500pH_ihp-sg13cmos5l.s2p"
IND_CT = "ind_ct_n2_d82_w4_s4_ihp-sg13g2.s3p"


def _net(name):
    return io.load_touchstone(os.path.join(EXAMPLES, name))


def _convert(name, key, **kw):
    return engine.convert(ConverterState(mode="structure", structure_key=key, **kw), _net(name))


@pytest.fixture(scope="module")
def two_port():
    return _convert(IND, "inductor-wideband")


@pytest.fixture(scope="module")
def center_tap():
    return _convert(IND_CT, "inductor-ct")


def _values(res):
    return {lab: val for lab, val, _unit in res.value_rows}


# The references are inductor_fit.py's output on Windows (numpy 2.4, scipy 1.17).  The fit is
# deterministic for one set of libraries, but a local optimizer on another numpy, scipy or BLAS
# can settle elsewhere along directions the data barely constrains.  In IIC-OSIC-TOOLS (numpy
# 2.5, scipy 1.18) the center-tapped fit lands 0.2 % lower in cost with L_s,h and k 4.5 %
# away and R_skin2 at 2.3 x, while L, Q, the SRF and the well-determined elements agree within
# 0.3 %.  So the tests pin the topology decisions, the elements the data does determine and
# the response, each to 1 %, and leave the weak directions alone.

def test_the_two_port_fit_reproduces_the_reference(two_port):
    """inductor_fit.py on the same file: 3 segments, symmetric substrate, these totals."""
    assert two_port.ok, two_port.error
    m = two_port.metrics
    assert m["segments"] == 3
    assert m["substrate"] == "symmetric"
    ref = {"R_s": 1.84543, "L_s": 5.04813e-10, "C_s": 9.76973e-15,
           "C_ox1": 2.47652e-14, "R_si1": 1719.96, "C_si1": 2.56102e-14}
    vals = _values(two_port)
    for lab, want in ref.items():
        assert vals[lab] == pytest.approx(want, rel=1e-2), lab
    assert vals["C_ox2"] == vals["C_ox1"]                 # symmetric: port 2 tied to port 1
    assert m["L_dc"] == pytest.approx(0.5689e-9, rel=1e-2)
    assert m["Q11_peak"] == pytest.approx(15.41, rel=1e-2)
    assert m["srf_model"] == pytest.approx(50.30e9, rel=1e-2)


def test_the_center_tap_fit_reproduces_the_reference(center_tap):
    """inductor_fit.py on the same file: 2 segments per half, the half coil inductances tied,
    the resistances (an underpass in one half) and the p1/p2 substrate fitted separately."""
    assert center_tap.ok, center_tap.error
    m = center_tap.metrics
    assert m["segments"] == 2
    assert m["symmetric"] == {"inductance": True, "resistance": False, "substrate": False}
    ref = {"R_s,h1": 0.721296, "R_s,h2": 0.998252, "C_s": 4.8286e-15, "R_ct": 0.0957937,
           "C_ox1": 6.47091e-15, "C_ox,ct": 1.90788e-14, "R_si,ct": 8364.33}
    vals = _values(center_tap)
    for lab, want in ref.items():
        assert vals[lab] == pytest.approx(want, rel=1e-2), lab
    assert vals["L_s,h2"] == vals["L_s,h1"]
    assert m["L_diff_dc"] == pytest.approx(0.4700e-9, rel=1e-2)
    assert m["Qdiff_peak"] == pytest.approx(18.18, rel=1e-2)
    assert m["Qcm_peak"] == pytest.approx(10.28, rel=1e-2)
    assert m["fit_cost"] == pytest.approx(0.007279, rel=2e-2)


@pytest.mark.parametrize("which", ["two_port", "center_tap"])
def test_the_netlist_is_the_model_that_was_fitted(which, request):
    """The CircuitIR, rebuilt by snp2le's own nodal analysis (per-segment elements, the K
    couplings of the center tap), gives the response of the fit's own model function."""
    res = request.getfixturevalue(which)
    ct = which == "center_tap"
    names = fitmod.CT_PARAM_NAMES if ct else fitmod.PARAM_NAMES
    # the rows carry every fitted total, only the switched-off coupling is not an element
    vals = _values(res)
    off = {n: 10.0 ** x for n, x in fitmod.X_COUPLING_OFF.items()}
    p = np.array([vals.get(_row(n, 0.0)[0], off.get(n)) for n in names])
    w = 2 * np.pi * res.freq
    Y = (fitmod.y_model_ct if ct else fitmod.y_model)(p, w, res.metrics["segments"])
    S = skrf.network.y2s(Y, z0=50)
    assert np.max(np.abs(res.model_s - S)) < 1e-9


def test_the_center_tap_couples_every_cell_pair(center_tap):
    """2 segments per half: 4 K elements with k/2 each, rendered in both dialects."""
    ir = center_tap.ir
    assert len(ir.couplings) == 4
    k = _values(center_tap)["k"]
    assert all(kk == pytest.approx(k / 2) for _a, _b, kk in ir.couplings)
    assert center_tap.ngspice.count("\nK") == 4
    assert center_tap.vacask.count(" mutual k=") == 4
    assert ".SUBCKT inductor_ct p1 p2 p3" in center_tap.ngspice
    assert "Rct m p3" in center_tap.ngspice                # the center tap is port 3


def test_the_schematic_counts_coil_segments_not_skin_inductors(two_port, center_tap):
    """Ls_1..Ls_3 are segments, Lskin1_1 is not (the first count read 9 for 3 segments),
    and the center-tapped count is per half."""
    assert coil_segments(two_port.ir) == two_port.metrics["segments"] == 3
    assert coil_segments(center_tap.ir) == center_tap.metrics["segments"] == 2
    for res in (two_port, center_tap):
        assert res._structure.schematic_drawing(res.ir) is not None


def test_structure_resistors_keep_their_noise(two_port, center_tap):
    for res in (two_port, center_tap):
        assert res.physical
        assert "noisy=0" not in res.ngspice and "noisy=0" not in res.vacask


def test_basic_has_the_fixed_topology():
    """1 segment, 1 skin section, no substrate coupling: the same elements for any data."""
    res = _convert(IND, "inductor-wideband", basic_model=True)
    assert res.ok and res.metrics["segments"] == 1 and res.metrics["basic"]
    labels = [lab for lab, _v, _u in res.value_rows]
    assert labels == ["R_s", "L_s", "R_skin1", "L_skin1", "C_s",
                      "C_ox1", "R_si1", "C_si1", "C_ox2", "R_si2", "C_si2"]
    assert not any(e.name.startswith(("Rskin2", "Lskin2", "Rsub")) for e in res.ir.elements)
    assert "basic model" in res.messages[0]


def test_f_ext_does_not_apply():
    """A wideband model is fitted over the band: f_ext changes nothing and is not reported."""
    a = _convert(IND, "inductor-wideband", basic_model=True, f_extract=1e9)
    b = _convert(IND, "inductor-wideband", basic_model=True, f_extract=900e9)
    assert a.ngspice == b.ngspice and a.value_rows == b.value_rows
    assert "f_extract" not in a.metrics
    assert not any("ext. frequency" in m for m in b.messages)
    assert a.value_drift == {}


def test_the_fit_band_stops_past_the_self_resonance():
    """The 0.1 nH coil resonates at 223 GHz in a 500 GHz sweep: fitted to 1.2 x SRF."""
    res = _convert("ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p", "inductor-wideband",
                   basic_model=True)
    assert res.ok
    assert res.metrics["f_fit_max"] == pytest.approx(1.2 * res.metrics["srf_data"], rel=0.01)
    assert any("not fitted (beyond 1.2 x SRF)" in m for m in res.messages)


def test_a_fit_range_above_the_first_point_is_flagged():
    """The low end pins Rdc and the DC inductance, so cutting it is said out loud."""
    res = _convert(IND, "inductor-wideband", basic_model=True, f_min=2e9)
    assert res.ok
    assert any("extrapolated, not fitted" in m for m in res.messages)
    full = _convert(IND, "inductor-wideband", basic_model=True)
    assert not any("extrapolated, not fitted" in m for m in full.messages)


def test_progress_is_reported_up_to_done():
    seen = []
    engine.convert(ConverterState(mode="structure", structure_key="inductor-wideband",
                                  basic_model=True), _net(IND),
                   progress=lambda fraction, message: seen.append((fraction, message)))
    fractions = [fr for fr, _ in seen]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    assert any(msg.startswith("fitting 1 coil segment") for _, msg in seen)


def test_data_that_is_no_inductor_is_refused_with_a_reason():
    """A Wilkinson divider is no center-tapped inductor: its half coils come out negative."""
    res = _convert("wpd_ihp-sg13g2.s3p", "inductor-ct", basic_model=True)
    assert not res.ok
    assert "does not look like a center-tapped inductor" in res.error


def test_the_dropdown_defaults_did_not_move():
    """Structure mode opens on the first structure matching the port count, so the new ones
    sit behind inductor-pi (2-port) and the Wilkinsons (3-port)."""
    first = {}
    for key, _name, n in structure_items():
        first.setdefault(n, key)
    assert first == {2: "inductor-pi", 3: "wilkinson-inphase", 4: "balun"}
    assert {k for k, s in STRUCTURES.items() if s.wideband} == {"inductor-wideband",
                                                                 "inductor-ct"}
