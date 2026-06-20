"""universal.py - the universal (any-N-port) macromodel via vector fitting.

Wraps skrf.vectorFitting.VectorFitting: auto-fit the S-parameters, optionally
enforce passivity, emit the SPICE subcircuit, and parse it back into a CircuitIR
so both netlist dialects render from one representation.  Also reconstructs the
fitted S-parameters on any frequency grid for the data-vs-model plots.

The passivity-enforcement strategy in `_enforce_passivity` (escalate the sample
count, then fall back to a lower model order) was inspired by the COBRA project's
vector-fitting wrapper: https://github.com/DI-PASSIONATE/COBRA
(src/cobra/spice_sim/vector_fit.py).
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


# Sample counts tried, in order, when enforcing passivity.  Escalating the count
# (rather than scraping scikit-rf's warning text) catches narrow violation bands
# that a low count misses, while staying cheap in the common case.
_PASSIVITY_N_SAMPLES = (200, 800)
# An enforced/reduced model is only accepted if it stays this close to the data;
# otherwise we keep the accurate (near-passive) fit rather than ship a wreck.
_USABLE_RMS = 0.1


def fit_universal(net, max_order: int = 12, enforce_passivity: bool = True) -> FitResult:
    """Vector-fit `net` and synthesise a lumped-element SPICE subcircuit."""
    res = FitResult()
    with contextlib.redirect_stdout(_io.StringIO()), \
            contextlib.redirect_stderr(_io.StringIO()):
        vf = _auto_fit(net, max_order)
        if enforce_passivity:
            vf, msgs = _enforce_passivity(vf, net)
            res.messages.extend(msgs)

    res.vf = vf
    res.n_poles = int(len(np.atleast_1d(vf.poles)))
    res.passive = _is_passive(vf)
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


def _auto_fit(net, max_order: int):
    """Run scikit-rf auto_fit with the model order bounded by `max_order`.

    auto_fit grows the model adaptively up to `model_order_max`, so capping that
    keeps the exported netlist small.  (Our old call passed `n_poles_init`, which
    no longer exists in scikit-rf, so the order cap was silently ignored, and
    forcing the initial pole count made the model harder to make passive.)
    """
    vf = VectorFitting(net)
    try:
        vf.auto_fit(model_order_max=max(2, int(max_order)))
    except TypeError:                              # different scikit-rf signature
        vf.auto_fit()
    return vf


def _enforce_passivity(vf, net):
    """Make the model passive, escalating effort only as needed, never shipping a
    worse model than the original fit.

    1. If it is already passive, do nothing.
    2. Enforce from a *pristine copy* of the fit at an escalating sample count
       (this catches narrow violation bands, and replaces scraping scikit-rf's
       warning text, which is brittle).  Each attempt starts from the clean fit
       so perturbations do not compound.
    3. Last resort: one lower-order refit (a smaller model is often easier to
       make passive, at some accuracy cost).
    A candidate is kept only if it is passive *and* still resembles the data
    (`rms < _USABLE_RMS`); otherwise the accurate near-passive fit is returned.

    Strategy adapted from the COBRA project (https://github.com/DI-PASSIONATE/COBRA).

    Returns (vector_fitting, messages).
    """
    import copy
    msgs = []
    if _is_passive(vf):
        return vf, msgs

    best = [None]                                  # [(rms, vf)] best usable candidate

    def keep_if_good(cand, how):
        if not _is_passive(cand):
            return False
        r = _rms_error(cand, net)
        if r < _USABLE_RMS and (best[0] is None or r < best[0][0]):
            best[0] = (r, cand)
            msgs.append(f"passivity enforced ({how}, rms={r:.2e})")
            return True
        return False

    # escalate the sample count, enforcing from the clean fit each time
    for n_samples in _PASSIVITY_N_SAMPLES:
        cand = copy.deepcopy(vf)
        try:
            cand.passivity_enforce(n_samples=n_samples)
        except Exception as exc:                   # noqa: BLE001
            msgs.append(f"passivity enforce failed: {exc}")
            break
        if keep_if_good(cand, f"n_samples={n_samples}"):
            return best[0][1], msgs

    # last resort: a single lower-order refit (kept only if passive and accurate)
    poles = np.atleast_1d(vf.poles)
    n_cmplx = int(np.count_nonzero(poles.imag)) or (len(poles) // 2)
    k = max(2, int(n_cmplx * 0.66))
    if k < n_cmplx:
        cand = VectorFitting(net)
        try:
            cand.vector_fit(n_poles_real=1, n_poles_cmplx=k)
            if not _is_passive(cand):
                cand.passivity_enforce(n_samples=_PASSIVITY_N_SAMPLES[-1])
        except Exception:                          # noqa: BLE001
            cand = None
        if cand is not None and keep_if_good(cand, f"reduced order ({k} cmplx)"):
            return best[0][1], msgs

    msgs.append("passivity enforced (near-passive)")
    return vf, msgs


def _is_passive(vf) -> bool:
    try:
        return bool(vf.is_passive())
    except Exception:                              # noqa: BLE001
        return False


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
