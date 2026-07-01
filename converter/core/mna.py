"""mna.py - minimal nodal analysis: an R/L/C CircuitIR -> N-port S-parameters.

Used to reconstruct the *model* response of a physical structure model so the
Plot view can overlay it against the measured data.  Handles R, L, C, magnetically
coupled inductors (ir.couplings, e.g. a transformer balun) and the port/ground
topology only (physical models contain no controlled sources).
"""
from __future__ import annotations
import numpy as np
import skrf


def _coupled_groups(ir):
    """Group magnetically coupled inductors and return, per group, the inverse
    inductance matrix Gamma = L^-1 and the (node+, node-) of each member branch.

    Coupled inductor branches no longer have an independent admittance 1/(jwL).
    The group obeys V = jw L I with off-diagonal mutuals M_ij = k_ij*sqrt(Li*Lj),
    so the branch admittance block is Gamma/(jw).  Returns (groups, coupled_names)
    where coupled_names are the inductors handled here (the rest stamp normally).
    """
    inds = {e.name: e for e in ir.elements if e.kind == "L" and e.value > 0}
    pairs = [(a, b, k) for a, b, k in getattr(ir, "couplings", [])
             if a in inds and b in inds]
    coupled = set()
    for a, b, _ in pairs:
        coupled.add(a); coupled.add(b)
    parent = {n: n for n in coupled}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    for a, b, _ in pairs:
        parent[find(a)] = find(b)
    members = {}
    for n in coupled:
        members.setdefault(find(n), []).append(n)
    kpair = {frozenset((a, b)): k for a, b, k in pairs}

    groups = []
    for names in members.values():
        m = len(names)
        Lm = np.zeros((m, m))
        for i, ni in enumerate(names):
            Lm[i, i] = inds[ni].value
        for i, ni in enumerate(names):
            for j in range(i + 1, m):
                k = kpair.get(frozenset((ni, names[j])))
                if k is not None:
                    Lm[i, j] = Lm[j, i] = k * np.sqrt(Lm[i, i] * Lm[j, j])
        gamma = np.linalg.inv(Lm)
        branch = [(inds[n].nodes[0], inds[n].nodes[1]) for n in names]
        groups.append((gamma, branch))
    return groups, coupled


def rlc_sparams(ir, freq_hz, z0=50.0):
    ports = list(ir.ports)
    # node index map. Ground '0' is the reference (excluded from the matrix)
    nodes = set()
    for e in ir.elements:
        for n in e.nodes:
            if n != "0":
                nodes.add(n)
    for p in ports:
        nodes.add(p)
    order = ports + sorted(n for n in nodes if n not in ports)
    idx = {n: i for i, n in enumerate(order)}
    N = len(order)
    P = len(ports)
    f = np.asarray(freq_hz, dtype=float)
    w = 2 * np.pi * f
    S = np.zeros((len(f), P, P), dtype=complex)

    groups, coupled = _coupled_groups(ir)          # mutual-inductor preprocessing

    for k, wk in enumerate(w):
        Y = np.zeros((N, N), dtype=complex)

        def stamp(a, b, y):
            ia = idx.get(a); ib = idx.get(b)
            if ia is not None:
                Y[ia, ia] += y
            if ib is not None:
                Y[ib, ib] += y
            if ia is not None and ib is not None:
                Y[ia, ib] -= y
                Y[ib, ia] -= y

        def stamp4(ai, bi, aj, bj, y):
            """Couple branch i (ai,bi) to branch j (aj,bj) with admittance y."""
            for r, sr in ((ai, 1.0), (bi, -1.0)):
                ir_ = idx.get(r)
                if ir_ is None:
                    continue
                for c, sc in ((aj, 1.0), (bj, -1.0)):
                    ic_ = idx.get(c)
                    if ic_ is not None:
                        Y[ir_, ic_] += sr * sc * y

        for e in ir.elements:
            a, b = e.nodes[0], e.nodes[1]
            if e.kind == "R":
                # R <= 0 is an ideal short (a wire). Stamp a large conductance so
                # the node is tied rather than left floating
                stamp(a, b, 1.0 / e.value if e.value > 1e-9 else 1e9)
            elif e.kind == "C":
                stamp(a, b, 1j * wk * e.value)
            elif e.kind == "L":
                if e.value > 0 and e.name not in coupled:   # coupled L's: see below
                    stamp(a, b, 1.0 / (1j * wk * e.value + 1e-18))
        # coupled inductor groups: stamp Gamma/(jw) across their branch incidences
        for gamma, branch in groups:
            yb = gamma / (1j * wk)
            for i, (ai, bi) in enumerate(branch):
                for j, (aj, bj) in enumerate(branch):
                    stamp4(ai, bi, aj, bj, yb[i, j])
        # reduce internal nodes (Schur complement) to the port admittance matrix
        Ypp = Y[:P, :P]; Ypi = Y[:P, P:]; Yip = Y[P:, :P]; Yii = Y[P:, P:]
        if N > P:
            Yport = Ypp - Ypi @ np.linalg.solve(Yii, Yip)
        else:
            Yport = Ypp
        S[k] = skrf.network.y2s(Yport[np.newaxis, :, :], z0=z0)[0]
    return S
