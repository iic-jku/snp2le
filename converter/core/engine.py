"""engine.py - the conversion pipeline (pure Python, no Qt).

convert(state, net) runs the chosen mode, renders both netlist dialects from the
resulting CircuitIR, and assembles the data-vs-model S-parameters for the plot
view.  Both the GUI and the CLI call this one function.
"""
from __future__ import annotations
import numpy as np

from .state import Results
from . import netlist as _nl
from . import universal as _uni
from . import mna as _mna
from .structures import get_structure
from .pdk import get_pdk, DEFAULT_PDK


def convert(state, net) -> Results:
    res = Results(mode=state.mode)
    if net is None:
        res.ok = False
        res.error = "No network loaded."
        return res

    from . import io as _io
    net = _io.without_dc(net)            # a 0 Hz sample breaks the extraction math

    res.freq = net.f
    res.n_ports = net.nports
    res.data_s = net.s

    try:
        if state.mode == "structure":
            _convert_structure(state, net, res)
        else:
            _convert_universal(state, net, res)
    except Exception as exc:                        # noqa: BLE001
        res.ok = False
        res.error = str(exc)
        return res

    pdk = get_pdk(getattr(state, "pdk", DEFAULT_PDK))
    res.pdk = pdk.key
    res.ngspice = _nl.render_ngspice(res.ir, pdk)
    res.vacask = _nl.render_vacask(res.ir, pdk)
    if not res.value_rows:
        res.value_rows = res.ir.value_rows()
    return res


def _convert_universal(state, net, res):
    fit = _uni.fit_universal(net, max_order=state.max_order,
                             enforce_passivity=state.enforce_passivity)
    res.ir = fit.ir
    res.physical = False
    res.n_poles = fit.n_poles
    res.passive = fit.passive
    res.rms_error = fit.rms_error
    res.messages = fit.messages
    res.model_s = _uni.model_sparams(fit.vf, net.f)


def _convert_structure(state, net, res):
    struct = get_structure(state.structure_key)
    ir, metrics, rows = struct.extract(net)
    res.ir = ir
    res.physical = True
    res.metrics = metrics
    res.value_rows = rows
    res._structure = struct                          # noqa: SLF001 (used by GUI schematic)
    # rebuild the model response from the extracted RLC for the overlay
    try:
        res.model_s = _mna.rlc_sparams(ir, net.f, z0=float(np.real(net.z0.flatten()[0])))
        res.rms_error = _rms(res.model_s, net.s)
    except Exception as exc:                          # noqa: BLE001
        res.messages.append(f"model rebuild failed: {exc}")
    res.passive = True                                # passive RLC by construction


def _rms(model_s, data_s) -> float:
    d = np.asarray(model_s) - np.asarray(data_s)
    return float(np.sqrt(np.mean(np.abs(d) ** 2)))
