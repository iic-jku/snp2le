# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_convex_passivity.py - the convex passive refit of a universal fit (no Qt).

Passivity enforcement first refits the residues and the constant term of the fit at its own
poles under the bounded-real constraint (passive_refit.py), as one more candidate next to
residue perturbation and the refits.  These tests check the semidefinite program against its
own definition, then what the candidate does to real fits.  Run with:  pytest -q
"""
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


def test_the_other_candidates_still_compete():
    """The line at order 13 leans on a constant term of 5.24.  The refit at those poles is
    passive but 3e-2 off, the refit that includes the 0 Hz point (refitted convex itself) is
    closer and wins, as it did before the convex step existed."""
    res = _convert("tline_100um_ihp-sg13g2.s2p", max_order=13)
    assert res.passivity_path == "dc refit" and res.passive
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
    """One solver thread and no time limit, so the same fit refits to the same bits."""
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
    forced 104-state fit of the balun it left a band at sigma 1.0024.  The balanced one keeps
    the refit passive."""
    net = io.without_dc(_example("bpf_ihp-sg13g2.s2p"))
    vf = universal._auto_fit(net, 6)
    w0 = 2 * np.pi * float(net.f.max())
    poles = np.array(vf.poles, dtype=complex)
    k = int(np.argmax(poles.imag))
    poles[k] = -1e-5 * w0 + 1j * poles[k].imag
    vf.poles = poles
    vf.residues = np.array(vf.residues, dtype=complex) * 1e-3
    out, why = passive_refit.refit(vf, net, 0.9999)
    assert out is not None, why
    assert universal._is_passive(out)


def test_a_design_file_refuses_a_bad_limit():
    """The window has no control for the limit, so a design file is its only way in there."""
    assert ConverterState.from_json('{"convex_max_states": 40}').convex_max_states == 40
    assert ConverterState.from_json('{"convex_max_states": null}').convex_max_states == 100
    for bad in ("-1", "true", "2.5", '"40"'):
        with pytest.raises(ValueError):
            ConverterState.from_json('{"convex_max_states": %s}' % bad)


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
