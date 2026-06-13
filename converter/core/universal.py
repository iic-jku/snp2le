"""universal.py - the universal (any-N-port) macromodel via vector fitting.

Wraps skrf.vectorFitting.VectorFitting: auto-fit the S-parameters, optionally
enforce passivity, emit the SPICE subcircuit, and parse it back into a CircuitIR
so both netlist dialects render from one representation.  Also reconstructs the
fitted S-parameters on any frequency grid for the data-vs-model plots.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import io as _io
import contextlib
import numpy as np

from skrf.vectorFitting import VectorFitting

from .ir import CircuitIR
from . import netlist as _nl


@dataclass
class FitResult:
    ir: CircuitIR = None
    n_poles: int = 0
    passive: bool = False
    rms_error: float = float("nan")     # fraction (0..1) over all Sij
    vf: object = None                   # the VectorFitting object
    messages: list = field(default_factory=list)


def fit_universal(net, max_order: int = 12, enforce_passivity: bool = True) -> FitResult:
    """Vector-fit `net` and synthesise a lumped-element SPICE subcircuit."""
    res = FitResult()
    vf = VectorFitting(net)
    # auto_fit chooses the model order; cap complex poles by max_order.
    n_cmplx = max(2, (max_order // 2) * 2)
    with contextlib.redirect_stdout(_io.StringIO()), \
            contextlib.redirect_stderr(_io.StringIO()):
        try:
            vf.auto_fit(n_poles_init=n_cmplx)
        except TypeError:
            vf.auto_fit()
        if enforce_passivity:
            try:
                if not vf.is_passive():
                    vf.passivity_enforce()
                res.messages.append("passivity enforced" if vf.is_passive()
                                    else "passivity enforced (near-passive)")
            except Exception as exc:                   # noqa: BLE001
                res.messages.append(f"passivity enforce failed: {exc}")

    res.vf = vf
    res.n_poles = int(len(np.atleast_1d(vf.poles)))
    try:
        res.passive = bool(vf.is_passive())
    except Exception:                              # noqa: BLE001
        res.passive = False
    res.rms_error = _rms_error(vf, net)

    import tempfile, os
    with tempfile.NamedTemporaryFile("w+", suffix=".cir", delete=False) as fh:
        tmp = fh.name
    try:
        vf.write_spice_subcircuit_s(tmp)
        with open(tmp) as fh:
            spice_text = fh.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    res.ir = _nl.parse_spice_subckt(spice_text, name="s_equivalent")
    return res


def model_sparams(vf, freq_hz):
    """Reconstruct the fitted S-parameters S[f, i, j] on a frequency grid."""
    f = np.asarray(freq_hz, dtype=float)
    n = vf.network.nports
    S = np.zeros((len(f), n, n), dtype=complex)
    for i in range(n):
        for j in range(n):
            S[:, i, j] = vf.get_model_response(i, j, f)
    return S


def _rms_error(vf, net) -> float:
    """RMS of |S_model - S_data| over all responses, at the data frequencies."""
    try:
        f = net.f
        n = net.nports
        num = 0.0
        den = 0
        for i in range(n):
            for j in range(n):
                model = vf.get_model_response(i, j, f)
                data = net.s[:, i, j]
                num += np.sum(np.abs(model - data) ** 2)
                den += len(f)
        return float(np.sqrt(num / den)) if den else float("nan")
    except Exception:                              # noqa: BLE001
        return float("nan")
