# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""engine.py - the conversion pipeline (pure Python, no Qt).

convert(state, net) runs the chosen mode, renders both netlist dialects from the
resulting CircuitIR, and assembles the data-vs-model S-parameters for the plot
view.  Both the GUI and the CLI call this one function.

An optional `progress` callable, `cb(fraction, message)`, is reported to along
the way.  The weights below are the relative cost of each stage, measured on the
bundled examples, and they are what makes the fraction track the real work
instead of counting steps.  See `progress.py` for the contract.
"""
from __future__ import annotations
import numpy as np

from .state import Results
from .progress import StageTracker
from . import netlist as _nl
from . import universal as _uni
from . import mna as _mna
from .structures import get_structure

# (key, relative cost, message).  Universal mode is dominated by the fit itself,
# structure mode by the MNA rebuild of the extracted RLC over every frequency.
_PLAN_UNIVERSAL = (
    ("prepare",  3, "preparing the data"),
    ("fit",     72, "vector fitting"),
    ("model",   18, "rebuilding the model response"),
    ("dc",       3, "checking the DC operating point"),
    ("netlist",  4, "rendering the netlists"),
)
_PLAN_STRUCTURE = (
    ("prepare",  3, "preparing the data"),
    ("extract", 25, "extracting the element values"),
    ("tol",     12, "checking the element tolerances"),
    ("model",   50, "rebuilding the model response"),
    ("traces",   5, "building the extra traces"),
    ("netlist",  5, "rendering the netlists"),
)


def convert(state, net, progress=None) -> Results:
    res = Results(mode=state.mode)
    track = StageTracker(progress, _PLAN_STRUCTURE if state.mode == "structure"
                         else _PLAN_UNIVERSAL)
    if net is None:
        res.ok = False
        res.error = "No network loaded."
        return res

    from . import io as _io
    track.enter("prepare")
    net = _io.without_dc(net)            # a 0 Hz sample breaks the extraction math

    res.freq = net.f
    res.n_ports = net.nports
    res.data_s = net.s

    try:
        if state.mode == "structure":
            _convert_structure(state, net, res, track)
        else:
            _convert_universal(state, net, res, track)
    except Exception as exc:                        # noqa: BLE001
        res.ok = False
        res.error = str(exc)
        return res

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


def _convert_universal(state, net, res, track):
    from . import dc as _dc
    fit = _uni.fit_universal(net, max_order=state.max_order,
                             enforce_passivity=state.enforce_passivity,
                             passivity_ceiling=state.passivity_ceiling,
                             progress=track.sub("fit"))
    res.ir = fit.ir
    res.physical = False
    res.n_poles = fit.n_poles
    res.passive = fit.passive
    res.sigma_max = fit.sigma_max
    res.sigma_max_freq = fit.sigma_max_freq
    res.passivity_ceiling = fit.passivity_ceiling
    res.rms_error = fit.rms_error
    res.messages = fit.messages
    res.model_s = _uni.model_sparams(fit.vf, net.f, progress=track.sub("model"))
    track.enter("dc")
    try:                                            # flag a singular DC operating point
        z0 = float(np.real(np.asarray(net.z0).flatten()[0])) or 50.0
    except (TypeError, ValueError, IndexError):
        z0 = 50.0
    res.dc = _dc.dc_check(res.ir, z0=z0)
    if not res.dc.ok:
        res.messages.append(res.dc.message)


def _convert_structure(state, net, res, track):
    from .units import format_eng
    track.enter("extract")
    struct = get_structure(state.structure_key)
    ir, metrics, rows = struct.extract(net, state.f_extract, state.n_segments,
                                       state.iso_resistor)
    pos = net.f[net.f > 0]
    if pos.size and (state.f_extract < pos[0] or state.f_extract > pos[-1]):
        res.messages.append(
            f"ext. frequency {format_eng(state.f_extract, 'Hz')} outside the data; "
            f"extracted at {format_eng(metrics.get('f_extract'), 'Hz')}")
    _nl.clamp_ir(ir)                          # one clamped model: netlist == overlay == table
    res.ir = ir
    res.physical = True
    res.metrics = metrics
    res.value_rows = _nl.clamp_rows(rows)
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
        res.aux_traces = struct.freq_traces(net, res.model_s) or {}
        res.default_plots = struct.default_plots()
    except Exception as exc:                          # noqa: BLE001
        res.messages.append(f"freq traces failed: {exc}")
    res.passive = True                                # passive RLC by construction


def _rms(model_s, data_s) -> float:
    d = np.asarray(model_s) - np.asarray(data_s)
    return float(np.sqrt(np.mean(np.abs(d) ** 2)))
