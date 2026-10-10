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

# Order is the GUI dropdown order.  Which structure a file opens on is default_structure().
STRUCTURES = {s.key: s for s in (InductorPi(), InductorWideband(), InductorCenterTap(),
                                 MimCap(), TransmissionLine(), WilkinsonInphase(), Wilkinson(),
                                 Balun(), BranchLineCoupler())}


def structure_items():
    """(key, display_name, n_ports) for the GUI dropdown."""
    return [(s.key, s.display_name, s.n_ports) for s in STRUCTURES.values()]


def default_structure(n_ports):
    """The structure that structure mode opens on for an n-port: the first match in the
    dropdown that is not a wideband fit, which takes seconds and is picked on purpose.
    None when no structure has that port count."""
    keys = [s.key for s in STRUCTURES.values() if s.n_ports == n_ports]
    return next((k for k in keys if not STRUCTURES[k].wideband), keys[0] if keys else None)


def get_structure(key) -> Structure:
    return STRUCTURES[key]
