# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""passive_refit.py - the convex passive refit of a vector fit.

Coelho, Phillips and Silveira (IEEE Trans. CAD 23(2), 2004, doi:10.1109/TCAD.2003.822107)
keep the poles of a stable fit and solve for its numerator under the positive-real lemma,
which is convex once the state matrices A and B are fixed.  snp2le fits S-parameters, so
this uses the bounded-real form of the same lemma: with A Hurwitz, sigma_max(S(jw)) <= g at
every frequency if and only if a symmetric P exists with

    L = [[A^T P + P A, P B, C^T], [B^T P, -g I, D^T], [C, D, -g I]]  <= 0,

linear in (P, C, D).  The objective is snp2le's own error, the sum of |S_model - S_data|^2
over every Sij and data point.  The result is the most accurate model with the fit's poles
that stays at or below g at every frequency, the constant term D included, which residue
perturbation cannot move.  C = 0, D = 0 always satisfies the constraint, so a solution
exists whatever the fit.  The problem goes to Clarabel as a semidefinite program with about
n^2 / 2 unknowns for n states, so time and memory grow steeply with ports x order.
"""
from __future__ import annotations
import copy

import numpy as np
import scipy.sparse as sp


def state_layout(vf, n_ports):
    """(state, input port, pole index, part) in the order of noise.state_space(): one block of
    states per input port, a real pole one state, a complex pole two ('re', 'im')."""
    poles = np.atleast_1d(np.asarray(vf.poles))
    out = []
    i = 0
    for j in range(n_ports):
        for k, p in enumerate(poles):
            if p.imag == 0:
                out.append((i, j, k, "real"))
                i += 1
            else:
                out.append((i, j, k, "re"))
                out.append((i + 1, j, k, "im"))
                i += 2
    return out


def _basis(vf, f, w0, layout):
    """phi[s, f]: the response of state s to its own input at j 2 pi f / w0, for the
    realisation with time scaled by w0 (A / w0, B, C / w0), the same transfer function at
    entries of order 1."""
    poles = np.atleast_1d(np.asarray(vf.poles)) / w0
    sh = 2j * np.pi * np.asarray(f, float) / w0
    phi = np.zeros((len(layout), len(sh)), complex)
    for s, _, k, part in layout:
        p = poles[k]
        if part == "real":
            phi[s] = 1.0 / (sh - p.real)
        else:
            det = (sh - p.real) ** 2 + p.imag ** 2
            phi[s] = 2.0 * (sh - p.real) / det if part == "re" else -2.0 * p.imag / det
    return phi


def _balance(vf, w0, layout):
    """Per-state scale t that makes every pole block about equally controllable: a block with
    input weight b and damping |Re p| has a controllability Gramian of about b^2 / (2 |Re p|),
    so states x / t with t = b / sqrt(2 |Re p|) have one of about 1.  In the raw realisation a
    pole close to the imaginary axis puts entries of P at 1 / |Re p| next to entries of order
    1, and the solver's residual then leaves a narrow violation or stops it on a numerical
    error (a fit with a pole damped at 2e-5 of the band edge came back at sigma_max 1.0024)."""
    poles = np.atleast_1d(np.asarray(vf.poles)) / w0
    t = np.empty(len(layout))
    for s, _, k, part in layout:
        weight = 1.0 if part == "real" else 2.0
        t[s] = weight / np.sqrt(2.0 * max(abs(poles[k].real), 1e-12))
    return t


def svec_rows(m):
    """Column-major positions in vec(M) of the upper triangle of an m x m matrix, in the
    order Clarabel's PSDTriangleConeT reads it, with the sqrt(2) weight of each off-diagonal."""
    r, c = np.triu_indices(m)
    order = np.lexsort((r, c))                     # by column, then row
    r, c = r[order], c[order]
    return c * m + r, np.where(r == c, 1.0, np.sqrt(2.0))


def lmi_map(A, B, gamma):
    """(G, h) with svec(-L) = h - G x, for x = [p, c, d]: p the upper triangle of P column by
    column, c and d vec(C) and vec(D) column-major.  Clarabel's A x + s = b with s in the PSD
    cone then reads s = svec(-L) >= 0, that is L <= 0."""
    n, N = B.shape
    m = n + 2 * N
    n_p = n * (n + 1) // 2
    # vec(P) = dup @ p
    a, b = np.triu_indices(n)
    order = np.lexsort((a, b))
    a, b = a[order], b[order]
    idx = np.arange(n_p)
    rows = np.concatenate((b * n + a, (a * n + b)[a != b]))
    cols = np.concatenate((idx, idx[a != b]))
    dup = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n * n, n_p))
    As = sp.csr_matrix(A)
    eye_n = sp.identity(n, format="csr")
    k_tl = (sp.kron(eye_n, As.T) + sp.kron(As.T, eye_n)) @ dup     # vec(A^T P + P A)
    k_tm = sp.kron(sp.csr_matrix(B).T, eye_n) @ dup                # vec(P B), n x N
    # place each block's entries at their column-major index in vec(L)
    tl = np.arange(n * n)
    tl_rows = (tl // n) * m + tl % n
    tm = np.arange(n * N)
    tm_rows = (n + tm // n) * m + tm % n
    k_tl, k_tm = k_tl.tocoo(), k_tm.tocoo()
    r_list = [tl_rows[k_tl.row], tm_rows[k_tm.row]]
    c_list = [k_tl.col, k_tm.col]
    v_list = [k_tl.data, k_tm.data]
    # C^T in the top-right block: L[a, n + N + k] = C[k, a] = c[a * N + k]
    aa, kk = np.meshgrid(np.arange(n), np.arange(N), indexing="ij")
    r_list.append(((n + N + kk) * m + aa).ravel())
    c_list.append((n_p + aa * N + kk).ravel())
    v_list.append(np.ones(n * N))
    # D^T in the middle-right block: L[n + j, n + N + k] = D[k, j] = d[j * N + k]
    jj, kk = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    r_list.append(((n + N + kk) * m + n + jj).ravel())
    c_list.append((n_p + n * N + jj * N + kk).ravel())
    v_list.append(np.ones(N * N))
    full = sp.csr_matrix((np.concatenate(v_list), (np.concatenate(r_list), np.concatenate(c_list))),
                         shape=(m * m, n_p + n * N + N * N))
    pos, weight = svec_rows(m)
    G = sp.diags(weight) @ full[pos]
    const = np.zeros((m, m))
    const[n:, n:] = gamma * np.eye(2 * N)          # -L's constant part
    h = weight * const.reshape(-1, order="F")[pos]
    return G.tocsc(), h


def _model_response(vf, f, n_ports):
    out = np.empty((len(f), n_ports, n_ports), complex)
    for i in range(n_ports):
        for j in range(n_ports):
            out[:, i, j] = vf.get_model_response(i, j, f)
    return out


def refit(vf, net, gamma):
    """The most accurate model with `vf`'s poles whose sigma_max stays at or below `gamma`
    at every frequency, fitted to `net`.  Returns (vf_new, None) or (None, reason).  `vf`
    itself is not changed.  The caller decides on the size beforehand, see `n_states`."""
    try:
        import clarabel
    except ImportError:
        return None, "the clarabel package is not installed"
    from .noise import state_space
    A, B, C, D, E = state_space(vf)
    if np.any(E != 0.0):
        return None, "the fit has a proportional term"
    n, N = B.shape
    f = np.asarray(net.f, float)
    w0 = 2 * np.pi * float(f.max())
    layout = state_layout(vf, N)
    # Balanced coordinates x / t: B / t, C t, A unchanged since t is one scalar per pole block.
    t = _balance(vf, w0, layout)
    phi = _basis(vf, f, w0, layout) / t[:, None]
    port = np.array([j for _, j, _, _ in layout])
    F = len(f)
    # M[row, f, j]: the basis of response column j at frequency f.  Rows: n states, then D.
    M = np.zeros((n + N, F, N), complex)
    M[np.arange(n), :, port] = phi
    M[n + np.arange(N), :, np.arange(N)] = 1.0
    M = M.reshape(n + N, F * N)
    # The state layout has to be scikit-rf's, or the constraint would hold for another model.
    ref = np.transpose(_model_response(vf, f, N), (1, 0, 2)).reshape(N, F * N)
    now = np.hstack((C / w0 * t, D)) @ M
    if not np.max(np.abs(now - ref)) <= 1e-9 * max(1.0, float(np.max(np.abs(ref)))):
        return None, "the state-space realisation does not reproduce the fit"
    Y = np.transpose(np.asarray(net.s), (1, 0, 2)).reshape(N, F * N)
    Mr = np.hstack((M.real, M.imag))
    Yr = np.hstack((Y.real, Y.imag))
    Q, R = np.linalg.qr(Mr.T, mode="reduced")      # sum |w M - y|^2 = |R w^T - Q^T y^T|^2 + const
    target = Yr @ Q
    # x = [p, c, d, z], z the residual R w_i^T - Q^T y_i^T of each row i of [C / w0, D]
    G, h = lmi_map(A / w0, B / t[:, None], gamma)
    n_p, n_c, n_d = G.shape[1] - n * N - N * N, n * N, N * N
    n_w = n + N
    n_z = N * n_w
    n_x = n_p + n_c + n_d + n_z
    rows, cols, vals = [], [], []
    w_col = np.concatenate((n_p + np.arange(n) * N, n_p + n_c + np.arange(N) * N))
    rr, cc = np.meshgrid(np.arange(n_w), np.arange(n_w), indexing="ij")
    for i in range(N):
        base = i * n_w
        rows += [base + np.arange(n_w), base + rr.ravel()]
        cols += [n_p + n_c + n_d + base + np.arange(n_w), (w_col + i)[cc.ravel()]]
        vals += [np.ones(n_w), -R.ravel()]
    A_eq = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                         shape=(n_z, n_x))
    b_eq = -target.reshape(-1)
    G = sp.hstack((G, sp.csr_matrix((G.shape[0], n_z))))
    A_all = sp.vstack((A_eq, G)).tocsc()
    b_all = np.concatenate((b_eq, h))
    P_obj = sp.diags(np.concatenate((np.zeros(n_x - n_z), 2.0 * np.ones(n_z)))).tocsc()
    settings = clarabel.DefaultSettings()
    settings.verbose = False
    cones = [clarabel.ZeroConeT(n_z), clarabel.PSDTriangleConeT(n + 2 * N)]
    sol = clarabel.DefaultSolver(P_obj, np.zeros(n_x), A_all, b_all, cones, settings).solve()
    status = str(sol.status)
    if status not in ("Solved", "AlmostSolved"):
        return None, f"the solver stopped with status {status}"
    x = np.asarray(sol.x)
    c = x[n_p:n_p + n_c].reshape(N, n, order="F") / t * w0
    d = x[n_p + n_c:n_p + n_c + n_d].reshape(N, N, order="F")
    out = copy.deepcopy(vf)
    res = np.array(out.residues, dtype=complex, copy=True)
    resp = np.arange(N) * N
    for s, j, k, part in layout:
        if part == "real":
            res[resp + j, k] = c[:, s]
        elif part == "re":
            res[resp + j, k] = c[:, s] + 1j * c[:, s + 1]
    out.residues = res
    out.constant_coeff = d.reshape(-1).astype(np.asarray(out.constant_coeff).dtype)
    return out, None


def n_states(vf, n_ports):
    """Internal states of the realisation: ports x model order."""
    poles = np.atleast_1d(np.asarray(vf.poles))
    return n_ports * int(np.count_nonzero(poles.imag == 0) + 2 * np.count_nonzero(poles.imag != 0))
