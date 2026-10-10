# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""noise.py - the thermal noise of a universal (vector-fit) macromodel.

A passive N-port at temperature T emits noise waves with the correlation kT (I - S S^H) per
hertz (Bosma), so its noise follows from its S-parameters alone.  The resistors of a vector-fit
realisation cannot carry it, since they place poles rather than model loss, and they stay
noiseless (see netlist._NOISY_OFF).  This module builds a separate noise generator from the
fitted model and appends it to the subcircuit.

With the fit S(s) = D + C (sI - A)^-1 B, the bounded-real lemma gives a causal spectral factor
V(s) = V0 + C (sI - A)^-1 K with V V~ = I - S S~:

    R = I - D D^T = V0 V0^T,
    A Q + Q A^T + B B^T + (Q C^T + B D^T) R^-1 (C Q + D B^T) = 0,
    K = -(Q C^T + B D^T) V0^-T.

N white voltages of PSD kT, each a 0.25 ohm resistor at an otherwise open node, drive V, whose
output is the outgoing noise wave c of each port.  In scikit-rf's realisation a current j into
port n's sensor node s_n adds sqrt(Z0)/2 j to the outgoing wave b_n, so controlled sources
inject j = 2/sqrt(Z0) c there.  Only R, C and VCCS elements are added and nothing feeds back from
the signal network, so the S-parameters and the operating point stay exactly what they were.

A factor exists only for a strictly passive model, sigma_max < 1 at every frequency and at
infinity.  Whether it exists is decided from the model itself (the factorisation and its check),
never from the passivity settings that produced it.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import scipy.linalg as la

from .ir import Element

# Largest |V V^H - (I - S S^H)| accepted on the check grid, in units of kT.  A good factor
# lands near 1e-12, a failed one at the size of the loss itself.
CHECK_TOL = 1e-6
# Resistance of each white source: 4 k T R = k T, the noise-wave PSD of a matched port.
SOURCE_OHM = 0.25
# Check grid: log-spaced over the data span widened this far either side, plus the data band.
_SPAN_DECADES = 4.0
_LOG_POINTS = 400
_BAND_POINTS = 200
# Prefix of every node and element the generator adds.  scikit-rf names its own V, R, C, G,
# F elements and the p, s, x nodes, so this cannot collide.
_TAG = "nz"


@dataclass
class NoiseHealth:
    ok: bool
    message: str
    n_sources: int = 0              # white sources, one per port
    n_states: int = 0               # states of the generator, the fit's model order x ports
    error: float = float("nan")     # worst |V V^H - (I - S S^H)| on the check grid [kT]
    loss_min: float = float("nan")  # smallest eigenvalue of I - S S^H there [kT]


def state_space(vf):
    """Real (A, B, C, D, E) of the fitted model, from scikit-rf's public pole and residue
    attributes, laid out as its private `_get_ABCDE` does.  One block of states per input
    port: a real pole is one state, a complex pole (stored once, its conjugate implied) is
    two, x_re' = Re(p) x_re + Im(p) x_im + 2 u and x_im' = -Im(p) x_re + Re(p) x_im."""
    poles = np.atleast_1d(np.asarray(vf.poles))
    res = np.atleast_2d(np.asarray(vf.residues))
    d = np.real(np.asarray(vf.constant_coeff, dtype=complex))
    e = np.real(np.asarray(vf.proportional_coeff, dtype=complex))
    n_ports = int(round(np.sqrt(d.size)))
    per_port = int(sum(1 if p.imag == 0 else 2 for p in poles))
    n = n_ports * per_port
    A = np.zeros((n, n))
    B = np.zeros((n, n_ports))
    C = np.zeros((n_ports, n))
    i = 0
    for j in range(n_ports):
        r = res[j::n_ports]                        # responses S_kj, k = 0..N-1
        for k, p in enumerate(poles):
            if p.imag == 0:
                A[i, i] = p.real
                B[i, j] = 1.0
                C[:, i] = r[:, k].real
                i += 1
            else:
                A[i, i] = A[i + 1, i + 1] = p.real
                A[i, i + 1] = p.imag
                A[i + 1, i] = -p.imag
                B[i, j] = 2.0
                C[:, i] = r[:, k].real
                C[:, i + 1] = r[:, k].imag
                i += 2
    return A, B, C, d.reshape(n_ports, n_ports), e.reshape(n_ports, n_ports)


def spectral_factor(A, B, C, D, w0):
    """(K, V0) of V(s) = V0 + C (sI - A)^-1 K with V V~ = I - S S~.

    The Riccati equation is solved with time normalised to `w0` (rad/s), since A carries
    poles of 1e10 rad/s and more.  V0 is the Cholesky factor of R, lower triangular, which
    saves the netlist N (N - 1) / 2 sources against the symmetric root.  Raises
    np.linalg.LinAlgError or ValueError when no factor is found."""
    n_ports = D.shape[0]
    R = np.eye(n_ports) - D @ D.T
    An, Bn, Cn = A / w0, B / np.sqrt(w0), C / np.sqrt(w0)
    # scipy solves a^T X + X a - (X b + s) r^-1 (b^T X + s^T) + q = 0
    Q = la.solve_continuous_are(An.T, Cn.T, Bn @ Bn.T, -R, s=Bn @ D.T)
    V0 = la.cholesky(R, lower=True)
    X = Q @ Cn.T + Bn @ D.T
    Kn = -la.solve_triangular(V0, X.T, lower=True).T             # -X V0^-T
    return Kn * np.sqrt(w0), V0


def _check_grid(f):
    """Frequencies [Hz] the factor is checked on: DC, a log sweep _SPAN_DECADES beyond the
    data either side, and a dense sweep across the data band itself."""
    f = np.asarray(f, dtype=float)
    f = f[f > 0]
    if f.size == 0:
        return np.logspace(6, 14, _LOG_POINTS)
    lo = f[0] * 10.0 ** -_SPAN_DECADES
    hi = f[-1] * 10.0 ** _SPAN_DECADES
    return np.unique(np.concatenate((
        [0.0], np.logspace(np.log10(lo), np.log10(hi), _LOG_POINTS),
        np.linspace(f[0], f[-1], _BAND_POINTS))))


def _responses(A, B, K, C, D, V0, f):
    """S(j w) and V(j w) on the grid, one solve per frequency for both."""
    n, n_ports = B.shape
    rhs = np.hstack((B, K)).astype(complex)
    eye = np.eye(n)
    S = np.empty((len(f), n_ports, n_ports), dtype=complex)
    V = np.empty((len(f), n_ports, n_ports), dtype=complex)
    for i, fi in enumerate(f):
        X = C @ np.linalg.solve(2j * np.pi * fi * eye - A, rhs)
        S[i] = D + X[:, :n_ports]
        V[i] = V0 + X[:, n_ports:]
    return S, V


def _port_sensors(ir, ground="0"):
    """Sensor node s_n and reference resistance of every port, in port order.

    scikit-rf realises port n as a 0 V source from p_n to s_n plus a resistor of the
    reference impedance from s_n to ground.  None if the IR is not shaped like that."""
    out = []
    for p in ir.ports:
        sense = next((e for e in ir.elements if e.kind == "V" and e.nodes[0] == p), None)
        if sense is None:
            return None
        s = sense.nodes[1]
        ref = next((e for e in ir.elements if e.kind == "R" and set(e.nodes) == {s, ground}),
                   None)
        if ref is None or not ref.value > 0:
            return None
        out.append((s, float(ref.value)))
    return out


def generator_elements(A, C, K, V0, sensors, w0, ground="0"):
    """The generator as IR elements, appended after the fitted network.

    State i is a capacitor of 1/w0 at node nz_x<i> driven by VCCS, so x' = A x + K u
    keeps unit-size gains for the poles.  VACASK solves its matrix without equilibration,
    so each state is rescaled until the gains that drive it (K) and the gains that read
    it (C) meet in size, with a complex pair sharing one factor so its block stays as is.
    Without that the gains spread from 1e-15 to 4e11 and VACASK was 1.4 % off."""
    n, n_ports = K.shape
    cap = 1.0 / w0
    a = [2.0 / np.sqrt(z0) for _, z0 in sensors]    # wave c -> current into s_n
    k_in = np.max(np.abs(K), axis=1) * cap
    k_out = np.max(np.abs(C) * np.asarray(a)[:, None], axis=0)
    t = np.ones(n)
    good = (k_in > 0) & (k_out > 0)
    t[good] = np.sqrt(k_in[good] / k_out[good])
    for i in range(n - 1):
        if A[i, i + 1] != 0.0:                      # a complex pair
            t[i] = t[i + 1] = np.sqrt(t[i] * t[i + 1])
    As = A * t[None, :] / t[:, None]                # T^-1 A T
    Ks = K / t[:, None]
    Cs = C * t[None, :]

    els = []
    src = [f"{_TAG}_e{k + 1}" for k in range(n_ports)]
    st = [f"{_TAG}_x{i + 1}" for i in range(n)]
    for k in range(n_ports):
        els.append(Element("R", f"R{src[k]}", (src[k], ground), SOURCE_OHM, noisy=True))
    for i in range(n):
        els.append(Element("C", f"C{st[i]}", (st[i], ground), cap))
        for j in np.flatnonzero(As[i]):
            els.append(Element("G", f"G{_TAG}_a{i + 1}_{j + 1}", (ground, st[i]),
                               float(As[i, j] * cap), ctrl=(st[j], ground)))
        for k in np.flatnonzero(Ks[i]):
            els.append(Element("G", f"G{_TAG}_k{i + 1}_{k + 1}", (ground, st[i]),
                               float(Ks[i, k] * cap), ctrl=(src[k], ground)))
    for p, (s_node, _) in enumerate(sensors):
        for i in np.flatnonzero(Cs[p]):
            els.append(Element("G", f"G{_TAG}_c{p + 1}_{i + 1}", (ground, s_node),
                               float(a[p] * Cs[p, i]), ctrl=(st[i], ground)))
        for k in np.flatnonzero(V0[p]):
            els.append(Element("G", f"G{_TAG}_d{p + 1}_{k + 1}", (ground, s_node),
                               float(a[p] * V0[p, k]), ctrl=(src[k], ground)))
    return els


def add_thermal_noise(ir, vf, sigma_max=None, sigma_max_freq=None) -> NoiseHealth:
    """Append the thermal-noise generator of the fit `vf` to its realisation `ir`, in place.

    Returns a NoiseHealth.  When `ok` is False nothing was added and `message` says why,
    which is either a model that is not strictly passive or a factor that failed its check.
    `sigma_max` and `sigma_max_freq` are the fit's own measurement (universal.FitResult),
    quoted in that message so it names the same number as the passivity result."""
    from .units import format_eng
    fail = "thermal noise NOT added: "
    sensors = _port_sensors(ir)
    if sensors is None:
        return NoiseHealth(False, fail + "the netlist is not a scikit-rf realisation")
    if any(n.startswith(_TAG + "_") for e in ir.elements for n in e.nodes):
        return NoiseHealth(False, fail + f"the netlist already uses '{_TAG}_' node names")
    A, B, C, D, E = state_space(vf)
    n, n_ports = B.shape
    if n_ports != len(sensors):
        return NoiseHealth(False, fail + "the fit and the netlist differ in port count")
    if np.any(E != 0.0):
        return NoiseHealth(False, fail + "the fit has a proportional term, so it is not "
                                         "bounded at high frequency")

    f = _check_grid(vf.network.f)
    S, _ = _responses(A, B, np.zeros((n, n_ports)), C, D, np.zeros((n_ports, n_ports)), f)
    phi = np.eye(n_ports) - S @ np.conj(np.transpose(S, (0, 2, 1)))
    loss = np.array([np.linalg.eigvalsh(m)[0] for m in phi])
    k = int(np.argmin(loss))
    loss_min = float(loss[k])
    d_loss = float(np.linalg.eigvalsh(np.eye(n_ports) - D @ D.T)[0])
    # Loss of exactly 0 is a lossless direction, where the noise really is 0 but no factor
    # exists, so strict passivity is what both tests ask for.
    if loss_min <= 0.0 or d_loss <= 0.0:
        if sigma_max is not None and sigma_max == sigma_max and sigma_max >= 1.0:
            sigma, where = sigma_max, f"at {format_eng(sigma_max_freq, 'Hz')}"
        else:
            sigma = np.sqrt(max(0.0, 1.0 - min(loss_min, d_loss)))
            where = (f"at {format_eng(f[k], 'Hz')}" if loss_min <= d_loss
                     else "at high frequency")
        return NoiseHealth(False, fail + f"the model is not strictly passive (sigma_max "
                                         f"{sigma:.4f} {where}). Enforce passivity at "
                                         f"ceiling 1.00, or try another Max order",
                           loss_min=min(loss_min, d_loss))

    w0 = float(np.max(np.abs(np.atleast_1d(vf.poles))))
    try:
        K, V0 = spectral_factor(A, B, C, D, w0)
    except (np.linalg.LinAlgError, ValueError) as exc:
        return NoiseHealth(False, fail + f"no spectral factor found ({exc}). The model is "
                                         f"close to lossless or not strictly passive "
                                         f"between the sampled frequencies",
                           loss_min=loss_min)
    _, V = _responses(A, B, K, C, D, V0, f)
    err = float(np.max(np.abs(V @ np.conj(np.transpose(V, (0, 2, 1))) - phi)))
    if not err <= CHECK_TOL:
        return NoiseHealth(False, fail + f"the spectral factor misses I - S S^H by "
                                         f"{err:.1e} kT (limit {CHECK_TOL:.0e})",
                           error=err, loss_min=loss_min)

    for el in generator_elements(A, C, K, V0, sensors, w0):
        ir.add(el)
    ir.notes += [
        "thermal noise of the passive: kT(I - S S^H) at the ports, from a spectral factor "
        "of this fit",
        f"sources R{_TAG}_e1..R{_TAG}_e{n_ports} ({SOURCE_OHM:g} ohm, the only noisy "
        f"elements), {n} states {_TAG}_x*, controlled sources G{_TAG}_*"]
    return NoiseHealth(True, f"thermal noise added: {n_ports} sources, {n} states, "
                             f"factor error {err:.1e} kT",
                       n_sources=n_ports, n_states=n, error=err, loss_min=loss_min)
