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
# 1e-12 (with the "resistor too small" warning), so we clamp R to that range. This
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


def balance_state_gains(ir, ground: str = "0"):
    """Equilibrate the vector-fit realisation so a high-order universal macromodel stays
    well-conditioned for solvers without internal matrix scaling (VACASK).

    scikit-rf realises each pole as a state node whose voltage is driven by tiny input gains
    (~1e-5) and read back into the port-sensor nodes by huge gains (~1e11).  That 1e-5..1e11
    spread makes the MNA matrix ill-conditioned: ngspice's Sparse solver equilibrates
    internally and copes, but VACASK does not, so above ~5 poles it mis-places the
    resonances (the order-5/6 break).  Scaling each state node's controlled sources - inputs
    up and outputs down by k = sqrt(max_output / max_input) - leaves every node voltage, and
    hence the transfer function, unchanged (lossless), while bringing the two gain groups
    together so the matrix entries span far fewer decades.  The scaling is lossless for ANY
    per-node factor, so tying complex-conjugate pole pairs (..._re_... / ..._im_...) to one
    factor only keeps their coupling symmetric - a conditioning nicety, not a correctness
    requirement (with or without it the result is identical in testing).  Used together with
    rescale_state_resistors (which tames the state self-conductances): the two passes take
    VACASK from >12 dB RMS error to ~0 on an order-13 fit, matching the analytic model.
    """
    state = {e.nodes[0] if e.nodes[1] == ground else e.nodes[1]
             for e in ir.elements if e.kind == "C" and ground in e.nodes}
    if not state:
        return ir
    inj = {s: 0.0 for s in state}                      # max gain driving the state node
    rd = {s: 0.0 for s in state}                       # max gain reading the state node
    for e in ir.elements:
        if e.kind not in ("G", "E", "F"):
            continue
        if e.nodes[1] in inj:                          # current injected into n- (the node)
            inj[e.nodes[1]] = max(inj[e.nodes[1]], abs(e.value))
        if e.ctrl and e.kind in ("G", "E"):            # vccs / vcvs sense their control nodes
            for cn in e.ctrl:
                if cn in rd:
                    rd[cn] = max(rd[cn], abs(e.value))
    k = {s: (rd[s] / inj[s]) ** 0.5 if inj[s] > 0 and rd[s] > 0 else 1.0 for s in state}
    for s in list(k):                                  # tie a complex pair to one factor
        if "_re_" in s:
            t = s.replace("_re_", "_im_")
            if t in k:
                k[s] = k[t] = (k[s] * k[t]) ** 0.5
    if all(abs(v - 1.0) <= 1e-12 for v in k.values()):
        return ir
    for e in ir.elements:
        if e.kind not in ("G", "E", "F"):
            continue
        f = k.get(e.nodes[1], 1.0)                     # scale up where it injects
        if e.ctrl and e.kind in ("G", "E"):
            for cn in e.ctrl:
                if cn in k:
                    f /= k[cn]                         # scale down where it reads
        e.value *= f
    return ir


def safe_subckt_name(text: str, fallback: str = "s_equivalent") -> str:
    """Turn an arbitrary string (e.g. an export file stem) into a subcircuit name that is
    valid in BOTH ngspice (SPICE3) and VACASK (Spectre).  Only letters, digits and '_' are
    portable: '-' is the subtraction operator and ' ', '.', '/' etc. are separators, so a
    name like 'two-port' becomes 'two_port' (otherwise VACASK would not parse it).  Runs of
    such characters collapse to a single '_', leading/trailing '_' are trimmed, a leading
    digit is prefixed, and an empty result falls back."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
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
#   * passives reference a model (resistor/capacitor/inductor). Sources are built in
# Like the ngspice subckt, the device models and their OSDI loads are NOT redeclared
# here - the testbench / VACASK common lib provides them (OSDI path
# /foss/pdks/ihp-sg13g2/libs.tech/vacask/osdi).
_VC_PASSIVE = {"R": ("resistor", "r"), "C": ("capacitor", "c"), "L": ("inductor", "l")}
_VC_SOURCE = {"V": "vsource", "G": "vccs", "E": "vcvs", "F": "cccs"}


# Ground node.  Unlike SPICE (where node "0" is always ground), Spectre / VACASK has no
# implicit ground - the testbench must declare one, and Xschem's spectre netlister declares
# it as `ground GND`, not `ground 0`.  A subckt that uses "0" therefore leaves those
# terminals floating (which silently collapses the universal macromodel to a flat / wrong
# response), so map the IR's ground node "0" to GND on the VACASK side.  ngspice keeps "0".
_VC_GROUND = "GND"


def _vc_node(n: str) -> str:
    return _VC_GROUND if n == "0" else n


def _vc_model(e: Element) -> str:
    return _VC_PASSIVE[e.kind][0] if e.kind in _VC_PASSIVE else _VC_SOURCE[e.kind]


def _vc_instance(e: Element) -> str:
    n = " ".join(_vc_node(x) for x in e.nodes)        # no spaces inside the ( ) node list
    if e.kind in _VC_PASSIVE:
        model, p = _VC_PASSIVE[e.kind]
        return f"{e.name} ({n}) {model} {p}={_num(e.value)}"
    if e.kind == "V":
        return f"{e.name} ({n}) vsource dc={_num(e.value)}"
    if e.kind == "G":                                 # VCCS, transconductance in A/V
        return (f"{e.name} ({n} {_vc_node(e.ctrl[0])} {_vc_node(e.ctrl[1])}) "
                f"vccs gain={_num(e.value)}")
    if e.kind == "E":                                 # VCVS, gain in V/V
        return (f"{e.name} ({n} {_vc_node(e.ctrl[0])} {_vc_node(e.ctrl[1])}) "
                f"vcvs gain={_num(e.value)}")
    if e.kind == "F":                                 # CCCS (senses a vsource branch)
        # VACASK names the controlling instance with ctlinst (not Spectre's probe), as a
        # quoted string: cccs ctlinst="V1" gain=...  (see VACASK test/test_ctlsrc.sim and
        # docs/dev-builtin.md). ccvs takes the same ctlinst parameter.
        return f'{e.name} ({n}) cccs ctlinst="{e.ctrl[0]}" gain={_num(e.value)}'
    raise KeyError(e.kind)


def render_vacask(ir: CircuitIR) -> str:
    couplings = getattr(ir, "couplings", [])
    kinds = [e.kind for e in ir.elements]
    L = [f"// {ir.name} - lumped-element equivalent (VACASK / Spectre), generated by snp2le"]
    L += [f"// {c}" for c in ir.comments[:4]]
    models = {_vc_model(e) for e in ir.elements}
    if couplings:                                     # builtin mutual-inductance model
        models.add("mutual")
    if models:                                        # models are declared by the testbench
        L.append("// device models needed (declared by your testbench): "
                 + ", ".join(sorted(models)))
    L.append(f"// NOTE: ground is '{_VC_GROUND}' - your testbench MUST declare it as the "
             "ground (Xschem's spectre netlist does this with `ground GND`); otherwise the "
             "circuit floats and the result is wrong.")
    L.append(f"subckt {ir.name} ({' '.join(ir.ports)})")
    for e in ir.elements:
        L.append("  " + _vc_instance(e))
    # builtin mutual inductance: name () mutual k=.. ind1="La" ind2="Lb"
    for i, (la, lb, kk) in enumerate(couplings, 1):
        L.append(f'  K{i} () mutual k={_num(kk)} ind1="{la}" ind2="{lb}"')
    L.append("ends")
    return "\n".join(L) + "\n"


def render(ir: CircuitIR, dialect: str) -> str:
    return (render_vacask(ir) if dialect == "vacask"
            else render_ngspice(ir))
