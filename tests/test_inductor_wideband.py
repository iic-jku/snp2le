# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_inductor_wideband.py - the wideband inductor structures (no Qt).

`inductor-wideband` and `inductor-ct` port Volker Muehlhaus' inductor_fit.  The reference
values below are the ones his script prints for the same files, so a change to the port
that moves the fit shows up here first.  The second half checks what snp2le adds around
the fit: the CircuitIR per coil segment, the coupled half coils, f_ext being ignored, the
progress reports and the notes.  The full center-tapped fit takes about 6 s, so it runs
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
from snp2le.core.structures import (STRUCTURES, default_structure,   # noqa: E402
                                    structure_items)
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


def test_the_wideband_models_solve_at_dc(two_port, center_tap):
    """VACASK aborts on a singular DC operating point. test_core.py checks the other
    structures."""
    from snp2le.core import dc
    for res in (two_port, center_tap):
        assert res.ok and dc.dc_check(res.ir).ok


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


def _port_noise(ir, f, z0=50.0):
    """Port-voltage noise covariance per kT of an R/L/C IR with coupled inductors, every
    resistor a noise source of 4kT/R and the ports terminated in noiseless z0, and the
    S-matrix of the same circuit."""
    from snp2le.core import mna
    nodes = sorted({n for e in ir.elements for n in e.nodes if n != "0"} | set(ir.ports))
    ni = {n: i for i, n in enumerate(nodes)}
    w = 2 * np.pi * f
    Y = np.zeros((len(nodes), len(nodes)), complex)

    def stamp(ai, bi, aj, bj, y):
        for r, sr in ((ni.get(ai), 1), (ni.get(bi), -1)):
            for c, sc in ((ni.get(aj), 1), (ni.get(bj), -1)):
                if r is not None and c is not None:
                    Y[r, c] += sr * sc * y

    groups, coupled = mna._coupled_groups(ir)
    for e in ir.elements:
        a, b = e.nodes
        if e.kind == "R":
            stamp(a, b, a, b, 1 / e.value)
        elif e.kind == "C":
            stamp(a, b, a, b, 1j * w * e.value)
        elif e.kind == "L" and e.name not in coupled:
            stamp(a, b, a, b, 1 / (1j * w * e.value))
    for gamma, branch in groups:
        for i, (ai, bi) in enumerate(branch):
            for j, (aj, bj) in enumerate(branch):
                stamp(ai, bi, aj, bj, gamma[i, j] / (1j * w))
    for p in ir.ports:
        stamp(p, "0", p, "0", 1 / z0)
    P = [ni[p] for p in ir.ports]
    cov = np.zeros((len(P), len(P)), complex)
    for e in (e for e in ir.elements if e.kind == "R"):     # unit current from a to b
        J = np.zeros(len(nodes), complex)
        for n, s in ((e.nodes[0], -1), (e.nodes[1], 1)):
            if n in ni:
                J[ni[n]] += s
        h = np.linalg.solve(Y, J)[P]
        cov += 4 / e.value * np.outer(h, h.conj())
    S = np.zeros((len(P), len(P)), complex)
    for j, pj in enumerate(P):                     # Norton source of an incident wave of 1
        J = np.zeros(len(nodes), complex)
        J[pj] = 2 / np.sqrt(z0)
        a = np.zeros(len(P))
        a[j] = 1
        S[:, j] = np.linalg.solve(Y, J)[P] / np.sqrt(z0) - a
    return cov, S


@pytest.mark.parametrize("which, kw", [("two_port", None),
                                       ("two_port", dict(substrate="symmetric+coupling")),
                                       ("center_tap", None)])
def test_the_resistors_carry_exactly_the_noise_of_the_loss(which, kw, request):
    """Twiss's theorem, the reason structure models need no thermal-noise option: an RLC
    network with noisy resistors and coupled inductors emits exactly kT (I - S S^H) of its
    own S-parameters.  Below, inside and above the data."""
    res = (request.getfixturevalue(which) if kw is None
           else _convert(IND, "inductor-wideband", **kw))
    assert res.ok and (kw is None or "Rsub12" in res.ngspice)
    for f in (1e8, 1e9, 2e10, 6e10, 3e11):
        cov, S = _port_noise(res.ir, f)
        assert np.max(np.abs(cov - 50 * (np.eye(len(S)) - S @ S.conj().T))) < 1e-12 * 50, f


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
    """A Wilkinson divider is no center-tapped inductor: read with the center tap on port 3,
    its half coils come out negative.  (The detection takes its input port, which sits
    between the two arms like a center tap, and fits a model the panel then names.)"""
    res = _convert("wpd_ihp-sg13g2.s3p", "inductor-ct", basic_model=True, center_tap=3)
    assert not res.ok
    assert "does not look like a center-tapped inductor with the center tap on port 3" in (
        res.error)


# ---------------------------------------------------------------- fit options

def test_a_fixed_segment_count_and_substrate_are_used():
    res = _convert(IND, "inductor-wideband", coil_segments=2)
    assert res.ok and res.metrics["segments"] == 2 and coil_segments(res.ir) == 2
    assert "2 coil segments (set)" in res.messages[0]
    res = _convert(IND, "inductor-wideband", basic_model=True, substrate="asymmetric")
    vals = _values(res)
    assert res.metrics["substrate"] == "asymmetric" and vals["C_ox2"] != vals["C_ox1"]
    assert "asymmetric substrate network (set)" in res.messages[0]


@pytest.mark.parametrize("kw, why", [
    (dict(basic=True, segments=2), "the basic model always has 1 coil segment"),
    (dict(basic=True, substrate="asymmetric+coupling"), "has no substrate coupling"),
    (dict(segments=11), "must be 1 to 10"),
    (dict(substrate="shared"), "must be one of auto"),
    (dict(peak_q_weight=-1.0), "peak-Q weight must be a positive number"),
    (dict(shunt_accuracy=0.0), "shunt accuracy must be a positive number"),
])
def test_an_impossible_option_set_is_refused_with_the_reason(kw, why):
    with pytest.raises(ValueError, match=why):
        fitmod.check_options(2, **kw)


def test_the_center_tapped_model_refuses_coupling_and_a_fourth_port():
    with pytest.raises(ValueError, match="has no substrate coupling"):
        fitmod.check_options(3, substrate="symmetric+coupling")
    with pytest.raises(ValueError, match="center tap port must be 1, 2 or 3"):
        fitmod.check_options(3, center_tap=4)
    res = _convert(IND_CT, "inductor-ct", substrate="asymmetric+coupling")
    assert not res.ok and "has no substrate coupling" in res.error


def test_the_center_tap_may_be_on_any_port(center_tap):
    """The bundled coil with its ports turned round (center tap on port 1): detected, the
    same coil comes out, and the netlist keeps the file's pin order."""
    net = _net(IND_CT)
    order = [2, 0, 1]
    turned = skrf.Network(frequency=net.frequency, s=net.s[:, order][:, :, order], z0=50)
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-ct",
                                        coil_segments=2), turned)
    assert res.ok, res.error
    assert res.metrics["ct_port"] == res.metrics["ct_detected"] == 1
    assert "center tap on port 1 (detected)" in res.messages[0]
    assert "Rct m p1" in res.ngspice and "Cs p2 p3" in res.ngspice
    ref, vals = _values(center_tap), _values(res)
    for lab in ("R_s,h1", "R_s,h2", "C_s", "R_ct", "C_ox1", "C_ox,ct"):
        assert vals[lab] == pytest.approx(ref[lab], rel=1e-2), lab
    # the netlist against the fit's own model, which runs in the order (end, end, tap)
    p = np.array([vals[_row(n, 0.0)[0]] for n in fitmod.CT_PARAM_NAMES])
    Y = fitmod.y_model_ct(p, 2 * np.pi * res.freq, 2)
    back = np.argsort([1, 2, 0])
    S = skrf.network.y2s(Y[:, back][:, :, back], z0=50)
    assert np.max(np.abs(res.model_s - S)) < 1e-9
    assert res.default_plots[2:] == ["L22 / Q22", "S32"]
    assert "L22 / Q22" in res.aux_traces


def test_a_set_center_tap_overrides_the_detection_and_says_so():
    res = _convert(IND_CT, "inductor-ct", basic_model=True, center_tap=1)
    assert res.ok and res.metrics["ct_port"] == 1 and res.metrics["ct_detected"] == 3
    assert "center tap on port 1 (set)" in res.messages[0]
    assert any("port 3 looks like the center tap" in m for m in res.messages)


def test_shunt_accuracy_recovers_the_substrate_from_noisy_data():
    """Volker's test: known element values plus S noise of 1e-3.  Without the floor, the
    fit chases the noise in the tiny low-frequency shunt branch and C_ox lands about 20 to
    30 % off.  With it, C_ox comes back within a few percent."""
    p = dict(Rs=1.9, Ls=0.5e-9, Rskin1=1.6, Lskin1=2e-11, Rskin2=1.0, Lskin2=1e-30,
             Cs=7e-15, Cox1=25e-15, Rsi1=1500.0, Csi1=27e-15, Cox2=25e-15, Rsi2=1500.0,
             Csi2=27e-15, Rsub12=1e15, Csub12=1e-30)
    f = _net(IND).f
    S = skrf.network.y2s(fitmod.y_model(np.array([p[n] for n in fitmod.PARAM_NAMES]),
                                        2 * np.pi * f, 1), z0=50)
    rng = np.random.default_rng(1)
    S = S + 1e-3 * (rng.normal(size=S.shape) + 1j * rng.normal(size=S.shape)) / np.sqrt(2)
    noisy = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="hz"),
                         s=(S + np.transpose(S, (0, 2, 1))) / 2, z0=50)
    err = {k: abs(fitmod.fit_two_port(noisy, basic=True, shunt_accuracy=k).values["Cox1"]
                  / p["Cox1"] - 1) for k in (None, fitmod.DEFAULT_SHUNT_ACCURACY)}
    assert err[0.01] < 0.10 and err[0.01] < 0.5 * err[None], err


def test_peak_q_weight_tightens_q_around_its_peak():
    """On the bundled 500 pH coil the basic model misses Q11 near its peak by about 4 %,
    with the default weight by under 2 %."""
    net = _net(IND)
    w = 2 * np.pi * net.f
    _, q_data = fitmod.l_and_q(net.y[:, 0, 0], w)
    band = q_data >= fitmod.PEAK_Q_LEVEL * q_data.max()

    def peak_error(**kw):
        fit = fitmod.fit_two_port(net, basic=True, **kw)
        p = np.array([fit.values[n] for n in fitmod.PARAM_NAMES])
        _, q = fitmod.l_and_q(fitmod.y_model(p, w, 1)[:, 0, 0], w)
        return np.sqrt(np.mean((q[band] / q_data[band] - 1) ** 2)), fit.messages

    plain, _ = peak_error()
    weighted, msgs = peak_error(peak_q_weight=fitmod.DEFAULT_PEAK_Q_WEIGHT)
    assert weighted < 0.6 * plain, (plain, weighted)
    assert any(m.startswith("peak-Q weight 2: L and Q weighted up to 3x") for m in msgs)


def test_the_inductors_lead_the_dropdown_and_the_defaults_did_not_move():
    """The three inductors come first in the dropdown, and structure mode still opens on
    inductor-pi for a 2-port and on the in-phase Wilkinson for a 3-port: the default skips
    the wideband fits, which take seconds and are picked on purpose."""
    keys = [key for key, _name, _n in structure_items()]
    assert keys[:3] == ["inductor-pi", "inductor-wideband", "inductor-ct"]
    assert {n: default_structure(n) for n in (1, 2, 3, 4)} == {
        1: None, 2: "inductor-pi", 3: "wilkinson-inphase", 4: "balun"}
    assert {k for k, s in STRUCTURES.items() if s.wideband} == {"inductor-wideband",
                                                                 "inductor-ct"}


def test_a_lossy_coil_whose_skin_seed_exceeds_its_bound_still_fits():
    """A 25 ohm, 40 nH coil from 1 MHz seeds L_skin = R_skin/(2 pi f_corner) above the 1 uH
    bound, which least_squares refused as a start outside its bounds ("Initial guess is
    outside of provided bounds").  Clipped into them like the global fit's starts, the fit
    recovers the coil."""
    p = dict(Rs=25.0, Ls=40e-9, Rskin1=7.5, Lskin1=2e-9, Rskin2=1.0, Lskin2=1e-30, Cs=30e-15,
             Cox1=300e-15, Rsi1=500.0, Csi1=400e-15, Cox2=300e-15, Rsi2=500.0, Csi2=400e-15,
             Rsub12=1e15, Csub12=1e-30)
    f = np.geomspace(1e6, 5e9, 201)
    S = skrf.network.y2s(fitmod.y_model(np.array([p[n] for n in fitmod.PARAM_NAMES]),
                                        2 * np.pi * f, 1), z0=50)
    net = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="hz"), s=S, z0=50)
    for basic in (True, False):
        res = engine.convert(ConverterState(mode="structure", structure_key="inductor-wideband",
                                            basic_model=basic), net)
        assert res.ok, res.error
        v = _values(res)
        assert v["R_s"] == pytest.approx(25.0, rel=1e-3)
        assert v["L_s"] == pytest.approx(40e-9, rel=1e-3)


def test_the_messages_name_what_limits_the_fit():
    """A fit range that ends below the self-resonance is named as the limit, not the SRF, and
    a model with no self-resonance either says so instead of quoting an "n/a" SRF."""
    res = _convert(IND, "inductor-wideband", basic_model=True, f_max=3e9)
    assert not res.ok
    assert "up to 3 GHz, the end of the data or fit range" in res.error
    res = _convert(IND, "inductor-wideband", basic_model=True, f_max=5e9)
    assert res.ok and "no self-resonance in the data or in the model" in res.messages
    assert not any("n/a" in m for m in res.messages)


def _spread_variant(names, x, ties=None):
    ties = ties or {}
    return dict(names=names, free=np.array([n not in ties for n in names]), ties=ties, fixed={},
                lower=x - 5, upper=x + 5)


def _spread(names, x, residual, cost=0.0, floor_cost=1e-3, ties=None, lower=None):
    variant = _spread_variant(names, x, ties)
    return fitmod._spread_warnings(variant, x, x - 5 if lower is None else lower, x + 5, residual,
                                   cost, floor_cost, 60e9)


def test_an_element_the_data_does_not_constrain_is_named():
    """Each element named comes with a witness: a model with it moved by the factor and the
    others re-fitted, within the cost limit.  A flat direction reaches the top of the ladder."""
    names = ["Ls", "Rskin2", "Lskin2"]
    x = np.array([-9.0, 2.0, -11.0])                # skin corner 100 / (2 pi 1e-11) = 1.6 THz

    def flat_in_rskin2(x):                          # 0.1 is the fit's own error, cost 0.005
        return np.array([10 * (x[0] + 9.0), 10 * (x[2] + 11.0), 0.1])

    assert _spread(names, x, flat_in_rskin2, cost=0.005) == [
        "Rskin2 (x1000) is not determined by the data, it can change by that factor or more "
        "while the fit's RMS error grows by 0.5 % or less (skin section 2 has its corner above "
        "the fit band, where it acts as plain L, and Basic model leaves section 2 out)"]
    assert _spread(names, x, lambda x: np.append(10 * (x - np.array([-9.0, 2.0, -11.0])), 0.1),
                   cost=0.005) == []
    # an element at a bound is _bound_warnings' to report
    assert _spread(names, x, flat_in_rskin2, cost=0.005, lower=x - np.array([5, 0, 5])) == []
    msgs = _spread(["Cox1", "Cox2"], np.zeros(2), lambda x: np.array([0.1]), cost=0.005,
                   ties={"Cox2": "Cox1"})
    assert msgs[0].startswith("Cox1 = Cox2 (x1000) is not determined by the data")


def test_a_near_perfect_fit_is_judged_against_the_floor():
    """Below the floor a relative 0.5 % of a vanishing error would say nothing, so the message
    states the absolute bound instead (on synthetic data from the model itself)."""
    names = ["Ls", "Rskin2", "Lskin2"]
    x = np.array([-9.0, 2.0, -11.0])
    msgs = _spread(names, x, lambda x: 10 * np.array([x[0] + 9.0, x[2] + 11.0]), cost=0.0)
    assert msgs[0].startswith("Rskin2 (x1000) is not determined by the data, it can change by "
                              "that factor or more while the fit stays as close to the data as "
                              "a uniform relative error of 0.0001 (skin section 2")


def test_the_spread_follows_the_cost_not_the_curvature():
    """A cost that saturates (a skin R far above its corner) was missed by the curvature at
    the fit, which put the bundled coil's R_skin2 at x1.65 while a re-fit at 100 x cost 0.6 %
    more.  And a direction the curvature calls flat but the cost is not must not be named."""
    x = np.array([-9.0, 2.0])

    def saturating(x):                       # 0 at x[1] = 2, approaches 0.011 as x[1] grows
        return np.array([10 * (x[0] + 9.0), 0.022 * (1 / (1 + 10 ** (x[1] - 2)) - 0.5), 0.1])

    assert _spread(["A", "B"], x, saturating, cost=0.005)[0].startswith(
        "B (x10) is not determined")

    def quartic(x):                          # flat at the fit, steep 0.48 decades away
        return np.array([10 * (x[0] + 9.0), 1e-4 * (x[1] - 2), 100 * (x[1] - 2) ** 2, 0.1])

    assert _spread(["A", "B"], x, quartic, cost=0.005) == []


def test_a_flat_direction_elsewhere_does_not_hide_a_free_element():
    """Near a flat direction of the others (P + Q here) the linear guess moves them hundreds
    of decades, the start then costs more than the element moved alone, and a free element
    went unnamed in 10 of 16 noisy synthetic fits.  The search now starts from the cheaper
    of the two and steps only where the others are determined."""
    x = np.zeros(3)

    def coupled(x):
        k, p, q = x
        return np.array([0.002 * k, 1e3 * (p - q), 1e-6 * (p + q) + 1e-3 * k, 1e-2 * p ** 2,
                         1e-2 * q ** 2, 0.1])

    assert _spread(["K", "P", "Q"], x, coupled, cost=0.005)[0].startswith("K (x1000)")


def test_the_cost_floor_does_not_grow_with_the_number_of_points():
    """Each goal's residual is divided by the root of its point count, so the floor is the cost
    of one relative error on every point of every goal (it grew with the points before)."""
    costs = []
    for n in (10, 1000):
        meas = {"Y": np.linspace(1, 2, n) + 1j, "L": np.linspace(1, 2, n)}
        goals = fitmod._make_goals(meas, [("Y", 1.0, np.ones(n, bool)),
                                          ("L", 0.5, np.ones(n, bool))])
        costs.append(fitmod._uniform_error_cost(goals, 1e-3))
    assert costs[0] == pytest.approx(costs[1], rel=1e-12)
    assert costs[0] == pytest.approx(0.5 * 1e-6 * (1.0 + 0.25), rel=1e-12)


def test_tied_half_coils_keep_one_skin_section_order():
    """With the half inductances tied and the resistances free, the two halves could sort
    their skin sections differently, and the tie then paired section 1 with section 2."""
    names = fitmod.CT_PARAM_NAMES
    x = np.zeros(len(names))
    for h, r1, r2 in (("_h1", 1.0, 0.0), ("_h2", 0.0, 1.0)):   # corners in opposite orders
        x[names.index("Rskin1" + h)], x[names.index("Rskin2" + h)] = r1, r2
        x[names.index("Lskin1" + h)], x[names.index("Lskin2" + h)] = -10.9, -11.0
    ties = {n + "_h2": n + "_h1" for n in ("Ls", "Lskin1", "Lskin2")}
    fitmod._sort_half_coil_skin_sections(names, (x,), ties)
    for n in ("Lskin1", "Lskin2"):
        assert x[names.index(n + "_h1")] == x[names.index(n + "_h2")], n


def test_the_center_tapped_fit_names_its_undetermined_skin_sections(center_tap):
    """Its second skin sections have their corners above the band, so their R is free: a
    1e-12 change of the data moved R_skin2 by 75 % and L_skin2 by 41 % (2026-10-18).  The
    elements the data determines stay unnamed, on any numpy, since the flat direction is
    flat wherever the fit stops along it."""
    import re
    msg = [m for m in center_tap.messages if "not determined by the data, each can change" in m]
    assert len(msg) == 1
    named = {n for pair in re.findall(r"(\w+)(?: = (\w+))? \(x", msg[0]) for n in pair if n}
    assert {"Rskin2_h1", "Rskin2_h2"} <= named
    assert not named & {"Rs_h1", "Rs_h2", "Cs", "Rct", "Cox1", "Cox2", "Coxct", "Rsi1", "Rsi2",
                        "Rsict", "Csi1", "Csi2", "Csict"}
    assert "skin section 2 has its corner above the fit band" in msg[0]


def test_the_two_port_fit_names_only_its_free_skin_resistance(two_port):
    """The bundled coil's second skin corner (66 GHz) lies above its 50 GHz band."""
    msg = [m for m in two_port.messages if "can change by that factor" in m]
    assert len(msg) == 1 and msg[0].startswith("Rskin2 (x")
    assert "skin section 2 has its corner above the fit band" in msg[0]
    basic = _convert(IND, "inductor-wideband", basic_model=True)
    assert not any("can change by that factor" in m for m in basic.messages)


def test_a_wideband_conversion_never_reports_a_blank_stage():
    """The engine's tolerance stage is not in the wideband plan, entering it reported an
    empty message near the end of every fit."""
    trace = []
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-wideband",
                                        basic_model=True), _net(IND),
                         progress=lambda frac, msg: trace.append((frac, msg)))
    assert res.ok and trace
    assert all(msg for _frac, msg in trace), [t for t in trace if not t[1]]


def test_a_capacitor_is_refused_with_a_reason():
    """The MOM capacitor is capacitive at every point, so there is no coil to fit.  It used to
    fail with scipy's own "Initial guess is outside of provided bounds"."""
    for basic in (False, True):
        res = _convert("mom_cap_74fF_02_ihp-sg13cmos5l.s2p", "inductor-wideband",
                       basic_model=basic)
        assert not res.ok
        assert res.error == ("the input is not inductive anywhere in the fit band, this does "
                             "not look like an on-chip inductor")


def test_the_cli_says_what_a_wideband_structure_ignores(tmp_path, capsys):
    """--fext and --tolerances mean nothing to a model fitted over the band, a wideband
    option without --mode structure names the missing mode, and the center-tapped summary
    counts segments per half."""
    from snp2le import cli
    out = str(tmp_path / "ind.spice")
    assert cli.main(["convert", os.path.join(EXAMPLES, IND), "--mode", "structure",
                     "--structure", "inductor-wideband", "--basic", "--fext", "5GHz",
                     "--tolerances", "-o", out]) == 0
    got = capsys.readouterr()
    assert ("--fext, --tolerances ignored, the wideband inductors are fitted over the band"
            in got.err)
    assert "tolerances" not in got.out                    # the warning says it all
    assert cli.main(["convert", os.path.join(EXAMPLES, IND), "--structure",
                     "inductor-wideband", "--basic", "-o", out]) == 0
    assert "--basic ignored, it needs --mode structure" in capsys.readouterr().err
    assert cli.main(["convert", os.path.join(EXAMPLES, IND_CT), "--mode", "structure",
                     "--structure", "inductor-ct", "--basic", "-o", out]) == 0
    assert "1 segment per half" in capsys.readouterr().out


def test_the_coupled_stamp_and_the_chunked_grid_give_the_same_bits():
    """The coupled half coils were stamped with einsum("ib,fbc,jc->fij"), which visited every
    node and branch pair and took 97 % of a 10-segment center-tap model (288 s and 1.9 GB for
    `--segments 10`).  The direct stamp must give the same bits, so no fit moves, and so must
    the dense SRF grid evaluated in chunks."""
    rng = np.random.default_rng(0)
    for n in (1, 3, 10):
        branches = [(b, b + 1) for b in range(2 * n)]
        L = rng.normal(size=(2 * n, 2 * n))
        w = rng.uniform(1e9, 1e11, 7)
        Zb = 1j * w[:, None, None] * (L @ L.T + 2 * n * np.eye(2 * n)) * 1e-10 + np.eye(2 * n)
        M = rng.normal(size=(7, 4 * n + 3, 4 * n + 3)) * (1 + 1j)
        A = np.zeros((M.shape[1], len(branches)))
        for b, (n1, n2) in enumerate(branches):
            A[n1, b], A[n2, b] = 1.0, -1.0
        ref = M + np.einsum("ib,fbc,jc->fij", A, np.linalg.inv(Zb), A)
        fitmod._stamp_coupled(M, branches, Zb)
        assert np.array_equal(M.view(np.uint64), ref.view(np.uint64)), n
    def params(names):                     # 2 ohm, 0.1 nH, 10 fF and k = 0.4 throughout
        return np.array([0.4 if name == "k" else 1e-10 if name[0] == "L"
                         else 1e-14 if name[0] == "C" else 2.0 for name in names])
    w = 2 * np.pi * np.linspace(1e7, 9e10, 2 * fitmod.GRID_CHUNK + 123)
    for model, p in ((fitmod.y_model_ct, params(fitmod.CT_PARAM_NAMES)),
                     (fitmod.y_model, params(fitmod.PARAM_NAMES))):
        whole, chunked = model(p, w, 3), fitmod._on_grid(model, p, w, 3)
        assert np.array_equal(whole.view(np.uint64), chunked.view(np.uint64))
