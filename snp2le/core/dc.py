"""dc.py - DC operating-point health check for a CircuitIR.

A universal (vector-fit) macromodel is a *linear* network, so its DC operating point is a
single linear solve with no excitation (the port sensors are 0 V sources).  The solution
is trivially zero, but only when the DC MNA matrix is non-singular.  A rank-deficient matrix
is exactly what makes a simulator report a "singular matrix" or fail to find the operating
point, and it happens when an internal node has no DC path to ground (its state capacitor is
open at DC) or a controlled-source loop is degenerate.

This builds that DC matrix (capacitors open, ports terminated in z0 to mimic a testbench)
and reports how far it is from singular, so the GUI can warn *before* the netlist is handed
to Ngspice or VACASK.  Because the macromodel is linear, only true singularity matters, not
conditioning: an ill-conditioned but non-singular matrix still yields the (zero) DC solution.

Calibration (BPF and inductor fits, orders 4 to 24): healthy fits sit at margin >= ~6e-8, a
genuinely singular network at ~1e-17, so 1e-12 splits them with many decades of headroom.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

_SINGULAR = 1e-12


@dataclass
class DCHealth:
    ok: bool
    margin: float          # equilibrated reciprocal condition number (1 best, ~0 singular)
    message: str


def dc_check(ir, z0: float = 50.0, ground: str = "0") -> DCHealth:
    """Assess the DC operating point of `ir` (its ports terminated in `z0` to ground)."""
    A = _dc_mna(ir, z0, ground)
    if A.size == 0:
        return DCHealth(True, 1.0, "DC operating point: trivial (no internal state).")
    try:
        margin = 1.0 / np.linalg.cond(_equilibrate(A))
    except np.linalg.LinAlgError:
        margin = 0.0
    if not np.isfinite(margin) or margin < _SINGULAR:
        return DCHealth(
            False, margin,
            "DC operating point looks SINGULAR: an internal node likely has no DC path to "
            "ground (or a controlled-source loop is degenerate), so the simulator may report "
            "a singular matrix or fail to converge. Try a lower order or enable passivity.")
    return DCHealth(True, margin, "DC operating point: solvable.")


def _equilibrate(A, iters: int = 4):
    """Symmetric row/column scaling, so the reported margin reflects what a solver that
    equilibrates (Ngspice, VACASK) effectively sees rather than the raw element spread."""
    A = A.copy()
    for _ in range(iters):
        r = np.sqrt(np.maximum(np.abs(A).max(axis=1), 1e-300))
        A /= r[:, None]
        c = np.sqrt(np.maximum(np.abs(A).max(axis=0), 1e-300))
        A /= c[None, :]
    return A


def _dc_mna(ir, z0: float, ground: str):
    """Modified nodal analysis matrix at DC: capacitors open, inductors and 0 V sources are
    branch-current unknowns, controlled sources stamped, each port terminated in z0."""
    nodes = {n for e in ir.elements for n in e.nodes if n != ground}
    nodes.update(p for p in ir.ports if p != ground)
    ni = {n: i for i, n in enumerate(sorted(nodes))}
    branches = [e for e in ir.elements if e.kind in ("V", "E", "L")]
    bi = {e.name: len(ni) + k for k, e in enumerate(branches)}
    dim = len(ni) + len(branches)
    A = np.zeros((dim, dim))

    def gstamp(a, b, g):                    # conductance between nodes a, b
        ia, ib = ni.get(a), ni.get(b)
        if ia is not None:
            A[ia, ia] += g
        if ib is not None:
            A[ib, ib] += g
        if ia is not None and ib is not None:
            A[ia, ib] -= g
            A[ib, ia] -= g

    for e in ir.elements:
        if e.kind == "R":
            gstamp(e.nodes[0], e.nodes[1], 1.0 / e.value if e.value > 1e-15 else 1e12)
        elif e.kind == "C":
            continue                        # open circuit at DC
        elif e.kind == "G":                 # vccs: I(o+ -> o-) = gain * (V(cp) - V(cn))
            out = (ni.get(e.nodes[0]), ni.get(e.nodes[1]))
            ctl = (ni.get(e.ctrl[0]), ni.get(e.ctrl[1]))
            for r, sr in zip(out, (1.0, -1.0)):
                if r is None:
                    continue
                for c, sc in zip(ctl, (1.0, -1.0)):
                    if c is not None:
                        A[r, c] += sr * sc * e.value
        elif e.kind in ("V", "E", "L"):     # branch-current unknown, V=0 (L/sensor) or dc
            k = bi[e.name]
            ia, ib = ni.get(e.nodes[0]), ni.get(e.nodes[1])
            if ia is not None:
                A[ia, k] += 1.0
                A[k, ia] += 1.0
            if ib is not None:
                A[ib, k] -= 1.0
                A[k, ib] -= 1.0
            if e.kind == "E":               # vcvs: V(o) = gain * V(ctrl)
                cp, cn = ni.get(e.ctrl[0]), ni.get(e.ctrl[1])
                if cp is not None:
                    A[k, cp] -= e.value
                if cn is not None:
                    A[k, cn] += e.value
        elif e.kind == "F":                 # cccs: I(o+ -> o-) = gain * I(controlling branch)
            out = (ni.get(e.nodes[0]), ni.get(e.nodes[1]))
            kc = bi.get(e.ctrl[0])
            if kc is not None:
                if out[0] is not None:
                    A[out[0], kc] += e.value
                if out[1] is not None:
                    A[out[1], kc] -= e.value

    for p in ir.ports:                      # a matched testbench termination at each port
        gstamp(p, ground, 1.0 / z0)
    return A
