"""state.py - ConverterState (all user inputs) + Results (everything views render).

ConverterState is a plain dataclass (no Qt) so the logic is testable and the
design is serialisable for save/load, exactly like the filter designer.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields
import json


@dataclass
class ConverterState:
    mode: str = "universal"               # universal | structure
    structure_key: str = "inductor-pi"
    f_extract: float = 10e9               # extraction frequency for structure modes [Hz]
    n_segments: int = 2                   # RLGC ladder stages (transmission-line model)
    iso_resistor: bool = True             # include the Wilkinson isolation resistor
    max_order: int = 6
    enforce_passivity: bool = True
    source_path: str = ""                 # last loaded .sNp (for save/restore)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ConverterState":
        data = json.loads(text)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Results:
    ok: bool = True
    error: str = ""
    mode: str = "universal"
    physical: bool = False

    ir: object = None                     # CircuitIR
    ngspice: str = ""
    vacask: str = ""

    n_poles: int = 0
    passive: bool = False
    rms_error: float = float("nan")
    metrics: dict = field(default_factory=dict)
    value_rows: list = field(default_factory=list)   # (name, value, unit)
    messages: list = field(default_factory=list)

    # plotting payload
    freq: object = None                   # data frequencies [Hz]
    data_s: object = None                 # measured/EM S[f,i,j]
    model_s: object = None                # fitted/extracted S[f,i,j]
    n_ports: int = 0
    aux_traces: dict = field(default_factory=dict)   # extra plots, e.g. {"L/Q": {...}}
    default_plots: object = None          # preferred initial plot selectors (labels)
