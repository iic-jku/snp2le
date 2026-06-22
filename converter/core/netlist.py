"""netlist.py - render a CircuitIR to ngspice (SPICE3) and VACASK (Spectre).

Also parses the SPICE subcircuit that scikit-rf emits for the universal
macromodel into a CircuitIR, so the *same* IR drives both dialects and the
schematic.  scikit-rf only emits V, R, C, G (VCCS) and F (CCCS) elements, which
is the set handled here.
"""
from __future__ import annotations
import re
from .ir import CircuitIR, Element


def _num(x: float) -> str:
    return f"{x:.10g}"


# Simulator element-value limits.  ngspice floors a resistance below 1e-12 ohm to
# 1e-12 (with the "resistor too small" warning), so we clamp R to that range; this
# matches what the simulator does anyway, so the result is unchanged.  C/L get
# wide safety bounds that leave every realistic value untouched (including the
# universal macromodel's 1 F state capacitors).  V sources and controlled-source
# gains are not clamped.  The clamp is applied to the *model* (see clamp_ir /
# clamp_rows, called from the engine) so the netlist, schematic, values table and
# rebuilt response all describe the same circuit.
_LIMITS = {"R": (1e-12, 1e12), "C": (1e-18, 1e3), "L": (1e-18, 1e3)}
_UNIT_KIND = {"Ω": "R", "F": "C", "H": "L"}


def _clamp(kind: str, value: float) -> float:
    lo_hi = _LIMITS.get(kind)
    if lo_hi is None:
        return value
    lo, hi = lo_hi
    return min(max(value, lo), hi)


def clamp_ir(ir):
    """Clamp every R/L/C element value to the simulator-valid range, in place."""
    for e in ir.elements:
        e.value = _clamp(e.kind, e.value)
    return ir


def clamp_rows(rows):
    """Clamp (label, value, unit) value-table rows to match the clamped model.

    Negative values are derived display quantities (e.g. a mutual inductance M),
    not netlist elements, so they pass through unclamped (the simulator floors only
    apply to real positive R/L/C device values)."""
    return [(lab, val if val < 0 else _clamp(_UNIT_KIND.get(unit, ""), val), unit)
            for lab, val, unit in rows]


def rescale_state_resistors(ir, target: float = 1e-9):
    """Rescale a vector-fit state realisation so every state self-resistor is at
    least `target` ohms, keeping the transfer function *exactly* the same.

    scikit-rf realises each pole with a 1 F state capacitor and a self-resistor
    R = 1/Re(pole); fast poles give R below ngspice's 1e-12 resistor floor.  Both
    ngspice and a plain clamp would round that to 1e-12 and corrupt the pole,
    which badly distorts the reflection terms (S11/S22) while barely touching
    transmission (this is the order >= 13 bug).  Scaling a state node's capacitor
    by 1/K, its self-resistor by K and every source feeding that node (its n-
    terminal) by 1/K leaves the node voltage - hence every port response -
    unchanged, so the rescaling is lossless.  Only the universal macromodel uses
    this; physical structure models keep clamp_ir (their near-zero resistors are
    genuine shorts).
    """
    cap_nodes = set()
    for e in ir.elements:
        if e.kind == "C" and "0" in e.nodes:
            cap_nodes.add(e.nodes[0] if e.nodes[1] == "0" else e.nodes[1])
    k = {}                                        # state node -> scale factor
    for e in ir.elements:
        if e.kind == "R" and "0" in e.nodes:
            n = e.nodes[0] if e.nodes[1] == "0" else e.nodes[1]
            if n in cap_nodes and 0.0 < e.value < target:
                k[n] = target / e.value
    if not k:
        return ir
    for e in ir.elements:
        if e.kind == "C" and "0" in e.nodes:
            n = e.nodes[0] if e.nodes[1] == "0" else e.nodes[1]
            if n in k:
                e.value /= k[n]
        elif e.kind == "R" and "0" in e.nodes:
            n = e.nodes[0] if e.nodes[1] == "0" else e.nodes[1]
            if n in k:
                e.value *= k[n]
        elif e.kind in ("G", "E", "F"):
            tgt = e.nodes[1]                       # current is injected into n-
            if tgt in k:
                e.value /= k[tgt]
    return ir


def safe_subckt_name(text: str, fallback: str = "s_equivalent") -> str:
    """Turn an arbitrary string (e.g. an export file stem) into a valid SPICE
    subcircuit name: keep letters/digits/underscore, map the rest to '_', and
    avoid a leading digit."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", str(text)).strip("_")
    if not name:
        return fallback
    if name[0].isdigit():
        name = "x" + name
    return name


# --------------------------------------------------------------------------- #
#  Parse the scikit-rf SPICE subcircuit text into a CircuitIR
# --------------------------------------------------------------------------- #
def parse_spice_subckt(text: str, name: str = "s_equivalent") -> CircuitIR:
    ir = CircuitIR(name=name, physical=False)
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("*"):
            ir.comments.append(line.lstrip("* ").rstrip())
            continue
        low = line.lower()
        if low.startswith(".subckt"):
            parts = line.split()
            ir.name = parts[1]
            ir.ports = parts[2:]
            continue
        if low.startswith(".ends") or low.startswith(".end"):
            continue
        tok = line.split()
        k = tok[0][0].upper()
        nm = tok[0]
        if k in ("R", "C", "L", "V"):
            ir.add(Element(k, nm, (tok[1], tok[2]), float(tok[3])))
        elif k in ("G", "E"):
            ir.add(Element(k, nm, (tok[1], tok[2]), float(tok[5]),
                           ctrl=(tok[3], tok[4])))
        elif k == "F":
            ir.add(Element("F", nm, (tok[1], tok[2]), float(tok[4]),
                           ctrl=(tok[3],)))
    return ir


# --------------------------------------------------------------------------- #
#  ngspice  (Berkeley SPICE3)
# --------------------------------------------------------------------------- #
def render_ngspice(ir: CircuitIR) -> str:
    L = [f"* {ir.name} - lumped-element equivalent (ngspice / SPICE3)",
         "* generated by snp2le"]
    L += [f"* {c}" for c in ir.comments[:4]]
    L.append(f".SUBCKT {ir.name} {' '.join(ir.ports)}")
    for e in ir.elements:
        if e.kind in ("R", "C", "L", "V"):
            L.append(f"{e.name} {e.nodes[0]} {e.nodes[1]} {_num(e.value)}")
        elif e.kind in ("G", "E"):
            L.append(f"{e.name} {e.nodes[0]} {e.nodes[1]} "
                     f"{e.ctrl[0]} {e.ctrl[1]} {_num(e.value)}")
        elif e.kind == "F":
            L.append(f"{e.name} {e.nodes[0]} {e.nodes[1]} "
                     f"{e.ctrl[0]} {_num(e.value)}")
    for i, (la, lb, kk) in enumerate(getattr(ir, "couplings", []), 1):
        L.append(f"K{i} {la} {lb} {_num(kk)}")        # mutual inductance (coupling)
    L.append(f".ENDS {ir.name}")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
#  VACASK  (Spectre-style netlist)
# --------------------------------------------------------------------------- #
# VACASK syntax matched to an Xschem-exported, VACASK-runnable testbench:
#   * instances:  name ( nodes ) model param=value
#   * passives reference a model (resistor/capacitor/inductor); sources are built in
# Like the ngspice subckt, the device models and their OSDI loads are NOT redeclared
# here - the testbench / VACASK common lib provides them (OSDI path
# /foss/pdks/ihp-sg13g2/libs.tech/vacask/osdi).
_VC_PASSIVE = {"R": ("resistor", "r"), "C": ("capacitor", "c"), "L": ("inductor", "l")}
_VC_SOURCE = {"V": "vsource", "G": "vccs", "E": "vcvs", "F": "cccs"}


def _vc_model(e: Element) -> str:
    return _VC_PASSIVE[e.kind][0] if e.kind in _VC_PASSIVE else _VC_SOURCE[e.kind]


def _vc_instance(e: Element) -> str:
    n = " ".join(e.nodes)
    if e.kind in _VC_PASSIVE:
        model, p = _VC_PASSIVE[e.kind]
        return f"{e.name} ( {n} ) {model} {p}={_num(e.value)}"
    if e.kind == "V":
        return f"{e.name} ( {n} ) vsource dc={_num(e.value)}"
    if e.kind == "G":                                 # VCCS
        return f"{e.name} ( {n} {e.ctrl[0]} {e.ctrl[1]} ) vccs gm={_num(e.value)}"
    if e.kind == "E":                                 # VCVS
        return f"{e.name} ( {n} {e.ctrl[0]} {e.ctrl[1]} ) vcvs gain={_num(e.value)}"
    if e.kind == "F":                                 # CCCS (controlled by a vsource probe)
        return f"{e.name} ( {n} ) cccs probe={e.ctrl[0]} gain={_num(e.value)}"
    raise KeyError(e.kind)


def render_vacask(ir: CircuitIR) -> str:
    kinds = [e.kind for e in ir.elements]
    L = [f"// {ir.name} - lumped-element equivalent (VACASK), generated by snp2le"]
    L += [f"// {c}" for c in ir.comments[:4]]
    used = sorted({_vc_model(e) for e in ir.elements})
    if used:                                          # models come from the testbench
        L.append("// device models needed (declared by your testbench): " + ", ".join(used))
    if any(k in kinds for k in ("G", "E", "F")):
        L.append("// NOTE: controlled sources (universal macromodel) - verify "
                 "vccs / vcvs / cccs against your VACASK build")
    couplings = getattr(ir, "couplings", [])
    if couplings:
        L.append("// NOTE: mutual inductors (transformer coupling) are listed as "
                 "comments below - wire them up with your VACASK mutual-inductor primitive")
    L.append(f"subckt {ir.name} ( {' '.join(ir.ports)} )")
    for e in ir.elements:
        L.append("  " + _vc_instance(e))
    for i, (la, lb, kk) in enumerate(couplings, 1):
        L.append(f"  // mutual K{i}: {la} <-> {lb}, k = {_num(kk)}")
    L.append("ends")
    return "\n".join(L) + "\n"


def render(ir: CircuitIR, dialect: str) -> str:
    return (render_vacask(ir) if dialect == "vacask"
            else render_ngspice(ir))
