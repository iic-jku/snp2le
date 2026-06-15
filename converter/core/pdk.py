"""pdk.py - the process design kit (PDK) registry.

The selected PDK tags the generated netlist and decides which simulator
back-ends are available for it.  VACASK (Spectre-syntax) output is currently
only validated for the IHP PDKs, so the other kits are listed but disabled in
the UI until their device models / VACASK support are in place.

Data-driven like the structures registry: a new PDK added here appears in the
GUI dropdown and the CLI automatically.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Pdk:
    key: str
    display_name: str
    vendor: str
    supported: bool = True       # selectable in the UI / CLI
    ngspice: bool = True         # Ngspice (SPICE3) netlist available
    vacask: bool = True          # VACASK (Spectre) netlist available


# Insertion order is the display order in the dropdown.
PDKS = {p.key: p for p in (
    Pdk("ihp-sg13g2",     "IHP SG13G2",     "IHP",             supported=True,  vacask=True),
    Pdk("ihp-sg13cmos5l", "IHP SG13CMOS5L", "IHP",             supported=True,  vacask=True),
    Pdk("gf180mcuD",      "GF180MCU-D",     "GlobalFoundries", supported=False, vacask=False),
    Pdk("sky130A",        "SKY130A",        "SkyWater",        supported=False, vacask=False),
)}

DEFAULT_PDK = "ihp-sg13g2"


def pdk_items():
    """(key, display_name, supported) for the GUI dropdown / CLI listing."""
    return [(p.key, p.display_name, p.supported) for p in PDKS.values()]


def get_pdk(key) -> Pdk:
    """Return the Pdk for `key`, falling back to the default for unknown keys."""
    return PDKS.get(key) or PDKS[DEFAULT_PDK]
