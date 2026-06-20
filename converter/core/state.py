"""state.py - ConverterState (all user inputs) + Results (everything views render).

ConverterState is a plain dataclass (no Qt) so the logic is testable and the
design is serialisable for save/load, exactly like the filter designer.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json


@dataclass
class ConverterState:
    mode: str = "universal"               # universal | structure
    structure_key: str = "inductor-pi"
    pdk: str = "ihp-sg13g2"               # target PDK (see core/pdk.py, DEFAULT_PDK)
    max_order: int = 6
    enforce_passivity: bool = True
    source_path: str = ""                 # last loaded .sNp (for save/restore)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ConverterState":
        return cls(**json.loads(text))


@dataclass
class Results:
    ok: bool = True
    error: str = ""
    mode: str = "universal"
    physical: bool = False

    ir: object = None                     # CircuitIR
    ngspice: str = ""
    vacask: str = ""
    pdk: str = ""                         # target PDK key the netlists were rendered for

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
