# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_dc_point.py - the 0 Hz point of a universal fit (no Qt).

A file can carry a 0 Hz sample, which the fit drops and extrapolates to.  Passivity
enforcement tries a refit that includes it when residue perturbation cannot reach the ceiling,
as one more candidate next to the lower-order refit.  The DC pin (dcpin.py) then makes the
model meet the sample exactly.  The pin checks solve the emitted circuit itself, at 0 Hz and
in the band, so a sign or a node gone wrong in the netlist fails here.  Run with:  pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                   # noqa: E402
import skrf                                          # noqa: E402

from snp2le.core import io, engine, dcpin, universal  # noqa: E402
from snp2le.core.state import ConverterState         # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_noise import _port_noise                   # noqa: E402

_EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "snp2le", "examples")


def _example(name):
    return io.load_touchstone(os.path.join(_EXAMPLES, name))


def _with_dc_point(net):
    """`net` with a 0 Hz point taken from its lowest sample, the S-parameters made real, as
    an EM solver's extrapolated DC point would be."""
    f = np.concatenate(([0.0], net.f))
    s = np.concatenate((np.real(net.s[:1]), net.s))
    return skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"), s=s, z0=net.z0[0, 0])


def _with_series_dc(net, r):
    """`net` with the exact 0 Hz point of a series resistor `r` between its two 50 ohm
    ports, whose common mode is open, a singular value of exactly 1."""
    a = r / (r + 100.0)
    s0 = np.array([[[a, 1.0 - a], [1.0 - a, a]]])
    f = np.concatenate(([0.0], net.f))
    return skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"),
                        s=np.concatenate((s0, net.s)), z0=50.0)


def _convert(net, **kw):
    return engine.convert(ConverterState(mode="universal", **kw), net)


# The ladder without the convex refit, whose 0 Hz refit these tests are about.  The convex
# refit runs first and often wins (test_convex_passivity.py), and without it, above its state
# limit, the refit below is what is left.
_OLD = dict(convex_max_states=0)


def _r_dc(s, z0=50.0):
    """Resistance between the two ports of a 2-port at DC, from its S-matrix."""
    y = (np.eye(2) - s) @ np.linalg.inv(np.eye(2) + s) / z0
    return float(-1.0 / np.real(y[0, 1]))


_COIL = "ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p"             # starts at 0 Hz


def test_a_refit_with_the_dc_point_rescues_a_runaway_constant_term():
    """Without the convex refit, the 500 pH coil at order 6 stays near-passive: its constant
    term D sits at 2.18, residue perturbation cannot move it, and the lower-order refit misses
    too.  Given a 0 Hz point, enforcement also tries a refit that includes it, which lands on
    another model, and that one comes out strictly passive."""
    net = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    plain = _convert(net, max_order=6, **_OLD)
    assert plain.passivity_path == "near-passive" and not plain.passive
    res = _convert(_with_dc_point(net), max_order=6, **_OLD)
    assert res.ok and res.passive and res.passivity_path == "dc refit"
    assert res.sigma_max <= 1.0
    assert any("refit with the 0 Hz point" in m for m in res.messages)
    assert not any("not needed" in m for m in res.messages)


def test_the_refit_with_the_dc_point_only_runs_where_it_can_help():
    """A file whose fit perturbs to passivity never sees it, so its result is the one it
    always had, and a fit range that starts above 0 Hz leaves no DC point to refit with."""
    net = _with_dc_point(_example("wpd_ihp-sg13g2.s3p"))
    res = _convert(net, max_order=6, **_OLD)
    assert res.passivity_path == "perturbed"
    assert res.ngspice == _convert(io.without_dc(net), max_order=6, **_OLD).ngspice
    coil = _with_dc_point(_example("ind_500pH_ihp-sg13cmos5l.s2p"))
    above = _convert(coil, max_order=6, f_min=1e9, **_OLD)
    assert above.passivity_path == "near-passive"


def test_a_dc_point_above_passivity_is_made_passive():
    """An extrapolated DC point can come out a hair above passivity, and a fit that includes
    it would inherit a negative DC conductance.  Singular values above 1 are clipped, the
    ones below stay, so a coil's DC resistance keeps its value."""
    net = _example("ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p")
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


def test_a_dc_point_that_is_not_finite_is_ignored():
    """A 0 Hz row of NaN is dropped like any 0 Hz row and never refitted, so the result is
    the one the file gives without it."""
    net = _example("ind_500pH_ihp-sg13cmos5l.s2p")
    bad = _with_dc_point(net)
    bad.s[0] = np.nan
    same, nan = io.passive_dc(bad)
    assert same is bad and nan != nan
    res = _convert(bad, max_order=6, **_OLD)
    assert res.ok and res.passivity_path == "near-passive"
    assert res.ngspice == _convert(net, max_order=6, **_OLD).ngspice


def test_the_refit_stays_strictly_passive_so_it_can_carry_noise():
    """A coil's exact 0 Hz point has an open common mode, a singular value of exactly 1.  A
    refit that met it would be passive but not strictly, with no thermal noise, so the refit
    gets the point 1e-6 below it."""
    coil = _with_series_dc(_example("ind_500pH_ihp-sg13cmos5l.s2p"), 0.5)
    res = _convert(coil, max_order=6, thermal_noise=True, **_OLD)
    assert res.passivity_path == "dc refit" and res.passive
    assert res.noise.ok, res.noise.message


def test_the_pin_gives_the_coil_its_dc_resistance():
    """The bundled coil's file reads 1.0964 ohm at 0 Hz, its fit at order 13 1.29 ohm.  The
    pinned netlist, solved as a circuit, reads the file's value, to the 5e-9 the clip below
    sigma 1 adds through the common mode."""
    net = _example(_COIL)
    want = _r_dc(np.real(net.s[0]))
    res = _convert(net, max_order=13)
    assert res.dc_pin.ok and res.dc_pin.n_sources == 6, res.dc_pin.message
    assert abs(_r_dc(np.real(_port_noise(res.ir, 0.0)[1])) / want - 1.0) < 1e-7
    plain = _convert(net, max_order=13, dc_pin=False)
    assert plain.dc_pin is None
    assert _r_dc(np.real(_port_noise(plain.ir, 0.0)[1])) > 1.15 * want
    assert any(m.startswith("DC pinned to the file's 0 Hz point") for m in res.messages)


def test_the_pin_leaves_the_band_and_the_noise_alone():
    """In the band the pinned netlist is the fit to 1e-7, the overlay shows the netlist,
    the noise generator and the passivity result are those of the fit, and the netlist is
    the unpinned one plus the pin's lines."""
    net = _example(_COIL)
    on = _convert(net, max_order=13, thermal_noise=True)
    off = _convert(net, max_order=13, thermal_noise=True, dc_pin=False)
    assert on.dc_pin.ok and on.noise.ok and off.noise.ok and on.passive == off.passive
    assert np.max(np.abs(on.model_s - off.model_s)) == on.dc_pin.rf_change < 1e-7
    for k in (0, len(on.freq) // 2, len(on.freq) - 1):
        circuit = _port_noise(on.ir, on.freq[k])[1]
        assert np.max(np.abs(circuit - on.model_s[k])) < 1e-9
    for a, b in ((on.ngspice, off.ngspice), (on.vacask, off.vacask)):
        added = [ln for ln in a.splitlines() if ln not in set(b.splitlines())]
        assert [ln for ln in a.splitlines() if ln not in added] == b.splitlines()
        assert added and all("dcp" in ln for ln in added)
    assert "Rdcp_1 dcp_d1 0 1.0 noisy=0" in on.ngspice
    assert "Gdcp_v1 (GND dcp_d1 p1 GND) vccs gain=1e-06" in on.vacask


def test_the_pin_only_acts_on_a_universal_fit_of_a_file_with_a_0_hz_point():
    bpf = _example("bpf_ihp-sg13g2.s2p")
    res = _convert(bpf, max_order=6)
    assert res.dc_pin is None and res.ngspice == _convert(bpf, max_order=6, dc_pin=False).ngspice
    st = ConverterState(mode="structure", structure_key="inductor-pi")
    assert engine.convert(st, _example(_COIL)).dc_pin is None
    bad = _with_dc_point(_example("ind_500pH_ihp-sg13cmos5l.s2p"))
    bad.s[0] = np.nan
    assert _convert(bad, max_order=13).dc_pin is None


def test_the_pin_uses_the_0_hz_point_below_a_fit_range():
    """A fit range above the file's first sample still has the file's 0 Hz point to pin to."""
    net = _example(_COIL)
    res = _convert(net, max_order=13, f_min=float(net.f[5]))
    assert res.band_limited and res.dc_pin.ok
    assert abs(_r_dc(np.real(_port_noise(res.ir, 0.0)[1])) / _r_dc(np.real(net.s[0])) - 1) < 1e-7


def test_a_pin_that_would_make_the_dc_point_singular_comes_back_out():
    """The WPD fitted at order 6 with a 0 Hz point prepended nearly shorts a mode at DC, 566 S,
    which the pin would have to cancel.  That leaves the DC matrix singular, so the netlist
    stays the fit's."""
    net = _with_dc_point(_example("wpd_ihp-sg13g2.s3p"))
    res = _convert(net, max_order=6)
    assert not res.dc_pin.ok and "singular" in res.dc_pin.message
    assert res.dc_pin.n_sources == 0
    assert res.dc.ok and res.ngspice == _convert(net, max_order=6, dc_pin=False).ngspice


def test_the_island_leak_reaches_only_the_floating_mode():
    """The coil's common mode has no DC path.  Without a leak it keeps 1e-8 S, the clip of
    the file's point below sigma 1, and with one it gets that conductance on top.  The DC
    resistance stays."""
    net = _example(_COIL)
    want = _r_dc(np.real(net.s[0]))
    g_file = np.linalg.eigvalsh(dcpin.dc_target(net.s[0], np.full(2, 50.0))[0])[0]
    assert abs(g_file / 1e-8 - 1.0) < 1e-3
    for leak in (0.0, 1e-6):
        g_cm = g_file + leak
        res = _convert(net, max_order=13, dc_island_leak=leak)
        assert res.dc_pin.ok and res.dc_pin.n_islands == 1
        s = np.real(_port_noise(res.ir, 0.0)[1])
        y = (np.eye(2) - s) @ np.linalg.inv(np.eye(2) + s) / 50.0
        assert abs(np.linalg.eigvalsh(0.5 * (y + y.T))[0] / g_cm - 1.0) < 1e-3
        assert abs(_r_dc(s) / want - 1.0) < 1e-5


def test_a_bad_setting_skips_the_pin():
    """The skip names the setting at fault, also for a leak that is no number, which used to
    be blamed on the corner.  A design file is checked when it loads, a ConverterState built
    in code is not."""
    net = _example(_COIL)
    for kw, why in (({"dc_pin_fc": 0.0}, "corner frequency"), ({"dc_pin_fc": "fast"}, "corner"),
                    ({"dc_island_leak": -1.0}, "leak"), ({"dc_island_leak": "x"}, "leak"),
                    ({"dc_pin_fc": 10 ** 400}, "corner"),
                    ({"dc_island_leak": 10 ** 400}, "leak")):
        res = _convert(net, max_order=13, **kw)
        assert res.ok and not res.dc_pin.ok, res.dc_pin.message
        assert res.dc_pin.message.startswith(f"DC pin skipped: the {why}"), res.dc_pin.message
        assert "dcp" not in res.ngspice


def test_the_message_names_a_corner_or_leak_away_from_the_default():
    """The window has no control for them, so a loaded design that sets them is named in the
    pin's message, whatever the pin did, in ASCII like every core message."""
    net = _example(_COIL)
    for kw in ({}, {"dc_pin_fc": 160, "dc_island_leak": 0}):        # the defaults, also as ints
        assert "Non-default" not in _convert(net, max_order=13, **kw).dc_pin.message
    res = _convert(net, max_order=13, dc_pin_fc=1e3, dc_island_leak=1e-6)
    assert res.dc_pin.ok and res.dc_pin.message in res.messages
    assert res.dc_pin.message.endswith(". Non-default settings: corner 1 kHz (default 160 Hz), "
                                       "island leak 1e-06 S (default 0 S)")
    nan = _convert(net, max_order=13, dc_pin_fc=float("nan")).dc_pin
    assert not nan.ok and nan.message.endswith("Non-default settings: corner nan Hz "
                                               "(default 160 Hz)")
    hand = _convert(net, max_order=13, dc_island_leak="x").dc_pin
    assert hand.message.endswith("Non-default settings: island leak 'x' (default 0 S)")
    huge = _convert(net, max_order=13, dc_pin_fc=10 ** 400).dc_pin  # an int beyond any float
    assert huge.message.endswith("Non-default settings: corner inf Hz (default 160 Hz)")
    wpd = _convert(_with_dc_point(_example("wpd_ihp-sg13g2.s3p")), max_order=6,
                   dc_pin_fc=1e3).dc_pin
    assert "singular" in wpd.message and wpd.message.endswith("corner 1 kHz (default 160 Hz)")
    assert all(p.message.isascii() for p in (res.dc_pin, nan, hand, wpd))


def test_the_pin_matches_its_closed_form():
    """pinned_sparams is Y_fit + dY / (1 + jf/fc) written without (I + S)^-1."""
    rng = np.random.default_rng(1)
    s = 0.3 * (rng.standard_normal((4, 3, 3)) + 1j * rng.standard_normal((4, 3, 3)))
    dy = rng.standard_normal((3, 3)) * 0.01
    f = np.array([0.0, 50.0, 1e3, 1e9])
    got = dcpin.pinned_sparams(s, f, dy, np.full(3, 50.0), 160.0)
    for k in range(len(f)):
        y = (np.eye(3) - s[k]) @ np.linalg.inv(np.eye(3) + s[k]) / 50.0
        y = y + dy / (1.0 + 1j * f[k] / 160.0)
        want = np.linalg.solve(np.eye(3) + 50.0 * y, np.eye(3) - 50.0 * y)
        assert np.max(np.abs(got[k] - want)) < 1e-12


def test_the_pin_options_survive_a_design_round_trip():
    st = ConverterState(dc_pin=False, dc_pin_fc=1e3, dc_island_leak=1e-6)
    back = ConverterState.from_json(st.to_json())
    assert (back.dc_pin, back.dc_pin_fc, back.dc_island_leak) == (False, 1e3, 1e-6)
    # a design saved before the pin existed opens with it on, at its defaults
    old = ConverterState.from_json('{"mode": "universal"}')
    assert (old.dc_pin, old.dc_pin_fc, old.dc_island_leak) == (True, 160.0, 0.0)


def test_a_design_file_holds_its_pin_values_to_numbers():
    """null means the default, as in a tick-box field.  true would read as 1 (a 1 Hz corner, a
    1 S leak), so anything that is no number refuses the design.  A number out of range loads
    and skips the pin with a note at conversion."""
    import pytest
    st = ConverterState.from_json('{"dc_pin_fc": null, "dc_island_leak": null}')
    assert (st.dc_pin_fc, st.dc_island_leak) == (160.0, 0.0)
    for field in ("dc_pin_fc", "dc_island_leak"):
        for bad in ("true", "false", '"fast"', "[1]", "{}"):
            with pytest.raises(ValueError, match=f"{field} must be a number"):
                ConverterState.from_json(f'{{"{field}": {bad}}}')
    with pytest.raises(ValueError, match="got true$"):        # as written in the file
        ConverterState.from_json('{"dc_pin_fc": true}')
    st = ConverterState.from_json('{"dc_pin_fc": 0, "dc_island_leak": 1e-6}')
    assert (st.dc_pin_fc, st.dc_island_leak) == (0, 1e-6)


def test_cli_dc_pin_flags(capsys):
    import pytest
    from snp2le import cli
    p = cli.build_parser()
    a = p.parse_args(["convert", "x.s2p"])
    assert (a.dc_pin, a.dc_pin_fc, a.dc_island_leak) == (None, None, None)
    assert p.parse_args(["convert", "x.s2p", "--no-dc-pin"]).dc_pin is False
    assert p.parse_args(["convert", "x.s2p", "--dc-pin-fc", "1kHz"]).dc_pin_fc == 1e3
    assert p.parse_args(["convert", "x.s2p", "--dc-island-leak", "1e-6"]).dc_island_leak == 1e-6
    for bad in (["--dc-pin-fc", "0"], ["--dc-island-leak", "-1"], ["--dc-island-leak", "inf"]):
        with pytest.raises(SystemExit):
            p.parse_args(["convert", "x.s2p", *bad])
    capsys.readouterr()


def test_cli_writes_the_pinned_netlist(tmp_path, capsys):
    from snp2le import cli
    src = os.path.join(_EXAMPLES, _COIL)
    out = tmp_path / "coil.spice"
    assert cli.main(["convert", src, "--order", "13", "-o", str(out), "--no-progress"]) == 0
    assert "Gdcp_y1_2" in out.read_text() and "dc_pinned" in capsys.readouterr().out
    assert cli.main(["convert", src, "--order", "13", "--dc-pin-fc", "1kHz", "-o", str(out),
                     "--no-progress"]) == 0
    assert "Non-default settings: corner 1 kHz (default 160 Hz)" in capsys.readouterr().out
    assert cli.main(["convert", src, "--order", "13", "--no-dc-pin", "-o", str(out),
                     "--quiet"]) == 0
    assert "dcp" not in out.read_text()
    assert cli.main(["convert", src, "--mode", "structure", "--dc-pin-fc", "1k", "-o",
                     str(tmp_path / "s.spice"), "--quiet"]) == 0
    assert "--dc-pin-fc ignored in structure mode" in capsys.readouterr().err


def test_with_thermal_noise_a_strictly_passive_candidate_wins(monkeypatch):
    """At a raised ceiling the refit with the 0 Hz point can land just above sigma 1, where
    it cannot carry thermal noise, while the lower-order refit is strictly passive (two ORCA
    coils at ceiling 1.05).  With thermal noise asked for, the strictly passive one wins.
    No bundled file has both candidates, so the perturbation is made to fail, both refits
    to pass, and the one with the 0 Hz point to be the closer but not strictly passive."""
    net = _example(_COIL)
    band = io.without_dc(net)
    dc_net = io.passive_dc(net, ceiling=dcpin.DC_SIGMA)[0]
    vf0 = universal._auto_fit(band, 10)

    def with_dc(vf):
        return vf.network.f[0] == 0

    def fail(*a, **k):
        raise RuntimeError("no perturbation")
    monkeypatch.setattr(universal, "_meets_ceiling", lambda vf, s, c: vf is not vf0)
    monkeypatch.setattr(universal, "_enforce_at", fail)
    monkeypatch.setattr(universal, "_is_passive", lambda vf: not with_dc(vf))
    monkeypatch.setattr(universal, "_rms_error", lambda vf, n: 1e-4 if with_dc(vf) else 1e-3)
    for strict, path in ((False, "dc refit"), (True, "reduced order")):
        got = universal._enforce_passivity_path(vf0, band, 1.05, dc_net=dc_net, max_order=10,
                                                prefer_strict=strict, convex_max_states=0)
        assert got[3] == path


def test_the_refit_needs_no_max_order():
    """A library caller that hands in the 0 Hz band without max_order gets the refit at the
    fit's own model order, where it used to be skipped without a word."""
    net = _with_dc_point(_example("ind_500pH_ihp-sg13cmos5l.s2p"))
    band = io.without_dc(net)
    vf0 = universal._auto_fit(band, 6)
    got = universal._enforce_passivity_path(vf0, band, dc_net=io.passive_dc(
        net, ceiling=dcpin.DC_SIGMA)[0], convex_max_states=0)
    assert got[3] == "dc refit"


def test_the_refit_runs_when_the_fit_range_starts_at_the_first_sample():
    """A fit range from the file's first sample above 0 Hz fits the same band, so it keeps
    the refit.  One that starts higher leaves no 0 Hz point next to its band."""
    coil = _with_dc_point(_example("ind_500pH_ihp-sg13cmos5l.s2p"))
    assert _convert(coil, max_order=6, f_min=float(coil.f[1]), **_OLD).passivity_path == "dc refit"
    assert (_convert(coil, max_order=6, f_min=float(coil.f[2]), **_OLD).passivity_path
            == "near-passive")


def test_the_refit_reports_its_progress():
    """The refit and its enforcement report on their own share of the bar, rather than
    holding it at one value for the whole refit."""
    trace = []
    engine.convert(ConverterState(max_order=13), _example("tline_100um_ihp-sg13g2.s2p"),
                   progress=lambda f, m: trace.append((f, m)))
    fractions = [f for f, _ in trace]
    assert fractions == sorted(fractions)
    k = next(i for i, (_, m) in enumerate(trace) if m == "refitting with the 0 Hz point")
    assert any(m == "checking passivity" and f > trace[k][0] for f, m in trace[k:])


def test_a_file_shorted_at_dc_is_named():
    """A port shorted at DC needs an infinite conductance.  The note says so instead of
    reporting the band move such a pin would cost."""
    net = _example(_COIL)
    net.s[0] = -np.eye(2)
    res = _convert(net, max_order=13)
    assert not res.dc_pin.ok and "the file's 0 Hz point shorts a port at DC" in res.dc_pin.message
    assert "dcp" not in res.ngspice


def test_a_0_hz_point_made_symmetric_is_reported():
    net = _example(_COIL)
    net.s[0, 0, 1] += 0.01
    res = _convert(net, max_order=13)
    assert res.dc_pin.ok and "made real and symmetric, a change of 5.0e-03" in res.dc_pin.message


def test_cli_warns_when_the_pin_options_meet_no_0_hz_point(tmp_path, capsys):
    from snp2le import cli
    src = os.path.join(_EXAMPLES, "bpf_ihp-sg13g2.s2p")
    assert cli.main(["convert", src, "--dc-pin", "--dc-pin-fc", "1k", "-o",
                     str(tmp_path / "b.spice"), "--quiet"]) == 0
    assert "--dc-pin, --dc-pin-fc ignored, the file has no finite 0 Hz sample" in \
        capsys.readouterr().err
