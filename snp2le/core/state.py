# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""state.py - ConverterState (all user inputs) + Results (everything views render).

ConverterState is a plain dataclass (no Qt) so the logic is testable and the
design is serialisable for save/load, exactly like the filter designer.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields
import json

_TRUE, _FALSE = {"true", "yes", "on", "1"}, {"false", "no", "off", "0"}
# Numbers the window has no control for, so a design file is their only way in there.  true
# would read as 1, so a value that is no number refuses the design, as a bad tick box does.
_NUMBER_FIELDS = ("dc_pin_fc", "dc_island_leak")


def _as_bool(name, value):
    """A tick-box field of a loaded design.  A saved design holds JSON true/false, a
    hand-edited one may hold 0/1 or a word, and bool("no") would read as True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
        return value.strip().lower() in _TRUE
    raise ValueError(f"{name} must be true or false, got {json.dumps(value)}")


@dataclass
class ConverterState:
    mode: str = "universal"               # universal | structure
    structure_key: str = "inductor-pi"
    f_extract: float = 10e9               # extraction frequency for structure modes [Hz]
    n_segments: int = 2                   # RLGC ladder stages (transmission-line model)
    iso_resistor: bool = True             # include the Wilkinson isolation resistor
    # Wideband inductor models: the fixed topology (1 coil segment, 1 skin section, no
    # substrate coupling) instead of the one the fit picks, so every fit has the same elements.
    basic_model: bool = False
    # Their fit options (inductor_fit.check_options), 0 and "auto" leave the choice to the fit.
    # The GUI sets coil_segments (1 to 3), center_tap and the two weights at their defaults,
    # the substrate variant and other weight values come from the CLI only.
    coil_segments: int = 0                # 1 to 10 coil segments, 0: the fit picks 1 to 3
    substrate: str = "auto"               # auto | symmetric | asymmetric | ...+coupling
    peak_q_weight: float = 0.0            # emphasis A on L and Q near the Q peak, 0 = off
    shunt_accuracy: float = 0.0           # substrate error floor K x |series branch|, 0 = off
    center_tap: int = 0                   # center tap port of a 3-port, 0: detected
    max_order: int = 6
    enforce_passivity: bool = True
    # Largest singular value the enforced model may keep.  1.0 is strict passivity, a
    # higher ceiling trades a bounded violation for accuracy.  It is what the enforcement
    # works towards, so it only takes effect with enforce_passivity=True.  See
    # universal.PASSIVITY_CEILING_* for the allowed range.
    passivity_ceiling: float = 1.0
    # Universal mode: append a generator of the passive's thermal noise, kT(I - S S^H) at the
    # ports, computed from the fit (noise.py).  False keeps the model noiseless (ideal).
    # Structure models are unaffected, their resistors are real loss and always noisy.
    thermal_noise: bool = False
    # Universal mode: pin the model to the file's 0 Hz sample with a low-pass correction below
    # dc_pin_fc, so its DC admittance (a coil's DC resistance) is the file's, see dcpin.py.
    # Only for a file with a finite 0 Hz sample.  dc_island_leak > 0 gives each DC mode without
    # a path to ground that conductance [S], which can help harmonic balance converge.
    dc_pin: bool = True
    dc_pin_fc: float = 160.0
    dc_island_leak: float = 0.0
    f_min: float | None = None            # fit band start [Hz], None = the data's first point
    f_max: float | None = None            # fit band stop  [Hz], None = the data's last point
    source_path: str = ""                 # last loaded .sNp (for save/restore)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ConverterState":
        data = json.loads(text)
        known = {f.name: f for f in fields(cls)}
        values = {}
        for k, v in data.items():
            if k not in known:
                continue
            if isinstance(known[k].default, bool):
                if v is None:                 # null: the default, like a missing key
                    continue
                v = _as_bool(k, v)
            elif k in _NUMBER_FIELDS:
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError(f"{k} must be a number, got {json.dumps(v)}")
            values[k] = v
        return cls(**values)


@dataclass
class Results:
    ok: bool = True
    error: str = ""
    mode: str = "universal"
    physical: bool = False

    ir: object = None                     # CircuitIR
    ngspice: str = ""
    vacask: str = ""
    xyce: str = ""

    n_poles: int = 0                      # pole entries, a conjugate pair counted once
    model_order: int = 0                  # n_real + 2 x n_complex, the unit max_order is in
    passive: bool = False                 # sigma_max <= passivity_ceiling
    sigma_max: float = float("nan")       # largest singular value of the model S-matrix
    sigma_max_freq: float = float("nan")  # where that peak sits [Hz]
    passivity_ceiling: float = 1.0        # the ceiling `passive` was judged against
    # universal mode: off, not needed, perturbed, reduced order, dc refit (a refit that
    # includes the file's 0 Hz point) or near-passive (enforcement ran and the free fit was
    # kept).  Empty for a structure model.
    passivity_path: str = ""
    dc: object = None                     # DCHealth: DC operating-point check (universal mode)
    noise: object = None                  # NoiseHealth when thermal noise was requested
    dc_pin: object = None                 # DCPinHealth when the file's 0 Hz point was pinned to
    rms_error: float = float("nan")
    metrics: dict = field(default_factory=dict)
    value_rows: list = field(default_factory=list)   # (name, value, unit)
    value_drift: dict = field(default_factory=dict)  # {label: band-drift %} per value
    messages: list = field(default_factory=list)
    band_limited: bool = False            # the fit used a sub-band of the loaded file

    # plotting payload
    freq: object = None                   # data frequencies [Hz]
    data_s: object = None                 # measured/EM S[f,i,j]
    model_s: object = None                # fitted/extracted S[f,i,j]
    n_ports: int = 0
    aux_traces: dict = field(default_factory=dict)   # extra plots, e.g. {"L/Q": {...}}
    default_plots: object = None          # preferred initial plot selectors (labels)
