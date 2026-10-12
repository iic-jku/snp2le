# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_fit_dc.py - the 0 Hz point of a universal fit (no Qt).

A file can carry a 0 Hz sample, which the fit drops by default and extrapolates to.  Passivity
enforcement tries a refit that includes it when residue perturbation cannot reach the ceiling,
since that refit's constant term is pinned to the DC point instead of free to run past 1.
`fit_dc` fits the 0 Hz point every time, which gives the exact DC point, a coil's DC
resistance included, at some in-band accuracy.  Run with:  pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                   # noqa: E402
import skrf                                          # noqa: E402

from snp2le.core import io, engine                   # noqa: E402
from snp2le.core.state import ConverterState         # noqa: E402

_EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "snp2le", "examples")
_COIL = "ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p"      # starts at 0 Hz


def _example(name):
    return io.load_touchstone(os.path.join(_EXAMPLES, name))


def _with_dc_point(net):
    """`net` with a 0 Hz point taken from its lowest sample, the S-parameters made real, as
    an EM solver's extrapolated DC point would be."""
    f = np.concatenate(([0.0], net.f))
    s = np.concatenate((np.real(net.s[:1]), net.s))
    return skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"), s=s, z0=net.z0[0, 0])


def _r_dc(s, z0=50.0):
    """Series resistance between ports 1 and 2 from a 2-port's S-matrix at 0 Hz."""
    y = (np.eye(2) - s) @ np.linalg.inv(np.eye(2) + s) / z0
    return -1.0 / y[0, 1].real


def _convert(net, **kw):
    return engine.convert(ConverterState(mode="universal", **kw), net)


def test_a_refit_with_the_dc_point_rescues_a_runaway_constant_term():
    """The 500 pH coil at order 6 stays near-passive: its constant term D sits at 2.18,
    residue perturbation cannot move it, and the lower-order refit misses too.  Given a
    0 Hz point, enforcement also tries a refit that includes it, whose D is pinned to the
    DC point, and that one comes out strictly passive."""
    net = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    plain = _convert(net, max_order=6)
    assert plain.passivity_path == "near-passive" and not plain.passive
    res = _convert(_with_dc_point(net), max_order=6)
    assert res.ok and res.passive and res.passivity_path == "dc refit"
    assert res.sigma_max <= 1.0
    assert any("refit with the 0 Hz point" in m for m in res.messages)


def test_the_refit_with_the_dc_point_only_runs_where_it_can_help():
    """A file whose fit perturbs to passivity never sees it, so its result is the one it
    always had, and a fit range that starts above 0 Hz leaves no DC point to refit with."""
    net = _with_dc_point(_example("wpd_ihp-sg13g2.s3p"))
    res = _convert(net, max_order=6)
    assert res.passivity_path == "perturbed"
    assert res.ngspice == _convert(io.without_dc(net), max_order=6).ngspice
    coil = _with_dc_point(_example("ind_500pH_ihp-sg13cmos5l.s2p"))
    above = _convert(coil, max_order=6, f_min=1e9)
    assert above.passivity_path == "near-passive"


def test_a_dc_point_above_passivity_is_made_passive():
    """An extrapolated DC point can come out a hair above passivity, and a fit that includes
    it would inherit a negative DC conductance.  Singular values above 1 are clipped, the
    ones below stay, so a coil's DC resistance keeps its value."""
    net = _example(_COIL)
    u, sv, vh = np.linalg.svd(net.s[0])
    hot = net.copy()
    hot.s[0] = u @ np.diag(sv * [1.0 + 1e-5, 1.0]) @ vh
    fixed, before = io.passive_dc(hot)
    after = np.linalg.svd(fixed.s[0], compute_uv=False)
    assert before > 1.0 and after[0] <= 1.0 + 1e-12
    assert abs(after[1] - sv[1]) < 1e-12
    assert hot.s[0] is not fixed.s[0]                  # the caller's network is untouched
    plain, nan = io.passive_dc(_example("bpf_ihp-sg13g2.s2p"))
    assert nan != nan and plain.f[0] > 0


def test_fitting_the_dc_point_gives_the_exact_dc_resistance():
    """Dropped, the 0 Hz point is extrapolated and the coil's DC resistance comes out off.
    Fitted, the model meets the DC point to rounding."""
    net = _example(_COIL)
    r_dc = _r_dc(net.s[0])
    fitted = _convert(net, max_order=10, enforce_passivity=False, fit_dc=True)
    assert fitted.ok and fitted.freq[0] == 0
    assert np.max(np.abs(fitted.model_s[0] - fitted.data_s[0])) < 1e-9
    assert abs(_r_dc(fitted.model_s[0]) / r_dc - 1) < 1e-9
    dropped = _convert(net, max_order=10, enforce_passivity=False)
    assert dropped.freq[0] > 0
    assert not any("0 Hz point" in m for m in fitted.messages)


def test_enforcement_that_moves_the_fitted_dc_point_says_so():
    net = _example(_COIL)
    res = _convert(net, max_order=10, fit_dc=True)
    assert res.ok and res.passive
    moved = float(np.max(np.abs(res.model_s[0] - res.data_s[0])))
    lines = [m for m in res.messages if "0 Hz point is" in m]
    assert moved > 1e-6 and len(lines) == 1 and "passivity enforcement" in lines[0]


def test_a_dc_point_above_passivity_is_reported_when_fitted():
    """The bundled line's 0 Hz point sits at sigma 1.0001, a hair above passivity."""
    res = _convert(_example("tline_100um_ihp-sg13g2.s2p"), max_order=6,
                   enforce_passivity=False, fit_dc=True)
    assert any("was made passive before the fit" in m for m in res.messages)
    assert np.linalg.svd(res.data_s[0], compute_uv=False)[0] <= 1.0 + 1e-12


def test_asking_for_the_dc_point_without_one_changes_nothing_but_a_note():
    net = _example("bpf_ihp-sg13g2.s2p")
    plain = _convert(net, max_order=6)
    asked = _convert(net, max_order=6, fit_dc=True)
    assert asked.ngspice == plain.ngspice and asked.vacask == plain.vacask
    assert len(asked.messages) == len(plain.messages) + 1
    assert "has none" in asked.messages[0]
    coil = _example(_COIL)
    above = _convert(coil, max_order=6, fit_dc=True, f_min=1e9)
    assert above.freq[0] >= 1e9 and any("has none" in m for m in above.messages)


def test_structure_mode_drops_the_dc_point_regardless():
    net = _example(_COIL)
    kw = dict(mode="structure", structure_key="inductor-pi")
    plain = engine.convert(ConverterState(**kw), net)
    asked = engine.convert(ConverterState(fit_dc=True, **kw), net)
    assert plain.ok and asked.ngspice == plain.ngspice and asked.freq[0] > 0


def test_the_option_survives_a_design_round_trip():
    assert ConverterState.from_json(ConverterState(fit_dc=True).to_json()).fit_dc is True
    assert ConverterState.from_json('{"mode": "universal"}').fit_dc is False


def test_cli_fit_dc_flags(tmp_path, capsys):
    from snp2le import cli
    p = cli.build_parser()
    assert p.parse_args(["convert", "x.s2p"]).fit_dc is False
    assert p.parse_args(["convert", "x.s2p", "--fit-dc"]).fit_dc is True
    assert p.parse_args(["convert", "x.s2p", "--fit-dc", "--no-fit-dc"]).fit_dc is False
    src = os.path.join(_EXAMPLES, _COIL)
    out = tmp_path / "coil.spice"
    assert cli.main(["convert", src, "--order", "10", "--no-passive", "--fit-dc",
                     "-o", str(out), "--quiet"]) == 0
    assert out.exists()
    assert cli.main(["convert", src, "--mode", "structure", "--fit-dc",
                     "-o", str(tmp_path / "pi.spice"), "--quiet"]) == 0
    assert "--fit-dc is ignored in structure mode" in capsys.readouterr().err
