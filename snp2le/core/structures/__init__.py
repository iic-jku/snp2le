# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""structures package - registry of physical extractors keyed by name."""
from __future__ import annotations
from .base import Structure
from .inductor_pi import InductorPi
from .inductor_wideband import InductorWideband, InductorCenterTap
from .mim_cap import MimCap
from .tline import TransmissionLine
from .wilkinson import Wilkinson, WilkinsonInphase
from .balun import Balun
from .branchline import BranchLineCoupler

# Order is the GUI dropdown order, and the first structure matching a file's port count is
# the one structure mode opens on, so the center-tapped inductor stays behind the Wilkinsons.
STRUCTURES = {s.key: s for s in (InductorPi(), InductorWideband(), MimCap(),
                                 TransmissionLine(), WilkinsonInphase(), Wilkinson(),
                                 InductorCenterTap(), Balun(), BranchLineCoupler())}


def structure_items():
    """(key, display_name, n_ports) for the GUI dropdown."""
    return [(s.key, s.display_name, s.n_ports) for s in STRUCTURES.values()]


def get_structure(key) -> Structure:
    return STRUCTURES[key]
