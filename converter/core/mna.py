"""mna.py - minimal nodal analysis: an R/L/C CircuitIR -> N-port S-parameters.

Used to reconstruct the *model* response of a physical structure model so the
Plot view can overlay it against the measured data.  Handles R, L, C and the
port/ground topology only (physical models contain no controlled sources).
"""
from __future__ import annotations
import numpy as np
import skrf


def rlc_sparams(ir, freq_hz, z0=50.0):
    ports = list(ir.ports)
    # node index map; ground '0' is the reference (excluded from the matrix)
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

        for e in ir.elements:
            a, b = e.nodes[0], e.nodes[1]
            if e.kind == "R":
                # R <= 0 is an ideal short (a wire); stamp a large conductance so
                # the node is tied rather than left floating
                stamp(a, b, 1.0 / e.value if e.value > 1e-9 else 1e9)
            elif e.kind == "C":
                stamp(a, b, 1j * wk * e.value)
            elif e.kind == "L":
                if e.value > 0:
                    stamp(a, b, 1.0 / (1j * wk * e.value + 1e-18))
        # reduce internal nodes (Schur complement) to the port admittance matrix
        Ypp = Y[:P, :P]; Ypi = Y[:P, P:]; Yip = Y[P:, :P]; Yii = Y[P:, P:]
        if N > P:
            Yport = Ypp - Ypi @ np.linalg.solve(Yii, Yip)
        else:
            Yport = Ypp
        S[k] = skrf.network.y2s(Yport[np.newaxis, :, :], z0=z0)[0]
    return S
