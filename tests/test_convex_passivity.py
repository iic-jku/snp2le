# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_convex_passivity.py - the convex passive refit of a universal fit (no Qt).

Passivity enforcement first refits the residues and the constant term of the fit at its own
poles under the bounded-real constraint (passive_refit.py), as one more candidate next to
residue perturbation and the refits.  These tests check the semidefinite program against its
own definition, then what the candidate does to real fits.  Run with:  pytest -q
"""
import copy
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                   # noqa: E402
import pytest                                        # noqa: E402
import scipy.sparse as sp                            # noqa: E402

from snp2le.core import engine, io, passive_refit, universal  # noqa: E402
from snp2le.core.state import ConverterState         # noqa: E402

clarabel = pytest.importorskip("clarabel")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLES = os.path.join(_ROOT, "snp2le", "examples")


def _example(name):
    return io.load_touchstone(os.path.join(_EXAMPLES, name))


def _convert(name, **kw):
    return engine.convert(ConverterState(mode="universal", **kw), _example(name))


def _svec(M, m):
    pos, weight = passive_refit.svec_rows(m)
    return weight * M.reshape(-1, order="F")[pos]


def test_the_triangle_order_is_clarabels():
    """min t with t at (0, 0) and a 1 at one off-diagonal of a 3 x 3 matrix that has to be
    positive semidefinite: the optimum differs with the entry's position, so a wrong order or
    a missing sqrt(2) weight lands on another t."""
    for (r, c), want in (((0, 1), 0.5), ((0, 2), 1 / 3), ((1, 2), 0.0)):
        M0 = np.diag([0.0, 2.0, 3.0])
        M0[r, c] = M0[c, r] = 1.0
        E = np.zeros((3, 3))
        E[0, 0] = 1.0
        settings = clarabel.DefaultSettings()
        settings.verbose = False
        sol = clarabel.DefaultSolver(sp.csc_matrix((1, 1)), np.array([1.0]),
                                     sp.csc_matrix(-_svec(E, 3).reshape(-1, 1)), _svec(M0, 3),
                                     [clarabel.PSDTriangleConeT(3)], settings).solve()
        assert abs(sol.x[0] - want) < 1e-7, ((r, c), sol.x[0])


def test_the_matrix_map_is_the_bounded_real_inequality():
    """h - G x is svec(-L) for L = [[A^T P + P A, P B, C^T], [B^T P, -g I, D^T], [C, D, -g I]],
    checked entry by entry for random P, C and D."""
    rng = np.random.default_rng(1)
    n, N, g = 7, 2, 0.97
    A = np.zeros((n, n))
    A[0, 0] = -0.3
    for i in (1, 3, 5):                            # complex pole blocks
        A[i:i + 2, i:i + 2] = [[-0.1 * i, 0.7 * i], [-0.7 * i, -0.1 * i]]
    B = rng.normal(size=(n, N))
    P = rng.normal(size=(n, n))
    P = P + P.T
    C, D = rng.normal(size=(N, n)), rng.normal(size=(N, N))
    L = np.block([[A.T @ P + P @ A, P @ B, C.T],
                  [B.T @ P, -g * np.eye(N), D.T],
                  [C, D, -g * np.eye(N)]])
    G, h = passive_refit.lmi_map(A, B, g)
    a, b = np.triu_indices(n)
    order = np.lexsort((a, b))
    x = np.concatenate((P[a[order], b[order]], C.reshape(-1, order="F"), D.reshape(-1, order="F")))
    assert np.max(np.abs((h - G @ x) - _svec(-L, n + 2 * N))) < 1e-12


def test_it_beats_perturbation_on_the_same_poles():
    """The band-pass filter at order 13 needs enforcement.  Residue perturbation keeps the
    poles and the constant term, so its model is one point of the convex problem, whose
    optimum can only be closer: 3.5e-4 against 1.5e-3."""
    convex = _convert("bpf_ihp-sg13g2.s2p", max_order=13)
    plain = _convert("bpf_ihp-sg13g2.s2p", max_order=13, convex_max_states=0)
    assert convex.passivity_path == "convex" and plain.passivity_path == "perturbed"
    assert convex.passive and convex.sigma_max <= 1.0
    assert convex.model_order == plain.model_order
    assert convex.rms_error < 0.5 * plain.rms_error
    assert any(m.startswith("passivity enforced (convex refit") for m in convex.messages)


def test_it_reaches_a_constant_term_perturbation_cannot():
    """The 500 pH coil at order 6 has its constant term D at 2.18, which perturbation cannot
    move, so without the refit the model stays near-passive and cannot carry noise.  The
    refit bounds D with everything else and the generator goes in."""
    plain = _convert("ind_500pH_ihp-sg13cmos5l.s2p", max_order=6, convex_max_states=0)
    assert plain.passivity_path == "near-passive" and not plain.passive
    res = _convert("ind_500pH_ihp-sg13cmos5l.s2p", max_order=6, thermal_noise=True)
    assert res.passivity_path == "convex" and res.passive and res.sigma_max <= 1.0
    assert res.rms_error < universal._USABLE_RMS
    assert res.noise.ok, res.noise.message
    assert not any("constant term D" in m for m in res.messages)


def test_noise_at_a_raised_ceiling_points_at_the_convex_refit():
    """At ceiling 1.05 the refit aims at 1.05, so the 500 pH coil at order 6 ends at 1.0499 with
    D there and no noise generator.  The refusal says that enforcing at 1.00 moves D through
    the convex refit, which it does, rather than that it would need a lower order."""
    res = _convert("ind_500pH_ihp-sg13cmos5l.s2p", max_order=6, thermal_noise=True,
                   passivity_ceiling=1.05)
    assert res.passivity_path == "convex" and 1.0 < res.sigma_max <= 1.05
    assert not res.noise.ok
    assert "can move D through the convex refit at this order" in res.noise.message
    strict = _convert("ind_500pH_ihp-sg13cmos5l.s2p", max_order=6, thermal_noise=True)
    assert strict.passivity_path == "convex" and strict.noise.ok


def test_the_other_candidates_still_compete():
    """The line at order 13 leans on a constant term of 5.24.  The refit at those poles is
    passive but 3e-2 off, and a usable convex candidate does not end the ladder: the refit that
    includes the 0 Hz point (refitted convex itself) still runs and wins where it settles, at
    7.5e-4 on Windows.  Whether it settles depends on the platform (it lost on the Linux runner
    with Python 3.10, as a 1e-12 change of the data makes it lose in 2 of 8 tries), so the test
    pins that it ran and that either outcome is passive."""
    steps = []
    res = engine.convert(ConverterState(mode="universal", max_order=13),
                         _example("tline_100um_ihp-sg13g2.s2p"),
                         progress=lambda f, m: steps.append(m))
    assert any("convex passive refit" in m for m in steps)
    assert any("refitting with the 0 Hz point" in m for m in steps)
    assert res.passive and res.passivity_path in ("dc refit", "convex")
    if res.passivity_path == "dc refit":
        assert any("refit with the 0 Hz point, convex" in m for m in res.messages)
        assert res.rms_error < 2e-3


def test_a_model_above_the_limit_is_left_to_the_old_ladder():
    """Above the state limit nothing is solved, the message names the count and the limit,
    and the netlist is the one the ladder without the refit gives."""
    small = _convert("bpf_ihp-sg13g2.s2p", max_order=13, convex_max_states=20)
    off = _convert("bpf_ihp-sg13g2.s2p", max_order=13, convex_max_states=0)
    assert small.passivity_path == "perturbed"
    assert any(m == "convex passive refit skipped: 26 states (ports x model order), above the "
                    "limit of 20" for m in small.messages)
    assert small.ngspice == off.ngspice and small.vacask == off.vacask
    assert "convex refit limit 20 states (default limit 100 states)" in small.messages
    assert "convex refit off (default limit 100 states)" in off.messages


def test_the_refit_is_deterministic():
    """No time limit, so the same fit refits to the same bits on one machine.  Another
    thread count of Clarabel's solver moves the last digits, as another BLAS does."""
    net = io.without_dc(_example("wpd_ihp-sg13g2.s3p"))
    vf = universal._auto_fit(net, 6)
    one, _ = passive_refit.refit(vf, net, 0.9999)
    two, _ = passive_refit.refit(vf, net, 0.9999)
    assert np.array_equal(one.residues, two.residues)
    assert np.array_equal(one.constant_coeff, two.constant_coeff)
    assert universal._is_passive(one)


def test_a_lightly_damped_pole_stays_passive():
    """A pole damped at 1e-5 of the band edge puts entries of P at 1e5 next to entries of
    order 1.  In the raw realisation the solver stops on a numerical error here, and on a
    forced 104-state fit of the balun it left a band at sigma 1.0024.  The balanced one solves,
    and the candidate enforcement gets is strictly passive: near a pole that sharp the solver's
    round-off decides on which side of 1 the peak lands (above it on the Linux and macOS
    runners, below on Windows), and `_scaled_below` brings it under."""
    net = io.without_dc(_example("bpf_ihp-sg13g2.s2p"))
    vf = universal._auto_fit(net, 6)
    w0 = 2 * np.pi * float(net.f.max())
    poles = np.array(vf.poles, dtype=complex)
    k = int(np.argmax(poles.imag))
    poles[k] = -1e-5 * w0 + 1j * poles[k].imag
    vf.poles = poles
    vf.residues = np.array(vf.residues, dtype=complex) * 1e-3
    cand, note = universal._convex_candidate(vf, net, 1.0, 100, universal.null_progress)
    assert cand is not None, note
    assert universal._is_passive(cand)


def test_a_candidate_just_above_the_ceiling_is_scaled_below_it():
    """S is linear in the residues and D, so scaling both scales sigma_max by the same factor.
    A passive refit pushed 0.2 % over 1.00, and 1 % over a ceiling of 1.05, comes back inside
    it, at a factor within 0.3 % and 1.2 % of 1."""
    net = io.without_dc(_example("wpd_ihp-sg13g2.s3p"))
    good, _ = passive_refit.refit(universal._auto_fit(net, 6), net, 0.9999)
    for ceiling, push in ((1.0, 1.002), (1.05, 1.06)):
        over = copy.deepcopy(good)
        over.residues = np.asarray(over.residues) * push
        over.constant_coeff = np.asarray(over.constant_coeff) * push
        assert not universal._meets_ceiling(over, None, ceiling)
        out, k = universal._scaled_below(over, ceiling)
        assert out is not None and universal._meets_ceiling(out, None, ceiling)
        assert 1.0 - 1.2e-2 < k < 1.0
        assert universal.max_singular_value(out)[0] <= ceiling


def test_a_design_file_refuses_a_bad_limit():
    """The window has no control for the limit, so a design file is its only way in there."""
    assert ConverterState.from_json('{"convex_max_states": 40}').convex_max_states == 40
    assert ConverterState.from_json('{"convex_max_states": null}').convex_max_states == 100
    for bad in ("-1", "true", "2.5", '"40"'):
        with pytest.raises(ValueError):
            ConverterState.from_json('{"convex_max_states": %s}' % bad)


def test_a_limit_from_code_that_is_no_count_falls_back_to_the_default():
    """The CLI and a design file check the limit, a state built in code is not checked.  The
    engine takes only a whole number of 0 or more and names any other value in a message,
    since True would read as 1 and 50.7 as 50."""
    for bad in (True, 50.7, -1, "80"):
        assert engine._convex_limit(ConverterState(convex_max_states=bad)) == 100
    assert engine._convex_limit(ConverterState(convex_max_states=np.int64(50))) == 50
    res = _convert("bpf_ihp-sg13g2.s2p", max_order=6, convex_max_states=True)
    assert res.ok
    assert ("convex refit limit True is no whole number of 0 or more, the default limit 100 "
            "states applies") in res.messages


def test_the_cli_takes_the_limit(tmp_path):
    out = tmp_path / "bpf.spice"
    run = subprocess.run([sys.executable, "-m", "snp2le", "-b", "convert",
                          os.path.join(_EXAMPLES, "bpf_ihp-sg13g2.s2p"), "--order", "13",
                          "--convex-max-states", "20", "-o", str(out)],
                         cwd=_ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "above the limit of 20" in run.stdout + run.stderr
    bad = subprocess.run([sys.executable, "-m", "snp2le", "-b", "convert",
                          os.path.join(_EXAMPLES, "bpf_ihp-sg13g2.s2p"), "--convex-max-states",
                          "-3", "-o", str(out)], cwd=_ROOT, capture_output=True, text=True)
    assert bad.returncode != 0 and "--convex-max-states" in bad.stderr
