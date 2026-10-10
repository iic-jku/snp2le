# SPDX-FileCopyrightText: 2026 Volker Muehlhaus
# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""structures/inductor_fit.py - wideband fit of an RFIC inductor model.

Ported from Volker Muehlhaus' inductor_fit (https://github.com/VolkerMuehlhaus/lumpedmodel),
used here under Apache-2.0 with his permission.  The fit runs without an extraction
frequency: analytic seed values from the pi (2-port) or delta (3-port) decomposition of the
Y-parameters, then a global least-squares fit of the complete model over the band up to
SRF_FIT_FACTOR x the self-resonance frequency.

2-port model, 1 coil segment:

    p1 --+-- Rs -- Ls -- (Rskin1 || Lskin1) -- (Rskin2 || Lskin2) --+-- p2
         +------------------------- Cs ------------------------------+
    p1 -- Cox1 -- s1 -- Rsi1 || Csi1 -- gnd,  p2 -- Cox2 -- s2 -- Rsi2 || Csi2 -- gnd
    s1 -- Rsub12 || Csub12 -- s2  (only when needed and physically plausible)

Center-tapped 3-port model (ports p1, p2, ct): two half coils p1 -> m -> p2, each with Rs, Ls
and the skin sections, Ls_h1 and Ls_h2 coupled with k, Cs across the whole coil, Rct from m
to ct, and a Cox-(Rsi||Csi) network at p1, m and p2.

Electrically long coils are split into 1 to 3 equal segments with the substrate network
distributed over the coil nodes.  Element values are always totals over the segments.  With
`basic=True` the topology is fixed (1 segment, 1 skin section, no substrate coupling), so
every fit has the same elements, e.g. for machine-learning data tables.

Pure numpy/scipy, no Qt and no file output: the Structure classes in inductor_wideband.py
turn an InductorFit into a CircuitIR.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math

import numpy as np
from scipy.optimize import least_squares

# weights of the error function terms used in the global fit
W_Y = 1.0         # complex Y11, Y22 and series branch -Y12 (relative error)
W_SHUNT = 1.0     # complex shunt branches Y11+Y12 and Y22+Y12 (relative error)
W_SHUNT_RE = 0.5  # real part of the shunt branches = substrate loss (relative error)
W_L = 0.5         # single-ended L11/L22 and differential L (relative error)
W_Q = 0.5         # single-ended Q11/Q22 and differential Q (relative error)
W_CORNER = 1.0    # penalty per decade of a skin section corner frequency below the fit band

SRF_FIT_FACTOR = 1.2   # the fit band stops at this factor times the SRF of the data
LQ_SRF_FACTOR = 0.8    # L and Q goals only below this factor times SRF (they diverge at SRF)
NUM_RANDOM_STARTS = 2  # additional global fit runs from randomly perturbed seed values
MAX_NFEV = 200         # cap per global fit run, the last iterations crawl along flat valleys
SEGMENT_CHOICES = (1, 2, 3)
SEGMENT_COST_TOLERANCE = 1.1    # fewest segments with cost within this factor of the best
SUBSTRATE_COST_TOLERANCE = 1.1  # simplest substrate variant within this factor of the best
SYMMETRY_TOLERANCE = 0.05       # symmetric model if port/half responses differ by less (RMS)
COX_SPAN = 0.5                  # Cox bound in decades around its low-frequency seed
MIN_FIT_POINTS = 10

# Substrate network variants (symmetric = port 2 tied to port 1, coupling = Rsub12||Csub12),
# simple to complex.  With coupling the network is not always unique: a "shared substrate"
# solution can fit as well without being physical, so coupling must pass a plausibility check.
SUBSTRATE_VARIANTS = {"symmetric": (True, False), "asymmetric": (False, False),
                      "symmetric+coupling": (True, True), "asymmetric+coupling": (False, True)}

PARAM_NAMES = ["Rs", "Ls", "Rskin1", "Lskin1", "Rskin2", "Lskin2", "Cs",
               "Cox1", "Rsi1", "Csi1", "Cox2", "Rsi2", "Csi2",
               "Rsub12", "Csub12"]
CT_HALF = ["Rs", "Ls", "Rskin1", "Lskin1", "Rskin2", "Lskin2"]
CT_PARAM_NAMES = ([n + "_h1" for n in CT_HALF] + [n + "_h2" for n in CT_HALF]
                  + ["k", "Cs", "Rct", "Cox1", "Rsi1", "Csi1", "Cox2", "Rsi2", "Csi2",
                     "Coxct", "Rsict", "Csict"])
K_BOUNDS = (math.log10(0.01), math.log10(0.99))   # coupling coefficient k, log10
X_SKIN2_FIXED = (0.0, -30.0)   # log10 of Rskin2 = 1 Ohm, Lskin2 = 1e-30 H: section 2 shorted
X_COUPLING_OFF = {"Rsub12": 15.0, "Csub12": -30.0}  # log10: 1e15 Ohm (open), 1e-30 F

# the fraction of the progress bar the seed values take, the global fit runs share the rest
_SEED_SHARE = 0.05


@dataclass
class InductorFit:
    """Result of fit_two_port / fit_center_tap.  Element values are totals over segments."""
    values: dict                 # element name -> value, every parameter of the model
    active: list                 # names of the elements in the model (fixed ones removed)
    segments: int                # coil segments (per half coil for the center-tapped model)
    num_skin: int                # skin sections per coil (1 basic, 2 full)
    coupling: bool = False       # 2-port: Rsub12 || Csub12 is part of the model
    basic: bool = False
    f_fit: tuple = (0.0, 0.0)    # fit band actually used [Hz]
    cost: float = float("nan")   # weighted error function of the selected model
    metrics: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)


# ---------------- model elements ----------------

def z_skin_branch(Rskin, Lskin, omega):
    # Rskin || Lskin: jwLskin well below the corner (internal inductance), Rskin well above
    # it (AC resistance), which models the skin and proximity effect
    return (Rskin * 1j * omega * Lskin) / (Rskin + 1j * omega * Lskin)


def z_coil(Rs, Ls, Rskin1, Lskin1, Rskin2, Lskin2, omega):
    return (Rs + 1j * omega * Ls + z_skin_branch(Rskin1, Lskin1, omega)
            + z_skin_branch(Rskin2, Lskin2, omega))


def y_shunt_branch(Cox, Rsi, Csi, omega):
    yox = 1j * omega * Cox                        # Cox in series with Rsi || Csi
    ysi = 1.0 / Rsi + 1j * omega * Csi
    return yox * ysi / (yox + ysi)


def shunt_weights(segments):
    """Share of the port 1 (a) and port 2 (b) shunt elements at each of the segments+1 coil
    nodes: trapezoidal along the coil, blended linearly from the port 1 to the port 2 values.
    One segment puts the port 1 network fully at p1 and the port 2 network fully at p2."""
    k = np.arange(segments + 1)
    trapezoid = np.where((k == 0) | (k == segments), 0.5, 1.0) / segments
    return 2 * trapezoid * (1 - k / segments), 2 * trapezoid * k / segments


# ---------------- nodal analysis ----------------

def _new_nodal(omega, num_nodes):
    return np.zeros((len(omega), num_nodes, num_nodes), dtype=complex)


def _stamp(M, n1, n2, y):
    """Two-terminal admittance y between nodes n1 and n2 (None = ground)."""
    M[:, n1, n1] += y
    if n2 is not None:
        M[:, n2, n2] += y
        M[:, n1, n2] -= y
        M[:, n2, n1] -= y


def _stamp_coupled(M, branches, Zb):
    """Magnetically coupled branches with impedance matrix Zb (N, b, b) between the node
    pairs in `branches`, stamped as A inv(Zb) A^T with the incidence matrix A."""
    A = np.zeros((M.shape[1], len(branches)))
    for b, (n1, n2) in enumerate(branches):
        A[n1, b], A[n2, b] = 1.0, -1.0
    M += np.einsum("ib,fbc,jc->fij", A, np.linalg.inv(Zb), A)


def _kron_reduce(M, ports):
    """Eliminate all internal nodes: Y = Ypp - Ypi inv(Yii) Yip."""
    internal = [n for n in range(M.shape[1]) if n not in ports]
    Mpp = M[:, ports][:, :, ports]
    Mpi = M[:, ports][:, :, internal]
    Mip = M[:, internal][:, :, ports]
    Mii = M[:, internal][:, :, internal]
    return Mpp - Mpi @ np.linalg.solve(Mii, Mip)


# ---------------- 2-port model ----------------

def segment_shunt_values(p, segments):
    """Cox, Rsi, Csi at each coil node, from the total port 1 / port 2 values."""
    Cox1, Rsi1, Csi1, Cox2, Rsi2, Csi2 = p[7:13]
    a, b = shunt_weights(segments)
    return a * Cox1 + b * Cox2, 1.0 / (a / Rsi1 + b / Rsi2), a * Csi1 + b * Csi2


def y_model(p, omega, segments):
    """2-port Y (N, 2, 2) of the model with parameters `p` in PARAM_NAMES order.  Coil nodes
    0..segments (0 = p1, segments = p2), one substrate node per coil node, all internal nodes
    eliminated.  Also valid at DC (Cox open, inductors short)."""
    Cs, Rsub12, Csub12 = p[6], p[13], p[14]
    num_coil = segments + 1
    M = _new_nodal(omega, 2 * num_coil)
    y_cell = segments / z_coil(*p[:6], omega)
    for k in range(segments):
        _stamp(M, k, k + 1, y_cell)
    _stamp(M, 0, segments, 1j * omega * Cs)
    Cox, Rsi, Csi = segment_shunt_values(p, segments)
    for k in range(num_coil):
        _stamp(M, k, num_coil + k, 1j * omega * Cox[k])
        _stamp(M, num_coil + k, None, 1.0 / Rsi[k] + 1j * omega * Csi[k])
    _stamp(M, num_coil, num_coil + segments, 1.0 / Rsub12 + 1j * omega * Csub12)
    return _kron_reduce(M, [0, segments])


# ---------------- center-tapped model ----------------

def ct_node_shunt_values(p, segments):
    """Cox, Rsi, Csi at the 2*segments+1 coil nodes.  Half 1 blends from the p1 to the
    center tap network, half 2 from the center tap to the p2 network, and each half carries
    one half of the center tap network."""
    d = dict(zip(CT_PARAM_NAMES, p))
    a, b = shunt_weights(segments)
    w1, wm, w2 = np.zeros((3, 2 * segments + 1))
    w1[:segments + 1] += a
    wm[:segments + 1] += b / 2
    wm[segments:] += a / 2
    w2[segments:] += b
    Cox = w1 * d["Cox1"] + wm * d["Coxct"] + w2 * d["Cox2"]
    Rsi = 1.0 / (w1 / d["Rsi1"] + wm / d["Rsict"] + w2 / d["Rsi2"])
    Csi = w1 * d["Csi1"] + wm * d["Csict"] + w2 * d["Csi2"]
    return Cox, Rsi, Csi


def ct_inductance_matrix(p, segments):
    """Inductance matrix of the 2*segments cell inductors (half 1 first): Ls/segments per
    cell, M/segments^2 between cells of opposite halves, M = k sqrt(Ls_h1 Ls_h2), aiding for
    differential current p1 -> m -> p2."""
    d = dict(zip(CT_PARAM_NAMES, p))
    n = segments
    Lmat = np.zeros((2 * n, 2 * n))
    Lmat[:n, n:] = Lmat[n:, :n] = d["k"] * math.sqrt(d["Ls_h1"] * d["Ls_h2"]) / n ** 2
    Lmat[np.arange(n), np.arange(n)] = d["Ls_h1"] / n
    Lmat[np.arange(n, 2 * n), np.arange(n, 2 * n)] = d["Ls_h2"] / n
    return Lmat


def y_model_ct(p, omega, segments):
    """3-port Y (N, 3, 3, ports p1, p2, ct) of the center-tapped model.  Coil nodes
    0..2*segments (0 = p1, segments = m, 2*segments = p2), then ct, then one substrate node
    per coil node.  Also valid at DC."""
    d = dict(zip(CT_PARAM_NAMES, p))
    n = segments
    num_coil = 2 * n + 1
    ct = num_coil
    M = _new_nodal(omega, 2 * num_coil + 1)
    z_rest = {h: (d["Rs" + h] + z_skin_branch(d["Rskin1" + h], d["Lskin1" + h], omega)
                  + z_skin_branch(d["Rskin2" + h], d["Lskin2" + h], omega)) / n
              for h in ("_h1", "_h2")}
    Zb = 1j * omega[:, None, None] * ct_inductance_matrix(p, n)
    for b in range(2 * n):
        Zb[:, b, b] += z_rest["_h1" if b < n else "_h2"]
    _stamp_coupled(M, [(b, b + 1) for b in range(2 * n)], Zb)
    _stamp(M, 0, 2 * n, 1j * omega * d["Cs"])
    _stamp(M, n, ct, 1.0 / d["Rct"])
    Cox, Rsi, Csi = ct_node_shunt_values(p, n)
    for k in range(num_coil):
        _stamp(M, k, ct + 1 + k, 1j * omega * Cox[k])
        _stamp(M, ct + 1 + k, None, 1.0 / Rsi[k] + 1j * omega * Csi[k])
    return _kron_reduce(M, [0, 2 * n, ct])


# ---------------- derived quantities (same for data and model) ----------------

def pi_branches(Y):
    """Exact pi decomposition of any 2-port: shunt at port 1, shunt at port 2, series."""
    y12 = (Y[:, 0, 1] + Y[:, 1, 0]) / 2
    return Y[:, 0, 0] + y12, Y[:, 1, 1] + y12, -y12


def y_diff(Y):
    """Differential admittance between port 1 and port 2 with floating ground, equal to
    1/(z11 - z12 - z21 + z22) without inverting a near-singular Y at low frequency."""
    det = Y[:, 0, 0] * Y[:, 1, 1] - Y[:, 0, 1] * Y[:, 1, 0]
    return det / (Y[:, 0, 0] + Y[:, 1, 1] + Y[:, 0, 1] + Y[:, 1, 0])


def l_and_q(Yin, omega):
    Zin = 1.0 / Yin
    return Zin.imag / omega, Zin.imag / Zin.real


def find_srf(f, Yin):
    """First frequency where Im(Yin) turns from inductive (negative) to capacitive, linearly
    interpolated between the samples.  None when it never does."""
    crossings = np.where(np.diff(np.sign(Yin.imag)) > 0)[0]
    if len(crossings) == 0:
        return None
    i0 = crossings[0]
    im_lo, im_hi = Yin.imag[i0], Yin.imag[i0 + 1]
    return float(f[i0] + (f[i0 + 1] - f[i0]) * (-im_lo) / (im_hi - im_lo))


def ct_open_2port(Y):
    """p1/p2 2-port of a 3-port (p1, p2, ct) with the ct port left open."""
    return Y[:, :2, :2] - Y[:, :2, 2:3] * Y[:, 2:3, :2] / Y[:, 2:3, 2:3]


def ct_quantities(Y, omega):
    """Responses of a center-tapped inductor (ports p1, p2, ct), for data and model."""
    def sym(i, j):
        return (Y[:, i, j] + Y[:, j, i]) / 2
    B12, B13, B23 = -sym(0, 1), -sym(0, 2), -sym(1, 2)   # delta decomposition: branches
    S1 = Y[:, 0, 0] - B12 - B13                          # and shunts (row sums)
    S2 = Y[:, 1, 1] - B12 - B23
    S3 = Y[:, 2, 2] - B13 - B23
    Ydd_gnd = y_diff(Y[:, :2, :2])         # differential, center tap AC grounded
    Ydd_open = y_diff(ct_open_2port(Y))    # differential, center tap open
    q = dict(Y=Y, Y11=Y[:, 0, 0], Y22=Y[:, 1, 1], Y33=Y[:, 2, 2], B12=B12, B13=B13, B23=B23,
             S1=S1, S2=S2, S3=S3, ReS1=S1.real, ReS2=S2.real, ReS3=S3.real,
             Ydd_gnd=Ydd_gnd, Ydd_open=Ydd_open)
    # L, Q: differential (ct grounded / open), common mode at ct, single-ended
    for key, Yin in (("dd_gnd", Ydd_gnd), ("dd_open", Ydd_open), ("cm", Y[:, 2, 2]),
                     ("11", Y[:, 0, 0]), ("22", Y[:, 1, 1])):
        q["L" + key], q["Q" + key] = l_and_q(Yin, omega)
    return q


# ---------------- error function ----------------

def _floored_norm(x):
    """Per-point |x|, floored at 10 % of its RMS, so relative errors where the data passes
    through or near zero do not dominate the fit."""
    mag = np.abs(x)
    return np.maximum(mag, 0.1 * np.sqrt(np.mean(mag ** 2)))


def _complex_residual(model, meas, norm, weight):
    diff = (model - meas) / norm
    return np.concatenate([weight * diff.real, weight * diff.imag]) / math.sqrt(len(meas))


def _real_residual(model, meas, norm, weight):
    return weight * (model - meas) / norm / math.sqrt(len(meas))


def _make_goals(meas_fit, goal_list):
    """Fit goals (quantity, weight, mask into the fit band, normalization).  A goal with
    fewer than 3 points is skipped (SRF close to the low end of the band)."""
    goals = []
    for key, w, mask in goal_list:
        if np.count_nonzero(mask) < 3:
            continue
        goals.append((key, w, mask, _floored_norm(meas_fit[key][mask])))
    return goals


def _goal_residuals(model, meas_fit, goals):
    res = []
    for key, w, mask, norm in goals:
        if np.iscomplexobj(meas_fit[key]):
            res.append(_complex_residual(model[key][mask], meas_fit[key][mask], norm, w))
        else:
            res.append(_real_residual(model[key][mask], meas_fit[key][mask], norm, w))
    return np.concatenate(res)


def _corner_penalty(names, x, f_low):
    """Soft constraint: skin section corners Rskin/(2 pi Lskin) not below the fit band.  A
    corner below the data is not determined by it, and one far below makes the DC resistance
    too low and the DC inductance far too high."""
    viol = [max(0.0, math.log10(2 * math.pi * f_low) - (x[i] - x[names.index("L" + name[1:])]))
            for i, name in enumerate(names) if name.startswith("Rskin")]
    return W_CORNER * np.array(viol)


def _rel_difference(a, b):
    """RMS difference of two responses relative to their mean (the symmetry check)."""
    return math.sqrt(np.mean(np.abs(a - b) ** 2) / np.mean(np.abs((a + b) / 2) ** 2))


# ---------------- fitting machinery (on log10 of the element values) ----------------

def _make_variant(names, x_base_seed, span, fixed, ties, bounds_override=None, **info):
    """Free, tied (symmetric: tied value = source value) and fixed parameters (e.g. skin
    section 2 in the basic model), with seed and bounds."""
    x_seed = x_base_seed.copy()
    for dst, src in ties.items():                 # symmetric seed: geometric mean of both
        x_seed[[names.index(src), names.index(dst)]] = (
            x_base_seed[names.index(src)] + x_base_seed[names.index(dst)]) / 2
    lower, upper = x_seed - span, x_seed + span
    for i, name in enumerate(names):
        if name.startswith("Lskin"):
            upper[i] = min(upper[i], -6)          # Lskin <= 1 uH
    for name, (lo, up) in (bounds_override or {}).items():
        lower[names.index(name)], upper[names.index(name)] = lo, up
        x_seed[names.index(name)] = np.clip(x_seed[names.index(name)], lo + 1e-3, up - 1e-3)
    for fixed_name, value in fixed.items():
        x_seed[names.index(fixed_name)] = value
    free = np.array([n not in fixed and n not in ties for n in names])
    return dict(names=names, fixed=fixed, ties=ties, free=free, x_seed=x_seed, lower=lower,
                upper=upper, **info)


def _expand(variant, x_free):
    """Full log10 parameter vector from the free parameters of a variant."""
    names = variant["names"]
    x = variant["x_seed"].copy()
    x[variant["free"]] = x_free
    for dst, src in variant["ties"].items():
        x[names.index(dst)] = x[names.index(src)]
    return x


def _runs(n_extra):
    """Global fit runs of one _fit_variant call with n_extra starts from earlier fits."""
    return 1 + n_extra + NUM_RANDOM_STARTS


def _fit_variant(variant, residual_fn, extra_starts, tick, label):
    """Best fit over all starts as (cost, full log10 parameter vector).  extra_starts are
    full parameter vectors from previous fits.  The random seed is fixed, so a fit is
    reproducible."""
    free = variant["free"]
    lo, up = variant["lower"][free], variant["upper"][free]

    def clip(x):
        return np.clip(x, lo + 1e-6, up - 1e-6)

    rng = np.random.default_rng(0)
    x0_seed = clip(variant["x_seed"][free])
    starts = ([x0_seed] + [clip(x[free]) for x in extra_starts]
              + [clip(x0_seed + rng.normal(0, 0.3, len(x0_seed)))
                 for _ in range(NUM_RANDOM_STARTS)])
    best = None
    for i, x0 in enumerate(starts):
        res = least_squares(lambda x_free: residual_fn(_expand(variant, x_free)), x0=x0,
                            bounds=(lo, up), method="trf", x_scale=1.0, max_nfev=MAX_NFEV,
                            ftol=1e-6)
        if best is None or res.cost < best.cost:
            best = res
        tick(f"fitting {label}, start {i + 1} of {len(starts)}")
    return best.cost, _expand(variant, best.x)


def _fit_segments(variant, residual_fn_for, segment_choices, tick):
    """Fit with each number of coil segments.  Values are totals, so the fit with fewer
    segments is a good extra start for more.  Returns all results and the fewest segments
    whose cost is within SEGMENT_COST_TOLERANCE of the best."""
    results = {}
    for n in segment_choices:
        extra = [results[max(results)][1]] if results else []
        results[n] = _fit_variant(variant, residual_fn_for(n), extra, tick,
                                  f"{n} coil segment{'' if n == 1 else 's'}")
    min_cost = min(cost for cost, _ in results.values())
    segments = min(n for n, (cost, _) in results.items()
                   if cost <= SEGMENT_COST_TOLERANCE * min_cost)
    return results, segments


def _sort_skin_sections(names, arrays, suffix=""):
    """Order the two skin sections by corner frequency (section 1 = lower corner), in all
    arrays (fit result, bounds, seeds) together."""
    i1, i2 = names.index("Rskin1" + suffix), names.index("Rskin2" + suffix)

    def corner(x, i):
        return x[i] - x[i + 1]                    # log10(Rskin/Lskin), monotonic in corner f

    if corner(arrays[0], i1) > corner(arrays[0], i2):
        for arr in arrays:
            arr[[i1, i1 + 1, i2, i2 + 1]] = arr[[i2, i2 + 1, i1, i1 + 1]]


class _Ticker:
    """Progress over a known number of global fit runs, after the seed stage."""

    def __init__(self, callback, total_runs):
        self._cb = callback
        self._total = max(1, total_runs)
        self._done = 0

    def start(self, message):
        if self._cb is not None:
            self._cb(0.0, message)

    def __call__(self, message):
        self._done += 1
        if self._cb is not None:
            self._cb(_SEED_SHARE + (1.0 - _SEED_SHARE) * self._done / self._total, message)


# ---------------- analytic seed values ----------------

def _seed_series(Yser, omega, fit_mask, num_skin_sections):
    """Staged fit of R-L(+skin)||Cs to a series branch on log parameters.  Returns Rs, Ls,
    Rskin1, Lskin1, Rskin2, Lskin2, Cs."""
    series_free = np.array([num_skin_sections == 2 or name not in ("Rskin2", "Lskin2")
                            for name in PARAM_NAMES[:7]])
    omega_fit = omega[fit_mask]
    f_fit = omega_fit / (2 * math.pi)
    Zser = 1.0 / Yser
    i0 = int(np.argmax(fit_mask))                 # first point of the fit band
    Rs0 = max(Zser.real[i0], 1e-3)
    Ls0 = max(np.median(Zser.imag[i0:i0 + 3] / omega[i0:i0 + 3]), 1e-12)

    def y_series_branch(p_series, omega):
        return 1.0 / z_coil(*p_series[:6], omega) + 1j * omega * p_series[6]

    def series_residuals_rlc(logp, omega, y_data):
        R, L, C = 10 ** logp
        model = y_series_branch([R, L, 1.0, 1e-20, 1.0, 1e-20, C], omega)   # skin shorted
        return _complex_residual(model, y_data, _floored_norm(y_data), 1.0)

    def series_residuals_skin(x_free, x_template, omega, y_data):
        x = x_template.copy()
        x[series_free] = x_free
        model = y_series_branch(10 ** x, omega)
        return _complex_residual(model, y_data, _floored_norm(y_data), 1.0)

    Yser_fit = Yser[fit_mask]
    res = least_squares(series_residuals_rlc, x0=np.log10([Rs0, Ls0, 1e-15]),
                        args=(omega_fit, Yser_fit),
                        bounds=(np.log10([1e-4, 1e-13, 1e-19]), np.log10([1e4, 1e-6, 1e-11])))
    Rs1, Ls1, Cs1 = 10 ** res.x

    # The skin corners are not known in advance: try (pairs of) seed corners spread over the
    # fit band and keep the best.  Lskin is capped at 1 uH, so a corner below the band stays
    # bounded.
    corner_seeds = np.geomspace(max(f_fit[0], f_fit[-1] / 1000), f_fit[-1] / 2, 5)
    if num_skin_sections == 2:
        corner_pairs = [(fc1, fc2) for i, fc1 in enumerate(corner_seeds)
                        for fc2 in corner_seeds[i + 1:]]
    else:
        corner_pairs = [(fc1, None) for fc1 in corner_seeds]
    series_lower = np.log10([1e-4, 1e-13, 1e-4, 1e-16, 1e-4, 1e-16, 1e-19])[series_free]
    series_upper = np.log10([1e4, 1e-6, 1e5, 1e-6, 1e5, 1e-6, 1e-11])[series_free]
    best = None
    for f_corner1, f_corner2 in corner_pairs:
        Rskin0 = max(Rs1, 0.1) / num_skin_sections
        skin2 = ((Rskin0, Rskin0 / (2 * math.pi * f_corner2)) if f_corner2
                 else 10 ** np.array(X_SKIN2_FIXED))
        x_template = np.log10([Rs1, Ls1, Rskin0, Rskin0 / (2 * math.pi * f_corner1),
                               *skin2, Cs1])
        res = least_squares(series_residuals_skin, x0=x_template[series_free],
                            args=(x_template, omega_fit, Yser_fit),
                            bounds=(series_lower, series_upper))
        if best is None or res.cost < best.cost:
            best = res
            x_series = x_template.copy()
            x_series[series_free] = res.x
    # skin corners not below the fit band, as in the global fit, whose bounds are centred on
    # the seed values
    for i in (2, 4):
        x_series[i + 1] = min(x_series[i + 1], x_series[i] - math.log10(2 * math.pi * f_fit[0]))
    return 10 ** x_series


def _seed_shunt(Ysh, omega, fit_mask):
    """Cox from the low-frequency capacitance, Csi and Rsi from the high-frequency limits
    Cp -> Cox Csi/(Cox+Csi) and Rp -> Rsi (Cox+Csi)^2/Cox^2, then refined by a small
    least-squares fit of Cox-(Rsi||Csi) to the shunt branch."""
    def shunt_residuals(logp, omega, y_data):
        model = y_shunt_branch(*(10 ** logp), omega)
        return np.concatenate([
            _complex_residual(model, y_data, _floored_norm(y_data), 1.0),
            _real_residual(model.real, y_data.real, _floored_norm(y_data.real), W_SHUNT_RE)])

    Cp = Ysh.imag / omega
    Cp_band = Cp[fit_mask & (Cp > 0)]
    if not len(Cp_band):
        raise ValueError("the shunt branch is not capacitive anywhere in the fit band, "
                         "this does not look like an on-chip inductor")
    Cox = np.median(Cp_band[:3])
    Cinf = np.min(Cp_band)
    Csi = Cox * Cinf / (Cox - Cinf) if Cinf < 0.95 * Cox else 20 * Cox
    Rp_band = 1.0 / Ysh.real[fit_mask & (Ysh.real > 0)]
    Rsi = np.min(Rp_band) * Cox ** 2 / (Cox + Csi) ** 2 if len(Rp_band) else 100.0
    Rsi = min(max(Rsi, 1.0), 1e5)
    x0 = np.log10([Cox, Rsi, Csi])
    res = least_squares(shunt_residuals, x0=x0, args=(omega[fit_mask], Ysh[fit_mask]),
                        bounds=(x0 - [1, 3, 3], x0 + [1, 3, 3]))
    return 10 ** res.x


# ---------------- shared helpers ----------------

def _ghz(x):
    return "n/a" if x is None else f"{x / 1e9:.4g} GHz"


def _prepare(net):
    """Frequencies, angular frequencies and Y of the positive-frequency samples."""
    keep = net.f > 0
    f = np.asarray(net.f[keep], float)
    return f, 2 * math.pi * f, np.asarray(net.y[keep])


def _log_seed(names, seed, what):
    """log10 of the seed values, refusing data whose seeds are not positive: the global fit
    runs on log values and cannot start from them."""
    bad = [n for n, v in zip(names, seed) if not (np.isfinite(v) and v > 0)]
    if bad:
        raise ValueError(f"the data gives no usable starting value for {', '.join(bad)}, "
                         f"it does not look like {what}")
    return np.log10(seed)


def _fit_band(f, srf):
    """The data's own band, cut at SRF_FIT_FACTOR x SRF when the data reaches that far."""
    fmax = min(SRF_FIT_FACTOR * srf, f[-1]) if srf is not None else f[-1]
    fit_mask = f <= fmax
    if np.count_nonzero(fit_mask) < MIN_FIT_POINTS:
        raise ValueError(f"only {np.count_nonzero(fit_mask)} points up to "
                         f"{SRF_FIT_FACTOR} x SRF ({_ghz(fmax)}), the fit needs "
                         f"{MIN_FIT_POINTS}")
    return fmax, fit_mask


def _below(f, fit_mask, srf, factor=LQ_SRF_FACTOR):
    """The fit band below factor x SRF, where L and Q are well defined."""
    mask = fit_mask.copy()
    if srf is not None:
        mask &= f <= factor * srf
    return mask


def _peak_q(f, Q, mask):
    i = int(np.argmax(np.where(mask, Q, -np.inf)))
    return float(Q[i]), float(f[i])


def _bound_warnings(variant, x_fit, lower, upper, negligible_at, skip=()):
    """An element that ran to the bound where it has no effect (a parallel C to 0, a
    parallel R to open, a skin section shorted) is simply not needed for this data, which
    is fine.  Any other element at a bound wanted to go beyond its range, which is reported."""
    at_lower = x_fit - lower < 0.005              # within ~1 % of the bound
    at_upper = upper - x_fit < 0.005
    out = []
    for i, name in enumerate(variant["names"]):
        if not variant["free"][i] or not (at_lower[i] or at_upper[i]) or name in skip:
            continue
        bound = "lower" if at_lower[i] else "upper"
        if negligible_at.get(name) != bound:
            out.append(f"{name} ended at its {bound} bound, it may not be determined by "
                       f"the data")
    return out


def _shorted_substrate(fit, locations, omega_max, tied=()):
    """Where Rsi is negligible against Cox over the whole band, Cox effectively connects to
    ground (a ground shield, a low-ohmic substrate contact) and Rsi, Csi are undetermined."""
    shorted, notes = [], []
    for loc in locations:
        if fit["Rsi" + loc] * omega_max * fit["Cox" + loc] < 0.05 and "Cox" + loc not in tied:
            shorted += ["Rsi" + loc, "Csi" + loc]
            notes.append(f"Rsi{loc} is negligible against Cox{loc}, so Cox{loc} effectively "
                         f"connects to ground and Rsi{loc}, Csi{loc} are not determined by "
                         f"the data")
    return shorted, notes


def _srf_message(srf_data, srf_model, f_last):
    if srf_data is None:
        return (f"no self-resonance in the data, the model's ({_ghz(srf_model)}) is "
                f"extrapolated")
    if srf_model is None or srf_model > f_last:
        return f"SRF {_ghz(srf_data)} in the data, the model's is outside the data range"
    return f"SRF {_ghz(srf_model)} (data {_ghz(srf_data)})"


# ======================== 2-port inductor ========================

def fit_two_port(net, basic=False, progress=None) -> InductorFit:
    """Fit the 2-port wideband inductor model to `net` (a 2-port skrf.Network)."""
    if net.nports != 2:
        raise ValueError("the wideband inductor model needs a 2-port (.s2p)")
    num_skin = 1 if basic else 2
    f, omega, Ymeas = _prepare(net)

    Ysh1_meas, Ysh2_meas, Yser_meas = pi_branches(Ymeas)
    Ydiff_meas = y_diff(Ymeas)
    L11_meas, Q11_meas = l_and_q(Ymeas[:, 0, 0], omega)
    L22_meas, Q22_meas = l_and_q(Ymeas[:, 1, 1], omega)
    Ldiff_meas, Qdiff_meas = l_and_q(Ydiff_meas, omega)

    # ---- self-resonance of the data and the fit band ----
    srf_candidates = [x for x in (find_srf(f, Ymeas[:, 0, 0]), find_srf(f, Ymeas[:, 1, 1]))
                      if x is not None]
    SRF_meas = min(srf_candidates) if srf_candidates else None
    SRFdiff_meas = find_srf(f, Ydiff_meas)
    fmax, fit_mask = _fit_band(f, SRF_meas)
    f_fit = f[fit_mask]
    omega_fit = omega[fit_mask]
    lq_mask = _below(f, fit_mask, SRF_meas)
    lqdiff_mask = _below(f, fit_mask, SRFdiff_meas)
    lq_fit = lq_mask[fit_mask]
    lqdiff_fit = lqdiff_mask[fit_mask]

    # ---- analytic seed values ----
    shunt_asymmetry = _rel_difference(Ysh1_meas[fit_mask], Ysh2_meas[fit_mask])
    data_symmetric = shunt_asymmetry < SYMMETRY_TOLERANCE
    sym = "symmetric" if data_symmetric else "asymmetric"
    substrate_choices = [sym] if basic else [sym, sym + "+coupling"]
    segment_choices = (1,) if basic else SEGMENT_CHOICES
    total_runs = (sum(_runs(0 if i == 0 else 1) for i in range(len(segment_choices)))
                  + (len(substrate_choices) - 1) * _runs(1))
    tick = _Ticker(progress, total_runs)
    tick.start("calculating the starting values")

    series_seed = _seed_series(Yser_meas, omega, fit_mask, num_skin)
    shunt1_seed = _seed_shunt(Ysh1_meas, omega, fit_mask)
    shunt2_seed = _seed_shunt(Ysh2_meas, omega, fit_mask)
    # substrate coupling starts "weak", the global fit decides whether it is needed
    Rsub12_seed = 100 * (shunt1_seed[1] + shunt2_seed[1]) / 2
    Csub12_seed = 0.01 * (shunt1_seed[2] + shunt2_seed[2]) / 2
    seed = np.concatenate([series_seed, shunt1_seed, shunt2_seed, [Rsub12_seed, Csub12_seed]])
    seed[PARAM_NAMES.index("Cs")] = max(seed[PARAM_NAMES.index("Cs")], 1e-16)

    # ---- global fit of the complete 2-port model ----
    def model_quantities(p, omega, segments):
        Y = y_model(p, omega, segments)
        Ysh1, Ysh2, Yser = pi_branches(Y)
        L11, Q11 = l_and_q(Y[:, 0, 0], omega)
        L22, Q22 = l_and_q(Y[:, 1, 1], omega)
        Ldiff, Qdiff = l_and_q(y_diff(Y), omega)
        return dict(Y11=Y[:, 0, 0], Y22=Y[:, 1, 1], Yser=Yser, Ysh1=Ysh1, Ysh2=Ysh2,
                    ReYsh1=Ysh1.real, ReYsh2=Ysh2.real, L11=L11, L22=L22, Ldiff=Ldiff,
                    Q11=Q11, Q22=Q22, Qdiff=Qdiff, Y=Y)

    meas_fit = dict(Y11=Ymeas[fit_mask, 0, 0], Y22=Ymeas[fit_mask, 1, 1],
                    Yser=Yser_meas[fit_mask], Ysh1=Ysh1_meas[fit_mask], Ysh2=Ysh2_meas[fit_mask],
                    ReYsh1=Ysh1_meas[fit_mask].real, ReYsh2=Ysh2_meas[fit_mask].real,
                    L11=L11_meas[fit_mask], L22=L22_meas[fit_mask], Ldiff=Ldiff_meas[fit_mask],
                    Q11=Q11_meas[fit_mask], Q22=Q22_meas[fit_mask], Qdiff=Qdiff_meas[fit_mask])
    all_fit = np.ones(len(f_fit), dtype=bool)
    goals = _make_goals(meas_fit, [
        ("Y11", W_Y, all_fit), ("Y22", W_Y, all_fit), ("Yser", W_Y, all_fit),
        ("Ysh1", W_SHUNT, all_fit), ("Ysh2", W_SHUNT, all_fit),
        ("ReYsh1", W_SHUNT_RE, all_fit), ("ReYsh2", W_SHUNT_RE, all_fit),
        ("L11", W_L, lq_fit), ("L22", W_L, lq_fit), ("Ldiff", W_L, lqdiff_fit),
        ("Q11", W_Q, lq_fit), ("Q22", W_Q, lq_fit), ("Qdiff", W_Q, lqdiff_fit)])

    def residual_fn_for(segments):
        return lambda x: np.concatenate([
            _goal_residuals(model_quantities(10 ** x, omega_fit, segments), meas_fit, goals),
            _corner_penalty(PARAM_NAMES, x, f_fit[0])])

    # bounds in decades around the seeds: wider for the skin and coupling elements, narrow
    # for Cox, which the low-frequency shunt capacitance pins down
    span = np.array([2, 2, 3, 3, 3, 3, 3, COX_SPAN, 3, 3, COX_SPAN, 3, 3, 4, 4])
    x_base_seed = _log_seed(PARAM_NAMES, seed, "an inductor")
    port2_tied = {"Cox2": "Cox1", "Rsi2": "Rsi1", "Csi2": "Csi1"}

    def make_substrate_variant(name):
        symmetric, coupling = SUBSTRATE_VARIANTS[name]
        fixed = {}
        if num_skin == 1:
            fixed.update(Rskin2=X_SKIN2_FIXED[0], Lskin2=X_SKIN2_FIXED[1])
        if not coupling:
            fixed.update(X_COUPLING_OFF)
        return _make_variant(PARAM_NAMES, x_base_seed, span, fixed,
                             port2_tied if symmetric else {}, name=name,
                             symmetric=symmetric, coupling=coupling)

    def unphysical_reasons(variant, x):
        # Cox must not run away from the low-frequency shunt capacitance, and the coupling
        # must be a secondary path, weaker than each port's own path to ground (else one
        # port reaches ground only through the other port's network)
        p = dict(zip(PARAM_NAMES, 10 ** x))
        reasons = []
        for name in ("Cox1", "Cox2"):
            i = PARAM_NAMES.index(name)
            if variant["free"][i] and min(x[i] - variant["lower"][i],
                                          variant["upper"][i] - x[i]) < 0.005:
                reasons.append(f"{name} at bound")
        if variant["coupling"]:
            ysub = np.abs(1 / p["Rsub12"] + 1j * omega_fit * p["Csub12"])
            for port in ("1", "2"):
                ysi = np.abs(1 / p["Rsi" + port] + 1j * omega_fit * p["Csi" + port])
                if np.any(ysub > ysi):
                    reasons.append(f"coupling dominates port {port} substrate path")
        return reasons

    variants = {name: make_substrate_variant(name) for name in substrate_choices}
    # step 1: the number of segments, with the (unique) substrate network without coupling
    segment_variant = substrate_choices[0]
    segment_results, segments = _fit_segments(variants[segment_variant], residual_fn_for,
                                              segment_choices, tick)
    # step 2: the simplest physical substrate variant within tolerance of the best physical
    substrate_results = {segment_variant: segment_results[segments]}
    for name in substrate_choices:
        if name not in substrate_results:
            substrate_results[name] = _fit_variant(
                variants[name], residual_fn_for(segments), [segment_results[segments][1]],
                tick, f"substrate network {name}")
    reasons = {name: unphysical_reasons(variants[name], x)
               for name, (_, x) in substrate_results.items()}
    physical = [name for name in substrate_choices if not reasons[name]]
    candidates = physical if physical else substrate_choices
    min_cost = min(substrate_results[name][0] for name in candidates)
    substrate = next(name for name in candidates
                     if substrate_results[name][0] <= SUBSTRATE_COST_TOLERANCE * min_cost)
    variant = variants[substrate]
    best_cost, x_fit = substrate_results[substrate]
    lower, upper = variant["lower"].copy(), variant["upper"].copy()
    x_seed = variant["x_seed"].copy()
    if num_skin == 2:
        _sort_skin_sections(PARAM_NAMES, (x_fit, lower, upper, x_seed))
    p_fit = 10 ** x_fit
    fit = dict(zip(PARAM_NAMES, (float(v) for v in p_fit)))
    active = [name for name in PARAM_NAMES if name not in variant["fixed"]]

    # ---- post-processing ----
    model = model_quantities(p_fit, omega, segments)
    # model SRF on a dense grid past the data, so an extrapolated SRF is found as well
    f_grid = np.linspace(f[0], 1.5 * f[-1], 20000)
    Y_grid = y_model(p_fit, 2 * math.pi * f_grid, segments)
    srf_model = [find_srf(f_grid, Y_grid[:, 0, 0]), find_srf(f_grid, Y_grid[:, 1, 1])]
    SRF_model = min(x for x in srf_model if x is not None) if any(srf_model) else None
    below_srf = f <= (SRF_meas if SRF_meas is not None else f[-1])
    below_srfdiff = f <= (SRFdiff_meas if SRFdiff_meas is not None else f[-1])
    q11 = _peak_q(f, model["Q11"], below_srf), _peak_q(f, Q11_meas, below_srf)
    qdiff = _peak_q(f, model["Qdiff"], below_srfdiff), _peak_q(f, Qdiff_meas, below_srfdiff)
    L_dc = fit["Ls"] + fit["Lskin1"] + (fit["Lskin2"] if num_skin == 2 else 0.0)

    msgs = [f"wideband fit {_ghz(f_fit[0])} to {_ghz(f_fit[-1])}, {segments} coil "
            f"segment{'' if segments == 1 else 's'}, {substrate} substrate network"
            + (", basic model" if basic else "")]
    if fmax < f[-1]:
        msgs.append(f"data above {_ghz(fmax)} not fitted (beyond {SRF_FIT_FACTOR} x SRF)")
    msgs.append(_srf_message(SRF_meas, SRF_model, f[-1]))
    msgs.append(f"peak Q11 {q11[0][0]:.3g} at {_ghz(q11[0][1])} (data {q11[1][0]:.3g} at "
                f"{_ghz(q11[1][1])}), differential {qdiff[0][0]:.3g} (data {qdiff[1][0]:.3g})")
    if not physical:
        msgs.append("no substrate network variant passed the plausibility check, the "
                    "substrate values may not be physical")
    negligible_at = {"Cs": "lower", "Csi1": "lower", "Csi2": "lower", "Csub12": "lower",
                     "Rsi1": "upper", "Rsi2": "upper", "Rsub12": "upper",
                     "Rskin1": "lower", "Lskin1": "lower", "Rskin2": "lower",
                     "Lskin2": "lower"}
    shorted, notes = _shorted_substrate(fit, ("1", "2"), omega_fit[-1], variant["ties"])
    msgs += notes
    msgs += _bound_warnings(variant, x_fit, lower, upper, negligible_at, shorted)

    metrics = {"segments": segments, "substrate": substrate, "basic": bool(basic),
               "f_fit_min": float(f_fit[0]), "f_fit_max": float(f_fit[-1]),
               "srf_data": SRF_meas, "srf_model": SRF_model, "L_dc": L_dc,
               "Q11_peak": q11[0][0], "Q11_peak_data": q11[1][0],
               "Qdiff_peak": qdiff[0][0], "Qdiff_peak_data": qdiff[1][0],
               "port_asymmetry": shunt_asymmetry, "fit_cost": float(best_cost)}
    return InductorFit(values=fit, active=active, segments=segments, num_skin=num_skin,
                       coupling=variant["coupling"], basic=bool(basic),
                       f_fit=(float(f_fit[0]), float(f_fit[-1])), cost=float(best_cost),
                       metrics=metrics, messages=msgs)


# ======================== center-tapped inductor (3-port) ========================

def _center_tap_hint(Y):
    """The port the low-frequency data puts in the middle of the coil.  With the other two
    ports grounded, current from a coil end mostly leaves through the nearby center tap, so
    the two coil ends share the weakest transfer admittance."""
    pairs = {2: abs(Y[0, 1]), 1: abs(Y[0, 2]), 0: abs(Y[1, 2])}   # key: the third port
    return min(pairs, key=pairs.get)


def fit_center_tap(net, basic=False, progress=None) -> InductorFit:
    """Fit the center-tapped inductor model to `net`: a 3-port with the coil ends on ports
    1 and 2 and the center tap on port 3."""
    if net.nports != 3:
        raise ValueError("the center-tapped inductor model needs a 3-port (.s3p)")
    num_skin = 1 if basic else 2
    f, omega, Ymeas = _prepare(net)
    s = np.asarray(net.s[net.f > 0])

    # Every port must touch the coil: at low frequency each one sees the coil (a small
    # resistance) with the others grounded.  An open or only capacitively coupled port (a
    # center tap port missing the metal in the EM setup) has a tiny, capacitive admittance.
    y_lf = np.abs(np.diagonal(Ymeas[0]))
    for i in np.where((y_lf < 1e-3 * y_lf.max()) | (np.diagonal(Ymeas[0]).imag > 0))[0]:
        c_ff = Ymeas[0, i, i].imag / omega[0] * 1e15
        raise ValueError(
            f"port {i + 1} is not connected to the coil: at {_ghz(f[0])} its input admittance "
            f"with the other ports grounded is {abs(Ymeas[0, i, i]):.3g} S, capacitive "
            f"({c_ff:.3g} fF), |S{i + 1}{i + 1}| = {abs(s[0, i, i]):.4f}. Check the port "
            f"definition in the EM setup")
    meas = ct_quantities(Ymeas, omega)

    # ---- self-resonances of the data and the fit band ----
    srf_keys = (("dd_gnd", "Ydd_gnd"), ("dd_open", "Ydd_open"), ("cm", "Y33"),
                ("11", "Y11"), ("22", "Y22"))
    SRF_meas = {key: find_srf(f, meas[yk]) for key, yk in srf_keys}
    srf_candidates = [SRF_meas[key] for key in ("dd_gnd", "11", "22")
                      if SRF_meas[key] is not None]
    SRF_ref = min(srf_candidates) if srf_candidates else None
    fmax, fit_mask = _fit_band(f, SRF_ref)
    f_fit = f[fit_mask]
    omega_fit = omega[fit_mask]
    lq_masks = {key: _below(f, fit_mask, srf) for key, srf in SRF_meas.items()}

    segment_choices = (1,) if basic else SEGMENT_CHOICES
    tick = _Ticker(progress, sum(_runs(0 if i == 0 else 1)
                                 for i in range(len(segment_choices))))
    tick.start("calculating the starting values")

    # ---- analytic seed values ----
    # the whole coil (center tap open) with the 2-port seeding
    Ysh1_open, Ysh2_open, Yser_open = pi_branches(ct_open_2port(Ymeas))
    Rs_t, Ls_t, Rsk1_t, Lsk1_t, Rsk2_t, Lsk2_t, Cs_t = _seed_series(Yser_open, omega,
                                                                   fit_mask, num_skin)
    # half coils, coupling and center tap lead from the low-frequency impedance matrix of
    # p1/p2 with the center tap as reference: Z11' = Zhalf1 + Rct, Z22' = Zhalf2 + Rct,
    # Z12' = Rct - jwM
    i0 = int(np.argmax(fit_mask))
    Zp = np.linalg.inv(Ymeas[i0:i0 + 3, :2, :2])
    w3 = omega[i0:i0 + 3]
    Rct0 = max(np.median(Zp[:, 0, 1].real), 1e-3)
    R_half = [max(np.median(Zp[:, i, i].real) - Rct0, 0.1 * np.median(Zp[:, i, i].real))
              for i in (0, 1)]
    L_half = [np.median(Zp[:, i, i].imag / w3) for i in (0, 1)]
    M0 = max(np.median(-Zp[:, 0, 1].imag / w3), 0.05 * math.sqrt(L_half[0] * L_half[1]))
    half_seeds = []
    for i in (0, 1):
        q_h = L_half[i] / sum(L_half)             # share of the half coil in L and R
        r_h = R_half[i] / sum(R_half)
        Lsk = (Lsk1_t * q_h, Lsk2_t * q_h)
        Ls_h = max(L_half[i] - sum(Lsk), 0.3 * L_half[i])
        half_seeds.append([R_half[i], Ls_h, Rsk1_t * r_h, Lsk[0], Rsk2_t * r_h, Lsk[1]])
    k0 = float(np.clip(M0 / math.sqrt(half_seeds[0][1] * half_seeds[1][1]), 0.05, 0.95))
    shunt_seeds = [_seed_shunt(meas[key], omega, fit_mask) for key in ("S1", "S2", "S3")]
    seed = np.concatenate([half_seeds[0], half_seeds[1], [k0, max(Cs_t, 1e-16), Rct0],
                           *shunt_seeds])

    # ---- global fit ----
    meas_fit = {key: value[fit_mask] for key, value in meas.items() if key != "Y"}
    all_fit = np.ones(len(f_fit), dtype=bool)
    lq_fit = {key: mask[fit_mask] for key, mask in lq_masks.items()}
    goal_list = ([(key, W_Y, all_fit) for key in ("Y11", "Y22", "Y33", "B12", "B13", "B23")]
                 + [(key, W_SHUNT, all_fit) for key in ("S1", "S2", "S3")]
                 + [(key, W_SHUNT_RE, all_fit) for key in ("ReS1", "ReS2", "ReS3")])
    for key in ("dd_gnd", "dd_open", "cm", "11", "22"):
        goal_list += [("L" + key, W_L, lq_fit[key]), ("Q" + key, W_Q, lq_fit[key])]
    goals = _make_goals(meas_fit, goal_list)

    def residual_fn_for(segments):
        return lambda x: np.concatenate([
            _goal_residuals(ct_quantities(y_model_ct(10 ** x, omega_fit, segments), omega_fit),
                            meas_fit, goals),
            _corner_penalty(CT_PARAM_NAMES, x, f_fit[0])])

    span = np.array([2, 2, 3, 3, 3, 3] * 2 + [0, 3, 3] + [COX_SPAN, 3, 3] * 3)
    x_base_seed = _log_seed(CT_PARAM_NAMES, seed,
                            "a center-tapped inductor with the center tap on port 3")

    # Symmetry is decided from the data, separately for the half coil inductances, the half
    # coil resistances and the substrate at p1/p2: symmetric halves can still differ in
    # resistance (an underpass in one half), and tying only what is symmetric keeps the
    # asymmetric model from spending freedom it does not need.
    Zhalf1, Zhalf2 = 1 / meas["B13"][fit_mask], 1 / meas["B23"][fit_mask]
    asymmetry = {"inductance": _rel_difference(Zhalf1.imag, Zhalf2.imag),
                 "resistance": _rel_difference(Zhalf1.real, Zhalf2.real),
                 "substrate": _rel_difference(meas["S1"][fit_mask], meas["S2"][fit_mask])}
    symmetric = {group: value < SYMMETRY_TOLERANCE for group, value in asymmetry.items()}
    tie_groups = {"inductance": {n + "_h2": n + "_h1" for n in ("Ls", "Lskin1", "Lskin2")},
                  "resistance": {n + "_h2": n + "_h1" for n in ("Rs", "Rskin1", "Rskin2")},
                  "substrate": {"Cox2": "Cox1", "Rsi2": "Rsi1", "Csi2": "Csi1"}}
    ties = {}
    for group, tie in tie_groups.items():
        if symmetric[group]:
            ties.update(tie)
    fixed = {}
    if num_skin == 1:
        for h in ("_h1", "_h2"):
            fixed.update({"Rskin2" + h: X_SKIN2_FIXED[0], "Lskin2" + h: X_SKIN2_FIXED[1]})
    variant = _make_variant(CT_PARAM_NAMES, x_base_seed, span, fixed, ties,
                            bounds_override={"k": K_BOUNDS})
    segment_results, segments = _fit_segments(variant, residual_fn_for, segment_choices, tick)
    best_cost, x_fit = segment_results[segments]
    lower, upper = variant["lower"].copy(), variant["upper"].copy()
    x_seed = variant["x_seed"].copy()
    if num_skin == 2:
        for h in ("_h1", "_h2"):
            _sort_skin_sections(CT_PARAM_NAMES, (x_fit, lower, upper, x_seed), h)
    p_fit = 10 ** x_fit
    fit = dict(zip(CT_PARAM_NAMES, (float(v) for v in p_fit)))
    active = [name for name in CT_PARAM_NAMES if name not in variant["fixed"]]

    # ---- post-processing ----
    model = ct_quantities(y_model_ct(p_fit, omega, segments), omega)
    f_grid = np.linspace(f[0], 1.5 * f[-1], 20000)
    grid = ct_quantities(y_model_ct(p_fit, 2 * math.pi * f_grid, segments), 2 * math.pi * f_grid)
    SRF_model = {key: find_srf(f_grid, grid[yk]) for key, yk in srf_keys}
    below_srf = {key: f <= (srf if srf is not None else f[-1]) for key, srf in SRF_meas.items()}
    q_dd = (_peak_q(f, model["Qdd_gnd"], below_srf["dd_gnd"]),
            _peak_q(f, meas["Qdd_gnd"], below_srf["dd_gnd"]))
    q_cm = _peak_q(f, model["Qcm"], below_srf["cm"]), _peak_q(f, meas["Qcm"], below_srf["cm"])
    L_dc = [fit["Ls" + h] + fit["Lskin1" + h] + (fit["Lskin2" + h] if num_skin == 2 else 0.0)
            for h in ("_h1", "_h2")]
    M_fit = fit["k"] * math.sqrt(fit["Ls_h1"] * fit["Ls_h2"])

    sym_text = ", ".join(f"{group} {'symmetric' if symmetric[group] else 'asymmetric'}"
                         for group in asymmetry)
    msgs = [f"center-tapped fit {_ghz(f_fit[0])} to {_ghz(f_fit[-1])}, {segments} coil "
            f"segment{'' if segments == 1 else 's'} per half, {sym_text}"
            + (", basic model" if basic else "")]
    hint = _center_tap_hint(Ymeas[i0])
    if hint != 2:
        msgs.append(f"port {hint + 1} looks like the center tap, the model expects it on "
                    f"port 3")
    if fmax < f[-1]:
        msgs.append(f"data above {_ghz(fmax)} not fitted (beyond {SRF_FIT_FACTOR} x SRF)")
    srf_model_ref = [SRF_model[key] for key in ("dd_gnd", "11", "22")
                     if SRF_model[key] is not None]
    srf_model_ref = min(srf_model_ref) if srf_model_ref else None
    msgs.append(_srf_message(SRF_ref, srf_model_ref, f[-1]))
    msgs.append(f"peak Q differential {q_dd[0][0]:.3g} at {_ghz(q_dd[0][1])} (data "
                f"{q_dd[1][0]:.3g} at {_ghz(q_dd[1][1])}), common mode {q_cm[0][0]:.3g} "
                f"(data {q_cm[1][0]:.3g})")
    negligible_at = {"Cs": "lower", "Rct": "lower"}
    for loc in ("1", "2", "ct"):
        negligible_at.update({"Csi" + loc: "lower", "Rsi" + loc: "upper"})
    for h in ("_h1", "_h2"):
        negligible_at.update({n + h: "lower" for n in ("Rskin1", "Lskin1", "Rskin2", "Lskin2")})
    shorted, notes = _shorted_substrate(fit, ("1", "2", "ct"), omega_fit[-1], ties)
    msgs += notes
    msgs += _bound_warnings(variant, x_fit, lower, upper, negligible_at, shorted)

    metrics = {"segments": segments, "basic": bool(basic),
               "symmetric": dict(symmetric), "asymmetry": dict(asymmetry),
               "f_fit_min": float(f_fit[0]), "f_fit_max": float(f_fit[-1]),
               "srf_data": SRF_ref, "srf_model": srf_model_ref,
               "L_dc_h1": L_dc[0], "L_dc_h2": L_dc[1], "M": M_fit,
               "L_diff_dc": L_dc[0] + L_dc[1] + 2 * M_fit,
               "Qdiff_peak": q_dd[0][0], "Qdiff_peak_data": q_dd[1][0],
               "Qcm_peak": q_cm[0][0], "Qcm_peak_data": q_cm[1][0],
               "fit_cost": float(best_cost)}
    return InductorFit(values=fit, active=active, segments=segments, num_skin=num_skin,
                       basic=bool(basic), f_fit=(float(f_fit[0]), float(f_fit[-1])),
                       cost=float(best_cost), metrics=metrics, messages=msgs)
