# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""universal.py - the universal (any-N-port) macromodel via vector fitting.

Wraps skrf.vectorFitting.VectorFitting: auto-fit the S-parameters, optionally
enforce passivity, emit the SPICE subcircuit, and parse it back into a CircuitIR
so both netlist dialects render from one representation.  Also reconstructs the
fitted S-parameters on any frequency grid for the data-vs-model plots.

Passivity is reported as a number, not only as a flag: `max_singular_value` returns
the largest singular value of the fitted S-matrix over all frequencies, and a fit is
enforced down to the passivity ceiling rather than only to 1 (see PASSIVITY_CEILING_*).

The passivity-enforcement strategy in `_enforce_passivity` (escalate the sample
count, then fall back to a lower model order) was inspired by the COBRA project's
vector-fitting wrapper: https://github.com/DI-PASSIONATE/COBRA
(src/cobra/spice_sim/vector_fit.py).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import io as _io
import contextlib
import math
import threading
import numpy as np

from skrf.vectorFitting import VectorFitting

from .ir import CircuitIR
from .progress import null_progress
from . import netlist as _nl


@dataclass
class FitResult:
    ir: CircuitIR = None
    n_poles: int = 0
    passive: bool = False               # sigma_max <= passivity_ceiling
    sigma_max: float = float("nan")     # largest singular value of the model S-matrix
    sigma_max_freq: float = float("nan")   # where that peak sits [Hz]
    passivity_ceiling: float = 1.0      # sigma_max the fit was judged against
    rms_error: float = float("nan")     # fraction (0..1) over all Sij
    vf: object = None                   # the VectorFitting object
    messages: list = field(default_factory=list)


# Sample counts tried, in order, when enforcing passivity.  Escalating the count
# (rather than scraping scikit-rf's warning text) catches narrow violation bands
# that a low count misses, while staying cheap in the common case.
_PASSIVITY_N_SAMPLES = (200, 800)
# An enforced/reduced model is only accepted if it stays this close to the data.
# Otherwise we keep the accurate (near-passive) fit rather than ship a wreck.
_USABLE_RMS = 0.1

# Passivity ceiling: the largest singular value the enforced model is allowed to keep.
# sigma_max <= 1 is the passivity condition itself (the model can never deliver more
# power than it absorbs, at any frequency), so 1.0 is the strict default.  Enforcing a
# ceiling above 1.0 leaves that much gain at the model's worst frequency and buys back
# accuracy in exchange, since the perturbation has less to correct.  1.2 is the highest
# allowed: past roughly 20 % the excess is large enough to grow a transient run away.
PASSIVITY_CEILING_MIN = 1.0
PASSIVITY_CEILING_DEFAULT = 1.0
PASSIVITY_CEILING_MAX = 1.2

# sigma_max grid: log-spaced points over the model's whole frequency range, plus this
# many extra points inside each violation band scikit-rf reports (the peaks sit there).
_SIGMA_GRID_POINTS = 400
_SIGMA_BAND_POINTS = 64
# The model is evaluated this far outside the fitted band.  A vector fit usually
# violates passivity where it has no data, below the first and above the last sample,
# and a transient run excites exactly those frequencies.
_SIGMA_SPAN_DECADES = 4.0

# How this function's own 0..1 progress splits across its phases.  auto_fit
# dominates, and it dominates harder when passivity enforcement is off, so that
# boundary moves with the flag instead of leaving a dead zone in the bar.  The
# sigma_max sweep gets its own slice: it evaluates the model over a few hundred
# frequencies for every response, so on an N-port it is not a rounding error.
_END_FIT_PASSIVE = 0.60
_END_FIT_PLAIN = 0.80
_END_PASSIVITY = 0.84
_END_SIGMA = 0.92
_END_SCORING = 0.96
_FIT_POLL_S = 0.15              # how often the watcher below samples the fit
_FIT_ITERS_SCALE = 9.0          # iterations at which the reported fraction hits ~2/3
_FIT_MAX_REPORTED = 0.97        # a saturating curve must never claim to be finished


def clamp_passivity_ceiling(value) -> float:
    """A usable passivity ceiling: a number clamped into
    [PASSIVITY_CEILING_MIN, PASSIVITY_CEILING_MAX], or the strict default.

    A readable number outside the range clamps to the edge it overshot, so 9.9 gives
    1.2 and 0.5 gives 1.0.  In the GUI that edge lands straight back in the field, which
    is how someone who has never read the tooltip finds out what the limits are.
    Something that is not a number at all (None, text, NaN) has no edge to clamp to, so
    it returns the strict default instead."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return PASSIVITY_CEILING_DEFAULT
    if v != v:                                     # NaN, no nearest edge to pick
        return PASSIVITY_CEILING_DEFAULT
    return float(min(max(v, PASSIVITY_CEILING_MIN), PASSIVITY_CEILING_MAX))


def effective_ceiling(enforce_passivity: bool,
                      passivity_ceiling=PASSIVITY_CEILING_DEFAULT) -> float:
    """The sigma_max a fit is held under, and judged against.

    The ceiling only means anything while enforcement is running, since it is the value
    the perturbation works towards.  With enforcement off nothing is aimed at, so the
    model is judged against strict passivity and the GUI greys the field out to say so.
    Keeping the rule here means the GUI, the CLI and the engine cannot disagree on it."""
    if not enforce_passivity:
        return PASSIVITY_CEILING_DEFAULT
    return clamp_passivity_ceiling(passivity_ceiling)


def fit_universal(net, max_order: int = 12, enforce_passivity: bool = True,
                  passivity_ceiling: float = PASSIVITY_CEILING_DEFAULT,
                  progress=None) -> FitResult:
    """Vector-fit `net` and synthesise a lumped-element SPICE subcircuit.

    `passivity_ceiling` is the sigma_max the enforcement brings the model down to.  It
    applies only with `enforce_passivity=True`, since it is what the perturbation works
    towards, see `effective_ceiling`.

    `progress` is an optional `cb(fraction, message)` covering this call alone, from 0
    (nothing fitted) to 1 (subcircuit parsed and scored)."""
    report = progress or null_progress
    end_fit = _END_FIT_PASSIVE if enforce_passivity else _END_FIT_PLAIN
    res = FitResult()
    ceiling = res.passivity_ceiling = effective_ceiling(enforce_passivity,
                                                        passivity_ceiling)
    attempted = False
    # These rebind sys.stdout/sys.stderr process-wide, not per thread, and the GUI now
    # runs this on a worker, so the whole application is muted for the duration of the
    # fit.  See doc/architecture.md, "Notes / limitations.
    with contextlib.redirect_stdout(_io.StringIO()), \
            contextlib.redirect_stderr(_io.StringIO()):
        vf = _auto_fit(net, max_order, _span(report, 0.0, end_fit))
        if enforce_passivity:
            vf, msgs, attempted = _enforce_passivity(
                vf, net, ceiling, _span(report, end_fit, _END_PASSIVITY))
            res.messages.extend(msgs)
        report(_END_PASSIVITY, "measuring the passivity margin")
        res.sigma_max, res.sigma_max_freq = max_singular_value(vf)

    report(_END_SIGMA, "scoring the fit")
    res.vf = vf
    res.n_poles = int(len(np.atleast_1d(vf.poles)))
    res.passive = _meets_ceiling(vf, res.sigma_max, ceiling)
    res.rms_error = _rms_error(vf, net)
    # Report the number whenever there is a violation to report, met or not.  A model
    # that is passive outright needs no line.  The frequency comes with it: it is what
    # separates a real hazard from a high-frequency asymptote nothing will excite.
    if res.sigma_max > PASSIVITY_CEILING_MIN:
        from .units import format_eng
        # ASCII here on purpose: this string also goes to a terminal, and a Windows
        # console in cp1252 renders a Greek sigma as '?'.  The GUI swaps in the symbol
        # when it draws the line (widgets.with_symbols).
        where = (f"sigma_max {res.sigma_max:.3f} at "
                 f"{format_eng(res.sigma_max_freq, 'Hz')}")
        if enforce_passivity and not attempted:
            # The ceiling was never binding.  Say so, or the reading is "I asked for
            # 1.20 and got 1.019", when the answer is that nothing needed correcting.
            res.messages.append(
                f"{where} is already below the ceiling {ceiling:.2f}, "
                f"fit left untouched")
        else:
            res.messages.append(
                f"{where}, {'below' if res.passive else 'ABOVE'} "
                f"ceiling {ceiling:.2f}")

    report(_END_SCORING, "synthesising the subcircuit")
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
    # Condition the realisation (both passes are lossless, so the transfer function and the
    # Ngspice result are unchanged).  rescale_state_resistors lifts the sub-1e-12 state
    # self-resistors to O(1) ohms (clamping them instead corrupts S11/S22 at higher orders),
    # and balance_state_gains equilibrates the tiny input and huge output controlled sources.
    # Together they keep VACASK (which has no internal matrix scaling) accurate well past the
    # order-5 point where the raw realisation otherwise mis-places the resonances.
    res.ir = _nl.balance_state_gains(_nl.rescale_state_resistors(
        _nl.parse_spice_subckt(spice_text, name="s_equivalent"), target=1.0))
    report(1.0, f"{res.n_poles} poles, rms {res.rms_error:.2e}")
    return res


def _span(report, lo, hi):
    """A `cb(fraction, message)` that maps a phase's own 0..1 onto [lo, hi]."""
    def scaled(fraction, message=""):
        report(lo + (hi - lo) * min(1.0, max(0.0, float(fraction))), message)
    return scaled


@contextlib.contextmanager
def _fit_watch(vf, report):
    """Report auto_fit's progress from the fit's own iteration history.

    auto_fit is one blocking call with no callback, but it appends to
    `vf.d_res_history` once per pole-relocation iteration.  Polling that list is a real
    progress signal and needs no log scraping, which is the brittle route
    `_enforce_passivity` already avoids.  The iteration count is not known in advance
    (that is the point of auto_fit), so the fraction follows a saturating curve and
    stops short of 1 rather than pretending to know."""
    stop = threading.Event()

    def loop():
        while not stop.wait(_FIT_POLL_S):
            n = len(getattr(vf, "d_res_history", None) or ())
            frac = min(_FIT_MAX_REPORTED, 1.0 - math.exp(-n / _FIT_ITERS_SCALE))
            report(frac, f"vector fitting, {n} iteration{'' if n == 1 else 's'}")

    watcher = threading.Thread(target=loop, name="snp2le-fit-watch", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        stop.set()
        watcher.join(timeout=1.0)


# Model order of auto_fit's default initial pole set, 3 real + 3 complex.  Kept as a
# number rather than read from the signature because scikit-rf's defaults are part of
# its API, and a mismatch here only costs the clamp below, never correctness.
_AUTO_FIT_INIT_ORDER = 3 + 2 * 3


def _auto_fit(net, max_order: int, report=null_progress):
    """Run scikit-rf auto_fit with the model order bounded by `max_order`.

    auto_fit grows the model adaptively up to `model_order_max`, so capping that
    keeps the exported netlist small.  (Our old call passed `n_poles_init`, which
    no longer exists in scikit-rf, so the order cap was silently ignored, and
    forcing the initial pole count made the model harder to make passive.)

    Below scikit-rf 1.12 `model_order_max` is only the exit test of the growth loop,
    never applied to the pole set auto_fit starts from.  That default set is 3 real
    plus 3 complex poles, model order 9, so any cap under 9 leaves the loop unentered
    and the model at order 9 whatever the user asked for (issue #7: max order 6 came
    back as 7 poles).  Passing the initial counts 1.12 would compute itself makes the
    older versions behave like 1.12, and is inert on 1.12, which clamps to the same
    two numbers.  It is skipped when the default set already fits, so the growth path
    at higher orders is untouched.
    """
    vf = VectorFitting(net)
    order = max(2, int(max_order))
    kwargs = {"model_order_max": order}
    if _AUTO_FIT_INIT_ORDER > order:
        kwargs.update(n_poles_init_real=order % 2, n_poles_init_cmplx=order // 2)
    report(0.0, "vector fitting")
    with _fit_watch(vf, report):
        try:
            vf.auto_fit(**kwargs)
        except TypeError:                          # different scikit-rf signature
            vf.auto_fit()
    report(1.0, "vector fitting done")
    return vf


def _enforce_at(vf, ceiling: float, n_samples: int):
    """Perturb `vf` in place until sigma_max <= `ceiling`.

    scikit-rf's `passivity_enforce` only knows the strict condition sigma_max <= 1, but
    sigma_max(S) <= t is exactly sigma_max(S/t) <= 1.  So scale the rational model down
    by t, run the standard singular-value perturbation, and scale back.  At t = 1.0 both
    scalings are the identity and this is `passivity_enforce` untouched, which is what
    keeps the strict path bit-for-bit what it was.

    Scaling every term keeps it one rational function: S(s) = D + sum_k R_k / (s - p_k),
    so dividing D and every R_k by t divides S by t at every frequency, poles unmoved."""
    if ceiling != 1.0:
        for attr in ("residues", "constant_coeff", "proportional_coeff"):
            setattr(vf, attr, getattr(vf, attr) / ceiling)
    vf.passivity_enforce(n_samples=n_samples)
    if ceiling != 1.0:
        for attr in ("residues", "constant_coeff", "proportional_coeff"):
            setattr(vf, attr, getattr(vf, attr) * ceiling)
    return vf


def _enforce_passivity(vf, net, ceiling: float = PASSIVITY_CEILING_DEFAULT,
                       report=null_progress):
    """Bring the model's sigma_max down to `ceiling`, escalating effort only as needed,
    never shipping a worse model than the original fit.

    1. If it already sits below the ceiling, do nothing.
    2. Enforce from a *pristine copy* of the fit at an escalating sample count
       (this catches narrow violation bands, and replaces scraping scikit-rf's
       warning text, which is brittle).  Each attempt starts from the clean fit
       so perturbations do not compound.
    3. Last resort: one lower-order refit (a smaller model is often easier to
       make passive, at some accuracy cost).
    A candidate is kept only if it clears the ceiling *and* still resembles the data
    (`rms < _USABLE_RMS`).  Otherwise the accurate near-passive fit is returned.  That
    guard matters more at a raised ceiling, not less: a model whose violation band runs
    to infinity cannot be fixed by perturbing residues at any ceiling, and without the
    guard the failed attempt would be shipped in place of a good fit.

    Strategy adapted from the COBRA project (https://github.com/DI-PASSIONATE/COBRA).

    Returns (vector_fitting, messages, attempted).  `attempted` is False only when the
    fit already sat below the ceiling and was handed straight back, and it is True on
    every path that ran the perturbation, including the near-passive one that ran it and
    kept the original anyway.  The caller reports the False case differently, because
    "nothing needed doing" is the answer to "why did my ceiling of 1.20 leave the model
    at 1.019", and the near-passive case must not borrow that wording: there the ceiling
    was missed, not unneeded.
    """
    import copy
    msgs = []
    report(0.0, "checking passivity")
    if _meets_ceiling(vf, None, ceiling):
        report(1.0, "already below the ceiling")
        return vf, msgs, False   # nothing to do

    best = [None]                                  # [(rms, vf)] best usable candidate
    at = "" if ceiling <= PASSIVITY_CEILING_MIN else f" at {ceiling:.2f}"

    def keep_if_good(cand, how):
        if not _meets_ceiling(cand, None, ceiling):
            return False
        r = _rms_error(cand, net)
        if r < _USABLE_RMS and (best[0] is None or r < best[0][0]):
            best[0] = (r, cand)
            msgs.append(f"passivity enforced{at} ({how}, rms={r:.2e})")
            return True
        return False

    # escalate the sample count, enforcing from the clean fit each time
    for i, n_samples in enumerate(_PASSIVITY_N_SAMPLES):
        report(i / (len(_PASSIVITY_N_SAMPLES) + 1),
               f"enforcing passivity, {n_samples} samples")
        cand = copy.deepcopy(vf)
        try:
            _enforce_at(cand, ceiling, n_samples)
        except Exception as exc:                   # noqa: BLE001
            msgs.append(f"passivity enforce failed: {exc}")
            break
        if keep_if_good(cand, f"n_samples={n_samples}"):
            return best[0][1], msgs, True

    # last resort: a single lower-order refit (kept only if it clears the ceiling)
    poles = np.atleast_1d(vf.poles)
    n_cmplx = int(np.count_nonzero(poles.imag)) or (len(poles) // 2)
    k = max(2, int(n_cmplx * 0.66))
    if k < n_cmplx:
        report(len(_PASSIVITY_N_SAMPLES) / (len(_PASSIVITY_N_SAMPLES) + 1),
               f"refitting at a lower order ({k} complex poles)")
        cand = VectorFitting(net)
        try:
            cand.vector_fit(n_poles_real=1, n_poles_cmplx=k)
            if not _meets_ceiling(cand, None, ceiling):
                _enforce_at(cand, ceiling, _PASSIVITY_N_SAMPLES[-1])
        except Exception:                          # noqa: BLE001
            cand = None
        if cand is not None and keep_if_good(cand, f"reduced order ({k} cmplx)"):
            return best[0][1], msgs, True

    msgs.append("passivity enforced (near-passive)")
    return vf, msgs, True


def _is_passive(vf) -> bool:
    try:
        return bool(vf.is_passive())
    except Exception:                              # noqa: BLE001
        return False


def _meets_ceiling(vf, sigma_max, ceiling: float) -> bool:
    """Does the model sit at or below `ceiling`?

    At the strict ceiling scikit-rf's eigenvalue test decides, because it is exact and
    finds violation bands too narrow for any sampled grid to see.  Above it the sampled
    sigma_max is what the question is about, and a peak narrow enough for the grid to
    miss carries no energy worth refusing a fit over.

    `sigma_max` may be None, which measures it here.  Callers that already have the
    number pass it in, since the measurement is the expensive half."""
    if _is_passive(vf):
        return True
    if ceiling <= PASSIVITY_CEILING_MIN:
        return False
    if sigma_max is None:
        sigma_max = max_singular_value(vf)[0]
    return bool(sigma_max == sigma_max and sigma_max <= ceiling)


def max_singular_value(vf):
    """(sigma_max, f_hz): the largest singular value of the fitted S-matrix over all
    frequencies, and where it occurs.

    sigma_max <= 1 is exactly the passivity condition, so this number says how far a
    model misses it (1.03 means 3 % of gain at its worst frequency) where `is_passive`
    only says that it does.  The frequency is worth reporting with it: a peak at DC or
    inside the fitted band is a real hazard for a transient run, while one out at
    10^4 times the top data point is the model's high-frequency asymptote and usually
    means the fit order is too high for the file.  Returns (NaN, NaN) if the model
    cannot be evaluated."""
    try:
        grid = _sigma_grid(vf)
        n = int(vf.network.nports)
        s = np.empty((len(grid), n, n), dtype=complex)
        for i in range(n):
            for j in range(n):
                s[:, i, j] = vf.get_model_response(i, j, grid)
        ok = np.isfinite(s).all(axis=(1, 2))       # one bad point must not void them all
        if not ok.any():
            return float("nan"), float("nan")
        grid, s = grid[ok], s[ok]
        per_f = np.max(np.linalg.svd(s, compute_uv=False), axis=1)
        k = int(np.argmax(per_f))
        return float(per_f[k]), float(grid[k])
    except Exception:                              # noqa: BLE001
        return float("nan"), float("nan")


def _sigma_grid(vf):
    """Frequencies at which sigma_max is sampled.

    DC, the data points, a log sweep _SIGMA_SPAN_DECADES either side of the data, and a
    dense sweep inside every passivity-violation band the half-size test matrix reports,
    since the peaks sit there.  A band left open at the top is closed at the top of the
    log sweep, where the model has already settled on its constant term."""
    f = np.asarray(vf.network.f, dtype=float)
    f = f[f > 0]
    if f.size == 0:
        return np.array([0.0])
    lo = f[0] * 10.0 ** -_SIGMA_SPAN_DECADES
    hi = f[-1] * 10.0 ** _SIGMA_SPAN_DECADES
    parts = [np.array([0.0]), f,
             np.logspace(np.log10(lo), np.log10(hi), _SIGMA_GRID_POINTS)]
    try:
        bands = np.atleast_2d(vf.passivity_test())
    except Exception:                              # noqa: BLE001
        bands = np.empty((0, 2))
    for band in bands:
        if band.size != 2:                         # no violation: an empty (1, 0) row
            continue
        b_lo, b_hi = float(band[0]), float(band[1])
        if not np.isfinite(b_hi):                  # the band is open at the top
            b_hi = max(hi, b_lo * 10.0)
        if b_hi > b_lo:
            parts.append(np.linspace(b_lo, b_hi, _SIGMA_BAND_POINTS))
    return np.unique(np.concatenate(parts))


def model_sparams(vf, freq_hz, progress=None):
    """Reconstruct the fitted S-parameters S[f, i, j] on a frequency grid.

    One model evaluation per response, so an 8-port costs 64 of them and is worth
    reporting per response rather than as one silent block."""
    f = np.asarray(freq_hz, dtype=float)
    n = vf.network.nports
    S = np.zeros((len(f), n, n), dtype=complex)
    for i in range(n):
        for j in range(n):
            if progress is not None:
                done = i * n + j
                progress(done / (n * n), f"model response S{i + 1}{j + 1}")
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
