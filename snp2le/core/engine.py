# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""engine.py - the conversion pipeline (pure Python, no Qt).

convert(state, net) restricts the data to the requested fit band (state.f_min /
state.f_max, both optional), runs the chosen mode, renders both netlist dialects
from the resulting CircuitIR, and assembles the data-vs-model S-parameters for the
plot view.  Everything downstream (RMS error, tolerances, plots) therefore refers
to the fitted band.  Both the GUI and the CLI call this one function.

An optional `progress` callable, `cb(fraction, message)`, is reported to along
the way.  The weights below are the relative cost of each stage, measured on the
bundled examples, and they are what makes the fraction track the real work
instead of counting steps.  See `progress.py` for the contract.

A conversion runs its linear algebra on one BLAS thread (`_one_blas_thread`).
"""
from __future__ import annotations
import os

import numpy as np

from .state import ConverterState, Results
from .progress import StageTracker
from .process_state import ProcessSetting
from . import netlist as _nl
from . import dcpin as _pin
from . import universal as _uni
from . import mna as _mna
from .structures import STRUCTURES, get_structure
from .structures.inductor_wideband import wideband_options

# (key, relative cost, message).  Universal mode is dominated by the fit itself,
# structure mode by the MNA rebuild of the extracted RLC over every frequency.
_PLAN_UNIVERSAL = (
    ("prepare",  3, "preparing the data"),
    ("fit",     72, "vector fitting"),
    ("model",   18, "rebuilding the model response"),
    ("dc",       3, "checking the DC operating point"),
    ("netlist",  4, "rendering the netlists"),
)
# With thermal noise the generator is solved and checked after the model response, and its
# netlist is larger.  A separate plan keeps the default one, and its fractions, as they were.
_PLAN_UNIVERSAL_NOISE = (
    ("prepare",  3, "preparing the data"),
    ("fit",     72, "vector fitting"),
    ("model",   18, "rebuilding the model response"),
    ("noise",    6, "computing the thermal noise"),
    ("dc",       3, "checking the DC operating point"),
    ("netlist",  5, "rendering the netlists"),
)
_PLAN_STRUCTURE = (
    ("prepare",  3, "preparing the data"),
    ("extract", 25, "extracting the element values"),
    ("tol",     12, "checking the element tolerances"),
    ("model",   50, "rebuilding the model response"),
    ("traces",   5, "building the extra traces"),
    ("netlist",  5, "rendering the netlists"),
)
# A wideband structure (the fitted inductors) spends nearly all its time in the global fit,
# which reports its own progress per least-squares run.  It has no per-element tolerance.
_PLAN_STRUCTURE_WIDEBAND = (
    ("prepare",  1, "preparing the data"),
    ("extract", 92, "fitting the wideband model"),
    ("model",    5, "rebuilding the model response"),
    ("traces",   1, "building the extra traces"),
    ("netlist",  1, "rendering the netlists"),
)


def _is_wideband(key) -> bool:
    return bool(getattr(STRUCTURES.get(key), "wideband", False))


# An explicit thread count for the BLAS library wins over the limit below.
_BLAS_THREAD_VARS = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def _limit_blas():
    """Limit the loaded BLAS libraries to one thread, returning what undoes it, or None when
    nothing is limited: without threadpoolctl, or with a thread variable set by the user."""
    if any(os.environ.get(k) for k in _BLAS_THREAD_VARS):
        return None
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:                       # a --no-deps install: slower, not wrong
        return None
    import scipy.linalg  # noqa: F401  scipy brings its own OpenBLAS, load it before limiting
    return threadpool_limits(limits=1, user_api="blas").restore_original_limits


# Shared by overlapping conversions, so the last one out restores the count the process had.
_BLAS_LIMIT = ProcessSetting(_limit_blas)


def _one_blas_thread():
    """One BLAS thread for a conversion.  Its matrices are small, so a thread pool spends more
    on synchronising than on arithmetic: a 7-port core at order 24 with thermal noise took
    905 s with the default 14 threads and 2.2 s with one.  threadpoolctl limits the libraries
    loaded in this process
    and restores them afterwards, so a simulator started from the GUI or --simulate keeps its
    own threads, which environment variables would not."""
    return _BLAS_LIMIT.held()


def error_text(exc) -> str:
    """The message of a failed conversion.  Some exceptions carry none, and an empty error
    would leave the caller with a failure and no word on what failed."""
    return str(exc) or type(exc).__name__


def convert(state, net, progress=None) -> Results:
    with _one_blas_thread():
        return _convert(state, net, progress)


def _convert(state, net, progress=None) -> Results:
    res = Results(mode=state.mode)
    wideband = state.mode == "structure" and _is_wideband(state.structure_key)
    if state.mode == "structure":
        plan = _PLAN_STRUCTURE_WIDEBAND if wideband else _PLAN_STRUCTURE
    else:
        plan = _PLAN_UNIVERSAL_NOISE if state.thermal_noise else _PLAN_UNIVERSAL
    track = StageTracker(progress, plan)
    if net is None:
        res.ok = False
        res.error = "No network loaded."
        return res

    from . import io as _io
    track.enter("prepare")
    try:
        loaded, ref_notes = _io.uniform_reference(net)
    except (TypeError, ValueError) as exc:     # numpy's LinAlgError is a ValueError
        res.ok = False
        res.error = error_text(exc)
        return res
    net = _io.without_dc(loaded)         # a 0 Hz sample breaks the extraction math
    n_file = len(net.f)
    f_file_lo = float(net.f[0]) if n_file else 0.0
    try:                                 # optional sub-band: fit only what the user asked for
        net, band_notes = _io.restrict_band(net, state.f_min, state.f_max)
    except (TypeError, ValueError) as exc:     # invalid band, or a non-number from a design
        res.ok = False
        res.error = error_text(exc)
        return res
    res.band_limited = len(net.f) < n_file

    res.freq = net.f
    res.n_ports = net.nports
    res.data_s = net.s

    # The same band with the file's 0 Hz point still in it, for passivity enforcement to try
    # a refit that includes it.  Only when the band starts at the file's first sample above
    # 0 Hz, and not for a 0 Hz row that is not finite, which the file then carries for nothing.
    dc_net = None
    has_dc = bool(len(loaded.f) and loaded.f[0] == 0 and np.all(np.isfinite(loaded.s[0])))
    if (state.mode != "structure" and has_dc and len(net.f) and n_file
            and net.f[0] == f_file_lo):
        dc_net = _io.passive_dc(_io.restrict_band(loaded, None, state.f_max)[0],
                                ceiling=_pin.DC_SIGMA)[0]
    # the file's 0 Hz S-matrix, which the DC pin makes the model meet
    dc_s = loaded.s[0] if state.mode != "structure" and state.dc_pin and has_dc else None

    try:
        if state.mode == "structure":
            _convert_structure(state, net, res, track)
        else:
            _convert_universal(state, net, res, track, dc_net, dc_s)
    except Exception as exc:                        # noqa: BLE001
        res.ok = False
        res.error = error_text(exc)
        return res

    if wideband and len(net.f) and net.f[0] > f_file_lo:
        # the low end is what pins Rdc and the DC inductance, a fit without it guesses them
        res.messages.append("the fit range starts above the file's first frequency, so the "
                            "DC resistance and inductance are extrapolated, not fitted")
    # the reference and the band first, they frame the rest
    res.messages = list(ref_notes) + list(band_notes) + list(res.messages)
    track.enter("netlist")
    res.ngspice = _nl.render_ngspice(res.ir)
    res.vacask = _nl.render_vacask(res.ir)
    if not res.value_rows:
        res.value_rows = res.ir.value_rows()
    track.finish(_summary(res))
    return res


def _summary(res) -> str:
    """One line describing the finished model, used as the closing progress message."""
    if res.mode == "universal":
        return f"{res.n_poles} poles, rms {res.rms_error:.2e}"
    n = len(res.value_rows)
    return f"{n} element{'' if n == 1 else 's'} extracted"


def _convert_universal(state, net, res, track, dc_net=None, dc_s=None):
    from . import dc as _dc
    fit = _uni.fit_universal(net, max_order=state.max_order,
                             enforce_passivity=state.enforce_passivity,
                             passivity_ceiling=state.passivity_ceiling,
                             progress=track.sub("fit"), dc_net=dc_net,
                             prefer_strict=state.thermal_noise)
    res.ir = fit.ir
    res.physical = False
    res.n_poles = fit.n_poles
    res.model_order = fit.model_order
    res.passive = fit.passive
    res.sigma_max = fit.sigma_max
    res.sigma_max_freq = fit.sigma_max_freq
    res.passivity_ceiling = fit.passivity_ceiling
    res.passivity_path = fit.passivity_path
    res.rms_error = fit.rms_error
    res.messages = fit.messages
    res.model_s = _uni.model_sparams(fit.vf, net.f, progress=track.sub("model"))
    if state.thermal_noise:
        from . import noise as _noise
        track.enter("noise")
        strict = (state.enforce_passivity and _uni.effective_ceiling(
            state.enforce_passivity, state.passivity_ceiling) <= 1.0)
        res.noise = _noise.add_thermal_noise(res.ir, fit.vf, fit.sigma_max,
                                             fit.sigma_max_freq, strictly_enforced=strict)
        if not res.noise.ok:                        # the netlist stays noiseless, say so
            res.messages.append(res.noise.message)
    track.enter("dc")                               # after the generator, so it is checked too
    try:                                            # flag a singular DC operating point
        z0 = float(np.real(np.asarray(net.z0).flatten()[0])) or 50.0
    except (TypeError, ValueError, IndexError):
        z0 = 50.0
    if dc_s is not None:
        _pin_dc(state, net, res, fit, dc_s, z0)
    else:
        res.dc = _dc.dc_check(res.ir, z0=z0)
    if not res.dc.ok:
        res.messages.append(res.dc.message)


def _pin_dc(state, net, res, fit, dc_s, z0):
    """Pin the model to the file's 0 Hz point (dcpin.py) and check the DC operating point.
    A fit that nearly shorts a port at DC needs a correction that cancels a large conductance,
    which can leave the DC matrix singular, so then the pin comes back out."""
    from . import dc as _dc
    plain = (list(res.ir.elements), list(res.ir.notes), res.model_s)
    res.dc_pin, res.model_s = _pin.add_dc_pin(
        res.ir, fit.vf, dc_s, np.real(np.asarray(net.z0)[0]), net.f, res.model_s,
        fit.rms_error, fc=state.dc_pin_fc, leak=state.dc_island_leak)
    res.dc = _dc.dc_check(res.ir, z0=z0)
    if res.dc_pin.ok and not res.dc.ok:
        pinned = (res.ir.elements, res.ir.notes, res.model_s)
        res.ir.elements, res.ir.notes, res.model_s = plain
        plain_dc = _dc.dc_check(res.ir, z0=z0)
        if plain_dc.ok:
            res.dc = plain_dc
            res.dc_pin.ok = False
            res.dc_pin.n_sources = 0
            res.dc_pin.message = (f"DC pin skipped: it would make the DC operating point "
                                  f"singular, since the fit nearly shorts a port at DC and the "
                                  f"correction has to cancel up to {res.dc_pin.dy_max:.2g} S")
        else:                                       # singular either way, keep the pin
            res.ir.elements, res.ir.notes, res.model_s = pinned
    if res.dc_pin.ok:                               # the overlay and RMS describe the netlist
        res.rms_error = _rms(res.model_s, net.s)
    res.dc_pin.message += _pin_settings(state)
    res.messages.append(res.dc_pin.message)


def _pin_settings(state):
    """The pin's corner and island leak where they differ from the defaults, as a sentence for
    its message.  Only the CLI and a loaded design set them, the window has no control for them."""
    named = []
    for name, value, default, unit in (
            ("corner", state.dc_pin_fc, ConverterState.dc_pin_fc, "Hz"),
            ("island leak", state.dc_island_leak, ConverterState.dc_island_leak, "S")):
        try:                                        # a caller can pass anything here
            value = float(value)
        except OverflowError:                       # an int beyond any float
            value = float("inf") if value > 0 else float("-inf")
        except (TypeError, ValueError):
            pass
        if value != default:
            named.append(f"{name} {_setting_text(value, unit)} "
                         f"(default {_setting_text(default, unit)})")
    return ". Non-default settings: " + ", ".join(named) if named else ""


def _setting_text(value, unit):
    """ASCII like every core message: a corner as '1 kHz', anything else as '1e-06 S', since
    format_eng writes micro as µ and a non-finite value as an em dash."""
    from .units import format_eng
    if not isinstance(value, float):
        return repr(value)
    if unit == "Hz" and np.isfinite(value) and abs(value) >= 1e-3:
        return format_eng(value, unit)
    return f"{value:g} {unit}"


def _convert_structure(state, net, res, track):
    from .units import format_eng
    track.enter("extract")
    struct = get_structure(state.structure_key)
    if struct.wideband:                       # fitted over the band, f_ext does not apply
        ir, metrics, rows = struct.extract(net, state.f_extract, state.n_segments,
                                           state.iso_resistor, progress=track.sub("extract"),
                                           **wideband_options(state))
    else:
        ir, metrics, rows = struct.extract(net, state.f_extract, state.n_segments,
                                           state.iso_resistor)
    pos = net.f[net.f > 0]
    if (not struct.wideband and pos.size
            and (state.f_extract < pos[0] or state.f_extract > pos[-1])):
        where = "the fit range" if res.band_limited else "the data"
        res.messages.append(
            f"ext. frequency {format_eng(state.f_extract, 'Hz')} outside {where}, "
            f"extracted at {format_eng(metrics.get('f_extract'), 'Hz')}")
    res.messages.extend(metrics.pop("messages", ()))       # the extractor's own notes
    _nl.clamp_ir(ir)                         # one clamped model: netlist == overlay == table
    res.ir = ir
    res.physical = True
    res.metrics = metrics
    res.value_rows = _nl.clamp_rows(rows)
    if not struct.wideband:                   # no per-element tolerance, so no stage in its plan
        track.enter("tol")
    try:                                      # per-element tolerance at f_ext
        drift = struct.value_drift(
            net, res.value_rows, metrics.get("f_extract", state.f_extract)) or {}
        # drop clamped placeholders (a ~0 value gives a meaningless relative tolerance)
        floor = {"H": 1e-17, "F": 1e-17, "Ω": 1e-11}
        res.value_drift = {lab: drift[lab] for lab, val, unit in res.value_rows
                           if lab in drift and abs(val) > floor.get(unit, 0.0)}
    except Exception as exc:                          # noqa: BLE001
        res.messages.append(f"value tolerance failed: {exc}")
    res._structure = struct                          # noqa: SLF001 (used by GUI schematic)
    # rebuild the model response from the extracted RLC for the overlay
    try:
        res.model_s = _mna.rlc_sparams(ir, net.f, z0=float(np.real(net.z0.flatten()[0])),
                                       progress=track.sub("model"))
        res.rms_error = _rms(res.model_s, net.s)
    except Exception as exc:                          # noqa: BLE001
        res.messages.append(f"model rebuild failed: {exc}")
    # optional extra frequency-domain traces (e.g. inductor L/Q) and plot defaults
    track.enter("traces")
    try:
        if struct.wideband:                   # its views follow the fitted port order
            res.aux_traces = struct.freq_traces(net, res.model_s, ir=ir) or {}
            res.default_plots = struct.default_plots(ir=ir)
        else:
            res.aux_traces = struct.freq_traces(net, res.model_s) or {}
            res.default_plots = struct.default_plots()
    except Exception as exc:                          # noqa: BLE001
        res.messages.append(f"freq traces failed: {exc}")
    res.passive = True                                # passive RLC by construction


def _rms(model_s, data_s) -> float:
    d = np.asarray(model_s) - np.asarray(data_s)
    return float(np.sqrt(np.mean(np.abs(d) ** 2)))
