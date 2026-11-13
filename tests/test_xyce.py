# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_xyce.py - the Xyce netlist dialect (no Qt).  Run with:  pytest -q

Xyce reads the Ngspice text except `noisy=0`, which it refuses, and its resistor has no other
noise switch.  So the dialect writes each silenced resistor as a VCCS that senses its own
terminals, a conductance without thermal noise.  The text checks run everywhere, the
simulator checks only where `Xyce` is on PATH (the IIC-OSIC-TOOLS container).
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from snp2le.core import io, engine, netlist
from snp2le.core.ir import CircuitIR, Element
from snp2le.core.state import ConverterState

_EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "snp2le", "examples")


def _path(name):
    return os.path.join(_EXAMPLES, name)


def _universal(name, order=6, thermal=False):
    return engine.convert(ConverterState(mode="universal", max_order=order,
                                         thermal_noise=thermal),
                          io.load_touchstone(_path(name)))


def _structure(name, key):
    net = io.load_touchstone(_path(name))
    f = np.asarray(net.f)
    return engine.convert(ConverterState(mode="structure", structure_key=key,
                                         f_extract=float(np.sqrt(f[0] * f[-1]))), net)


def _element_lines(text):
    return [ln for ln in text.splitlines() if ln and not ln.startswith(("*", "."))]


# bpf: plain fit.  blc: thermal-noise generator.  ind_d20: a 0 Hz sample, so the DC pin.
@pytest.mark.parametrize("name,order,thermal", [("bpf_ihp-sg13g2.s2p", 13, False),
                                                ("blc_ihp-sg13g2.s4p", 6, True),
                                                ("ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p", 6,
                                                 False)])
def test_silenced_resistors_become_noiseless_conductances(name, order, thermal):
    res = _universal(name, order, thermal)
    assert res.ok and (res.noise.ok if thermal else res.noise is None)
    ng, xy = res.ngspice.splitlines(), res.xyce.splitlines()
    assert not any("noisy" in ln for ln in _element_lines(res.xyce))
    assert xy[0] == ng[0].replace("(Ngspice / SPICE3)", "(Xyce)") and xy[1:6] == ng[1:6]
    assert len(xy) == len(ng)
    silenced = {e.name: e for e in res.ir.elements if netlist._silenced(e, res.ir)}
    assert silenced
    if name.startswith("ind_d20"):
        assert any(n.startswith("Rdcp") for n in silenced)
    for a, b in zip(ng[1:], xy[1:]):
        e = silenced.get(a.split()[0]) if a.endswith("noisy=0") else None
        if e is None:
            assert a == b
            continue
        tok = b.split()
        n0, n1 = e.nodes
        assert tok[:5] == ["G" + e.name, n0, n1, n0, n1]
        assert float(tok[5]) == 1.0 / e.value          # the same double, not a rounded one
    resistors = {ln.split()[0] for ln in xy if ln.startswith("R")}
    assert resistors == {e.name for e in res.ir.elements
                         if e.kind == "R" and e.name not in silenced}
    if thermal:
        assert resistors == {f"Rnz_e{k + 1}" for k in range(res.n_ports)}
    names = [ln.split()[0].upper() for ln in _element_lines(res.xyce)]
    assert len(names) == len(set(names))               # Xyce ignores case


@pytest.mark.parametrize("name,key", [("wpd_ihp-sg13g2.s3p", "wilkinson"),
                                      ("blc_ihp-sg13g2.s4p", "balun"),
                                      ("ind_ct_n2_d82_w4_s4_ihp-sg13g2.s3p", "inductor-ct")])
def test_a_structure_model_is_the_ngspice_text(name, key):
    """Its resistors are real loss and keep their noise, so nothing is substituted, and the
    couplings (a negative k on the balun) are SPICE K lines Xyce reads as they are."""
    res = _structure(name, key)
    assert res.ok, res.error
    ng, xy = res.ngspice.splitlines(), res.xyce.splitlines()
    assert xy[0].endswith("(Xyce)") and xy[1:] == ng[1:]


def test_a_name_clash_is_refused():
    ir = CircuitIR(name="m", ports=["p1"], physical=False)
    ir.add(Element("R", "R1", ("p1", "0"), 50.0))
    ir.add(Element("C", "gr1", ("p1", "0"), 1e-12))
    with pytest.raises(ValueError, match="GR1"):
        netlist.render_xyce(ir)
    ir.elements[1].name = "C1"
    assert "GR1 p1 0 p1 0 0.02" in netlist.render_xyce(ir)


def test_render_and_the_results_agree():
    res = _universal("wpd_ihp-sg13g2.s3p")
    assert set(netlist.EXTENSION) == set(netlist.DIALECTS)
    for dialect in netlist.DIALECTS:
        assert netlist.render(res.ir, dialect) == getattr(res, dialect)


def test_cli_writes_xyce_alone_or_with_the_others(tmp_path):
    from snp2le import cli
    src = _path("bpf_ihp-sg13g2.s2p")
    for fmt, outs in (("xyce", ["one.cir"]), ("all", ["one.spice", "one.inc", "one.cir"]),
                      ("both", ["one.spice", "one.inc"])):
        d = tmp_path / fmt
        assert cli.main(["convert", src, "--order", "6", "--format", fmt,
                         "-o", str(d / "one.cir"), "--quiet"]) == 0
        assert sorted(p.name for p in d.iterdir()) == sorted(outs)
    text = (tmp_path / "all" / "one.cir").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "* one - lumped-element equivalent (Xyce)"
    assert ".SUBCKT one p1 p2" in text and "noisy" not in text
    assert (tmp_path / "xyce" / "one.cir").read_text(encoding="utf-8") == text


# --------------------------------------------------------------------------- #
#  In Xyce itself
# --------------------------------------------------------------------------- #
needs_xyce = pytest.mark.skipif(shutil.which("Xyce") is None, reason="Xyce is not on PATH")
# Xyce's Boltzmann constant (older than CODATA's 1.380649e-23) and default 27 C
_K_T = 1.3806226e-23 * 300.15


def _xyce(tmp_path, res, bench, out):
    (tmp_path / "dut.cir").write_text(res.xyce, encoding="utf-8")
    (tmp_path / "tb.cir").write_text("* bench\n.include \"dut.cir\"\n" + "\n".join(bench)
                                     + "\n.END\n", encoding="utf-8")
    run = subprocess.run(["Xyce", "tb.cir"], cwd=tmp_path, capture_output=True, text=True,
                         timeout=600)
    assert run.returncode == 0 and (tmp_path / out).exists(), run.stdout[-2000:]
    return np.loadtxt(tmp_path / out, delimiter=",", skiprows=1, ndmin=2)


@needs_xyce
@pytest.mark.parametrize("res", [pytest.param(lambda: _universal("bpf_ihp-sg13g2.s2p", 13),
                                              id="bpf-universal-13"),
                                 pytest.param(lambda: _structure("blc_ihp-sg13g2.s4p", "balun"),
                                              id="blc-balun")])
def test_xyce_reproduces_the_model(tmp_path, res):
    """One copy of the subcircuit per driven port, each port in 50 ohm."""
    res = res()
    n, name = res.n_ports, res.ir.name
    f = np.asarray(res.freq)
    assert np.ptp(np.diff(f)) < 1e-6 * np.mean(np.diff(f))      # .AC LIN hits the data
    bench, probes = [], []
    for k in range(n):
        pins = [f"d{k}_{i}" for i in range(n)]
        bench += [f"V{k} s{k} 0 DC 0 AC 1", f"Rs{k} s{k} {pins[k]} 50"]
        bench += [f"Rt{k}_{i} {pins[i]} 0 50" for i in range(n) if i != k]
        bench.append(f"X{k} {' '.join(pins)} {name}")
        probes += pins
    bench += [f".AC LIN {len(f)} {f[0]:.17g} {f[-1]:.17g}",
              ".PRINT AC FORMAT=CSV FILE=ac.csv " + " ".join(f"VR({p}) VI({p})" for p in probes)]
    d = _xyce(tmp_path, res, bench, "ac.csv")
    v = d[:, 1::2] + 1j * d[:, 2::2]
    s = 2.0 * v.reshape(len(f), n, n).transpose(0, 2, 1) - np.eye(n)
    assert np.max(np.abs(s - np.asarray(res.model_s))) < 1e-6


@needs_xyce
@pytest.mark.parametrize("thermal", [False, True])
def test_xyce_noise_is_the_models(tmp_path, thermal):
    """Ports in noiseless 50 ohm (conductances, like the substitution): the noiseless model
    adds no noise at all, and with the generator each port carries the noise the nodal
    analysis of test_noise gives, which is Z0 kT (1 - (S S^H)_kk) there.  Written with
    noisy resistors instead, the fit's resistors alone gave 6 to 4e7 times the noise."""
    from test_noise import _port_noise
    res = _universal("wpd_ihp-sg13g2.s3p", 6, thermal)
    assert res.ok and (res.noise.ok if thermal else res.noise is None)
    n, name = res.n_ports, res.ir.name
    pins = [f"p{i}" for i in range(n)]
    bench = ["V1 s 0 DC 0 AC 1", "Gs s p0 s p0 0.02"]
    bench += [f"Gt{i} p{i} 0 p{i} 0 0.02" for i in range(1, n)]
    bench.append(f"X1 {' '.join(pins)} {name}")
    fs = (140e9, 161e9, 180e9)
    for k in range(n):
        bench_k = bench + [f".NOISE V(p{k}) V1 LIN {len(fs)} {fs[0]:.17g} {fs[-1]:.17g}",
                           f".PRINT NOISE FORMAT=CSV FILE=n{k}.csv ONOISE"]
        d = _xyce(tmp_path, res, bench_k, f"n{k}.csv")
        for fi, got in zip(d[:, 0], d[:, -1]):                     # ONOISE in V^2/Hz
            want = _K_T * _port_noise(res.ir, fi)[0][k, k].real
            assert (want > 0) == thermal
            assert got == pytest.approx(want, rel=1e-6, abs=1e-30), (k, fi)
