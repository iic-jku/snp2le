# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_noise.py - the thermal-noise generator of a universal model (no Qt). Run with:  pytest -q

The noise a passive N-port emits is kT (I - S S^H) at its ports (Bosma).  The checks below
solve the emitted circuit itself, with a small AC noise analysis over the IR, and compare the
port noise against that formula, so a sign, a scale or a node name gone wrong in the netlist
fails here and not only in a simulator.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from snp2le.core import io, engine, netlist, noise
from snp2le.core.state import ConverterState


def _example(name):
    return io.load_touchstone(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "snp2le", "examples", name))


def _convert(name, order=6, passive=True, thermal=True):
    return engine.convert(ConverterState(mode="universal", max_order=order,
                                         enforce_passivity=passive, thermal_noise=thermal),
                          _example(name))


def _port_noise(ir, f, z0=50.0):
    """Port-voltage noise covariance per kT, ports terminated in noiseless z0, and the
    S-matrix of the same circuit.  Handles the R, C, V, G and F elements a universal model
    uses.  Every resistor netlist._silenced() does not silence is a noise source of 4kT/R."""
    nodes = sorted({n for e in ir.elements for n in e.nodes if n != "0"} | set(ir.ports))
    ni = {n: i for i, n in enumerate(nodes)}
    vs = [e for e in ir.elements if e.kind == "V"]
    bi = {e.name: len(nodes) + k for k, e in enumerate(vs)}
    dim = len(nodes) + len(vs)
    w = 2 * np.pi * f
    Y = np.zeros((dim, dim), complex)

    def at(n):
        return ni.get(n)

    def g2(a, b, y):
        for r, sr in ((at(a), 1), (at(b), -1)):
            for c, sc in ((at(a), 1), (at(b), -1)):
                if r is not None and c is not None:
                    Y[r, c] += sr * sc * y

    noisy = []
    for e in ir.elements:
        a, b = e.nodes
        if e.kind == "R":
            g2(a, b, 1.0 / e.value)
            if not netlist._silenced(e, ir):
                noisy.append(e)
        elif e.kind == "C":
            g2(a, b, 1j * w * e.value)
        elif e.kind == "V":
            k = bi[e.name]
            for n, s in ((at(a), 1), (at(b), -1)):
                if n is not None:
                    Y[n, k] += s
                    Y[k, n] += s
        elif e.kind == "G":                     # current gain * v(ctrl) from a through to b
            for r, sr in ((at(a), 1), (at(b), -1)):
                for c, sc in ((at(e.ctrl[0]), 1), (at(e.ctrl[1]), -1)):
                    if r is not None and c is not None:
                        Y[r, c] += sr * sc * e.value
        elif e.kind == "F":
            k = bi[e.ctrl[0]]
            for r, sr in ((at(a), 1), (at(b), -1)):
                if r is not None:
                    Y[r, k] += sr * e.value
    for p in ir.ports:
        g2(p, "0", 1.0 / z0)
    P = [ni[p] for p in ir.ports]

    cov = np.zeros((len(P), len(P)), complex)
    for e in noisy:                               # unit current from node a to node b
        J = np.zeros(dim, complex)
        if at(e.nodes[0]) is not None:
            J[at(e.nodes[0])] -= 1
        if at(e.nodes[1]) is not None:
            J[at(e.nodes[1])] += 1
        h = np.linalg.solve(Y, J)[P]
        cov += 4.0 / e.value * np.outer(h, np.conj(h))

    S = np.zeros((len(P), len(P)), complex)
    for j, pj in enumerate(P):                    # incident wave of 1 at port j
        J = np.zeros(dim, complex)
        J[pj] = 2.0 / np.sqrt(z0)                 # Norton source of a 2 V / sqrt(z0) source
        v = np.linalg.solve(Y, J)[P]
        a = np.zeros(len(P)); a[j] = 1.0
        S[:, j] = v / np.sqrt(z0) - a
    return cov, S


def _with_noise_flags(text):
    """parse_spice_subckt reads values only, so mark each resistor from its own line."""
    ir = netlist.parse_spice_subckt(text)
    silent = {ln.split()[0] for ln in text.splitlines() if ln.strip().endswith("noisy=0")}
    for e in ir.elements:
        if e.kind == "R":
            e.noisy = e.name not in silent
    return ir


# The frequencies are below, inside and above the data (120 to 200 GHz for the BPF and WPD).
_F = (1e9, 140e9, 161e9, 600e9, 5e12)


@pytest.mark.parametrize("name,order", [("bpf_ihp-sg13g2.s2p", 13), ("wpd_ihp-sg13g2.s3p", 6),
                                        ("blc_ihp-sg13g2.s4p", 6)])
def test_the_netlist_emits_bosma_noise(name, order):
    """With every port terminated in noiseless 50 ohm, v = sqrt(Z0) b, so the port noise
    must be Z0 kT (I - S S^H), correlations included.  Checked on the IR the engine built
    and on the Ngspice text parsed back, which also covers the 10 printed digits."""
    res = _convert(name, order)
    assert res.ok and res.noise.ok, res.noise.message
    for ir, tol in ((res.ir, 1e-9), (_with_noise_flags(res.ngspice), 1e-6)):
        for f in _F:
            cov, S = _port_noise(ir, f)
            want = 50.0 * (np.eye(len(S)) - S @ S.conj().T)
            assert np.max(np.abs(cov - want)) <= tol * 50.0, (name, f)


def test_a_75_ohm_reference_scales_the_injection():
    """The injection is 2/sqrt(Z0) per unit of noise wave, with Z0 read from the
    realisation's own reference resistor, so a file referred to 75 ohm works as well."""
    net = _example("wpd_ihp-sg13g2.s3p")
    net.renormalize(75.0)                                # passive at order 10, not at 6
    res = engine.convert(ConverterState(max_order=10, thermal_noise=True), net)
    assert res.noise.ok, res.noise.message
    assert " 75 noisy=0" in res.ngspice                    # the sensors are 75 ohm
    for f in _F:
        cov, S = _port_noise(res.ir, f, z0=75.0)
        want = 75.0 * (np.eye(3) - S @ S.conj().T)
        assert np.max(np.abs(cov - want)) <= 1e-9 * 75.0, f


def test_the_generator_leaves_the_signal_path_alone():
    """The S-parameters of the emitted circuit are the fit's with and without the
    generator, and the noiseless netlist is the noisy one minus the added lines."""
    on = _convert("wpd_ihp-sg13g2.s3p", thermal=True)
    off = _convert("wpd_ihp-sg13g2.s3p", thermal=False)
    for f in _F:
        assert np.max(np.abs(_port_noise(on.ir, f)[1] - _port_noise(off.ir, f)[1])) < 1e-12
    for a, b in ((on.ngspice, off.ngspice), (on.vacask, off.vacask)):
        added = [ln for ln in a.splitlines() if ln not in set(b.splitlines())]
        assert [ln for ln in a.splitlines() if ln not in added] == b.splitlines()
        assert added and all("nz" in ln or ln.startswith(("*", "//")) for ln in added)


def test_without_the_option_the_model_stays_noiseless():
    """The default is the noiseless model: no generator, no notes, every resistor silent
    and no noise at the ports."""
    res = _convert("wpd_ihp-sg13g2.s3p", thermal=False)
    assert res.noise is None
    assert not res.ir.notes and "nz_" not in res.ngspice + res.vacask
    cov, _ = _port_noise(res.ir, 161e9)
    assert np.max(np.abs(cov)) == 0.0


def test_only_the_sources_are_noisy_in_both_dialects():
    """Inside the noisy model the fit's resistors keep noisy=0, and the N source resistors
    are the only ones without it."""
    res = _convert("blc_ihp-sg13g2.s4p")
    n_ports = res.n_ports
    src = {f"Rnz_e{k + 1}" for k in range(n_ports)}
    assert res.noise.n_sources == n_ports
    assert res.noise.n_states == n_ports * res.model_order
    for line in res.ngspice.splitlines():
        if line.startswith("R"):
            assert ("noisy=0" in line) == (line.split()[0] not in src), line
    for line in res.vacask.splitlines():
        if " resistor r=" in line:
            assert ("noisy=0" in line) == (line.split()[0] not in src), line
    assert sum(ln.endswith(" resistor r=0.25") for ln in res.vacask.splitlines()) == n_ports
    assert res.dc.ok                                      # the generator adds no DC trouble


def test_the_factor_matches_on_a_dense_grid():
    """Matrix level: V V^H = I - S S^H well inside the check limit, at every frequency the
    engine checked, and the state-space form is the fitted model itself."""
    from snp2le.core import universal
    net = io.without_dc(_example("bpf_ihp-sg13g2.s2p"))
    fit = universal.fit_universal(net, max_order=13)
    A, B, C, D, E = noise.state_space(fit.vf)
    f = np.logspace(8, 13, 60)
    S, _ = noise._responses(A, B, np.zeros((len(A), 2)), C, D, np.zeros((2, 2)), f)
    S_vf = universal.model_sparams(fit.vf, f)
    assert np.max(np.abs(S - S_vf)) < 1e-10
    assert not np.any(E)
    K, V0 = noise.spectral_factor(A, B, C, D, float(np.max(np.abs(fit.vf.poles))))
    _, V = noise._responses(A, B, K, C, D, V0, f)
    phi = np.eye(2) - S @ np.conj(np.transpose(S, (0, 2, 1)))
    assert np.max(np.abs(V @ np.conj(np.transpose(V, (0, 2, 1))) - phi)) < 1e-10


def test_a_model_that_is_not_strictly_passive_is_refused():
    """No generator exists where sigma_max >= 1, so the model stays noiseless, the
    conversion itself still succeeds, and the reason names the fit's own sigma_max."""
    res = _convert("wpd_ihp-sg13g2.s3p", passive=False)  # the raw fit sits at 1.083
    assert res.ok and not res.noise.ok
    assert "not strictly passive" in res.noise.message
    assert f"sigma_max {res.sigma_max:.4f}" in res.noise.message
    assert res.noise.message in res.messages
    assert "nz_" not in res.ngspice + res.vacask and not res.ir.notes


def test_structure_mode_ignores_the_option():
    """Structure models keep their physical resistor noise, with or without the option."""
    st = ConverterState(mode="structure", structure_key="wilkinson-inphase",
                        thermal_noise=True)
    res = engine.convert(st, _example("wpd_ihp-sg13g2.s3p"))
    assert res.ok and res.noise is None
    assert "nz_" not in res.ngspice and "noisy" not in res.ngspice


def test_the_option_survives_a_design_round_trip():
    st = ConverterState(thermal_noise=True)
    assert ConverterState.from_json(st.to_json()).thermal_noise is True
    # a design saved before the option existed opens noiseless
    assert ConverterState.from_json('{"mode": "universal"}').thermal_noise is False


def test_cli_writes_the_noisy_netlist(tmp_path):
    from snp2le import cli
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "snp2le", "examples", "wpd_ihp-sg13g2.s3p")
    out = tmp_path / "wpd_le.spice"
    assert cli.main(["convert", src, "--order", "6", "--thermal-noise", "--format", "both",
                     "-o", str(out), "--quiet"]) == 0
    for path in (out, tmp_path / "wpd_le.inc"):
        text = path.read_text()
        assert "Rnz_e3" in text and "thermal noise of the passive" in text
    assert cli.main(["convert", src, "--order", "6", "-o", str(tmp_path / "plain.spice"),
                     "--quiet"]) == 0
    assert "nz_" not in (tmp_path / "plain.spice").read_text()


def test_cli_refuses_to_write_a_noiseless_model_it_was_asked_to_make_noisy(tmp_path, capsys):
    """Asked for thermal noise on a model that cannot carry it, the CLI writes nothing and
    exits non-zero, rather than leave a noiseless netlist under the requested name."""
    from snp2le import cli
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "snp2le", "examples", "wpd_ihp-sg13g2.s3p")
    out = tmp_path / "wpd_le.spice"
    assert cli.main(["convert", src, "--order", "6", "--no-passive", "--thermal-noise",
                     "-o", str(out)]) == 1
    assert not out.exists()
    assert "not strictly passive" in capsys.readouterr().err


def test_cli_thermal_noise_flags():
    from snp2le import cli
    p = cli.build_parser()
    assert p.parse_args(["convert", "x.s2p"]).thermal_noise is False
    assert p.parse_args(["convert", "x.s2p", "--thermal-noise"]).thermal_noise is True
    assert p.parse_args(["convert", "x.s2p", "--thermal-noise",
                         "--no-thermal-noise"]).thermal_noise is False
