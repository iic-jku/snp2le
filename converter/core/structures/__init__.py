"""structures package - registry of physical extractors keyed by name."""
from __future__ import annotations
from .base import Structure
from .inductor_pi import InductorPi
from .mim_cap import MimCap
from .tline import TransmissionLine
from .wilkinson import Wilkinson, WilkinsonInphase

STRUCTURES = {s.key: s for s in (InductorPi(), MimCap(), TransmissionLine(),
                                 WilkinsonInphase(), Wilkinson())}


def structure_items():
    """(key, display_name, n_ports) for the GUI dropdown."""
    return [(s.key, s.display_name, s.n_ports) for s in STRUCTURES.values()]


def get_structure(key) -> Structure:
    return STRUCTURES[key]
