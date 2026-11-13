# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_xschem.py - sim_data_dir resolution (no Qt, no xschem needed). Run with: pytest -q

The result folder is the testbench's choice, so sim_data_dir must read it from the
testbench itself: the Ngspice `wrdata` target (from the .sch or the generated netlist),
the VACASK log's `postprocess: wrote` line, and only fall back to the bundled layout
(`plot_simulations/data/` next to the testbench) when neither says anything.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snp2le.core.xschem import sim_data_dir


def _make_sch(tmp_path, body, name="tb_ngspice.sch"):
    d = tmp_path / "testbenches" / "xschem"
    d.mkdir(parents=True, exist_ok=True)
    sch = d / name
    sch.write_text(body, encoding="utf-8")
    return sch


def test_ngspice_wrdata_bundled_layout(tmp_path):
    """The bundled testbenches' wrdata target resolves to plot_simulations/data next
    to the .sch."""
    sch = _make_sch(
        tmp_path, "value=\"\nwrdata ../plot_simulations/data/@schname\\\\\\\\.txt\n\"")
    assert sim_data_dir(str(sch), "ngspice") == str(
        tmp_path / "testbenches" / "xschem" / "plot_simulations" / "data")


def test_ngspice_wrdata_custom_folder(tmp_path):
    """A testbench writing somewhere else is followed there."""
    sch = _make_sch(tmp_path, "wrdata ../my_results/@schname.txt\n")
    assert sim_data_dir(str(sch), "ngspice") == str(
        tmp_path / "testbenches" / "xschem" / "my_results")


def test_ngspice_wrdata_from_generated_netlist(tmp_path):
    """No wrdata in the .sch: the generated netlist is the secondary source."""
    sch = _make_sch(tmp_path, "no control block here\n")
    sim = sch.parent / "simulations"
    sim.mkdir()
    (sim / "tb_ngspice.spice").write_text("wrdata out/tb_ngspice.txt\n", encoding="utf-8")
    assert sim_data_dir(str(sch), "ngspice") == str(sim / "out")


def test_vacask_folder_from_log(tmp_path):
    """The VACASK log's last 'postprocess: wrote' *table* line names the folder.  The
    postprocess also reports the figure PNG (written to the sibling figures/ folder),
    which must not win."""
    sch = _make_sch(tmp_path, "", name="tb_vacask.sch")
    sim = sch.parent / "simulations"
    sim.mkdir()
    (sim / "vacask.log").write_text(
        "Analysis 'acsp' completed.\n"
        "postprocess: wrote /somewhere/old/tb_vacask.txt\n"
        "postprocess: wrote /somewhere/new/tb_vacask.txt\n"
        "postprocess: wrote /somewhere/figures/tb_vacask.png\n", encoding="utf-8")
    assert sim_data_dir(str(sch), "vacask") == "/somewhere/new"


def test_fallback_bundled_layout(tmp_path):
    """Nothing to read: fall back to plot_simulations/data next to the testbench."""
    sch = _make_sch(tmp_path, "no wrdata anywhere\n")
    expect = str(tmp_path / "testbenches" / "xschem" / "plot_simulations" / "data")
    assert sim_data_dir(str(sch), "ngspice") == expect
    assert sim_data_dir(str(sch), "vacask") == expect
    assert sim_data_dir(str(sch), "xyce") == expect


# --------------------------------------------------------------------------- #
#  Xyce
# --------------------------------------------------------------------------- #
import re                                                  # noqa: E402
import time                                                # noqa: E402

from snp2le.core import xschem                             # noqa: E402

_BENCHES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "testbenches", "xschem")


def test_xyce_lin_file_bundled_layout(tmp_path):
    """Xyce's result is the .LIN FILE= target, read like Ngspice's wrdata."""
    sch = _make_sch(tmp_path, "value=\"\n.LIN SPARCALC=1 FORMAT=TOUCHSTONE2 "
                    "FILE=../plot_simulations/data/@schname\\\\.s2p\n\"",
                    name="tb_xyce.sch")
    assert sim_data_dir(str(sch), "xyce") == str(
        tmp_path / "testbenches" / "xschem" / "plot_simulations" / "data")


def test_xyce_lin_file_from_generated_netlist(tmp_path):
    sch = _make_sch(tmp_path, "no analysis here\n", name="tb_xyce.sch")
    sim = sch.parent / "simulations"
    sim.mkdir()
    (sim / "tb_xyce.spice").write_text(".lin sparcalc=1 file=out/tb_xyce.s2p\n",
                                       encoding="utf-8")
    assert sim_data_dir(str(sch), "xyce") == str(sim / "out")
    assert sim_data_dir(str(_make_sch(tmp_path, "", name="other_xyce.sch")), "xyce") == str(
        tmp_path / "testbenches" / "xschem" / "plot_simulations" / "data")


def test_sim_range_for_every_simulator(tmp_path):
    xschem.write_sim_range(str(tmp_path), 1.2e11, 2e11)
    assert (tmp_path / "sim_range.cir").read_text(encoding="utf-8").splitlines()[1:] == [
        ".param f_min=1.200000e+11", ".param f_max=2.000000e+11"]
    assert "var f_max = 2.000000e+11" in (tmp_path / "sim_range.inc").read_text()
    assert ".csparam f_min=1.200000e+11" in (tmp_path / "sim_range.spice").read_text()


def test_xyce_runs_on_xschems_xyce_entry_with_its_console_logged():
    prog, args, cwd = xschem.simulate_command(
        os.path.join(_BENCHES, "two_port_tb_acsp_xyce.sch"), show_output=False,
        simulator="xyce")
    tcl = args[args.index("--command") + 1]
    assert prog == "xschem" and cwd == _BENCHES and args[-1] == "two_port_tb_acsp_xyce.sch"
    assert 'set sim(spice,3,cmd) {Xyce "$N" >& xyce.log}' in tcl
    assert "set sim(spice,default) 3" in tcl and "xschem set netlist_type spice" in tcl
    assert tcl.endswith("xschem netlist; simulate")
    assert xschem.sim_log_path(os.path.join(_BENCHES, "x.sch"), "xyce").endswith(
        os.path.join("simulations", "xyce.log"))


def test_the_bundled_xyce_benches():
    """Each reads the exported Xyce netlist and the synced band, drives every port, writes
    Touchstone where the GUI looks, and grounds Xschem's GND, which Xyce leaves floating
    without REPLACEGROUND (the model was then off by up to 0.96 in S)."""
    for n, word in ((2, "two"), (3, "three"), (4, "four")):
        path = os.path.join(_BENCHES, f"{word}_port_tb_acsp_xyce.sch")
        text = open(path, encoding="utf-8").read()
        assert xschem.simulator_for(path) == "xyce"
        assert f".include ../../../netlist/xyce/{word}_port.cir" in text
        assert ".include ../sim_range.cir" in text
        assert ".PREPROCESS REPLACEGROUND TRUE" in text
        assert re.search(r"\.LIN .*FILE=\.\./plot_simulations/data/@schname\S*\.s%dp" % n, text)
        assert sorted(re.findall(r'name=P(\d) value="port=(\d) z0=50"', text)) == [
            (str(k), str(k)) for k in range(1, n + 1)]
        assert sim_data_dir(path, "xyce") == os.path.join(_BENCHES, "plot_simulations", "data")


def _touch(path, mtime):
    path.write_text("x" * 64, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_find_result_takes_the_benchs_own_touchstone(tmp_path):
    since = time.time()
    _touch(tmp_path / "tb_xyce.s2p", since + 1)
    _touch(tmp_path / "tb_xyce.aborted", since + 2)              # never a result
    assert xschem.find_result(str(tmp_path), "tb_xyce", since) == str(tmp_path / "tb_xyce.s2p")


def test_find_result_never_takes_the_previous_benchs_result(tmp_path):
    """Two runs back to back: the first bench's result, written just before the second run
    started, passed the 1 s of grace and was imported as the second bench's."""
    since = time.time()
    _touch(tmp_path / "two_port_tb_acsp_xyce.s2p", since - 0.5)
    _touch(tmp_path / "two_port_tb_acsp_ngspice.txt", since - 0.5)    # an Ngspice table too
    assert xschem.find_result(str(tmp_path), "three_port_tb_acsp_xyce", since) is None
    assert xschem.find_result(str(tmp_path), "three_port_tb_acsp_ngspice", since) is None
    _touch(tmp_path / "three_port_tb_acsp_xyce.s3p", since - 0.5)  # own name: the grace holds
    assert xschem.find_result(str(tmp_path), "three_port_tb_acsp_xyce", since) == str(
        tmp_path / "three_port_tb_acsp_xyce.s3p")


def test_find_result_falls_back_to_a_fresh_table_or_touchstone(tmp_path):
    since = time.time()
    _touch(tmp_path / "renamed.s4p", since + 1)
    _touch(tmp_path / "figure.png", since + 2)
    assert xschem.find_result(str(tmp_path), "tb_xyce", since) == str(tmp_path / "renamed.s4p")
    _touch(tmp_path / "renamed.txt", since + 3)
    assert xschem.find_result(str(tmp_path), "tb_xyce", since) == str(tmp_path / "renamed.txt")


def test_previous_results_are_the_benchs_own(tmp_path):
    for name in ("tb.txt", "tb.aborted", "tb.s2p", "tb.S10P", "tb.png", "tb_more.s2p",
                 "other.s2p", "tb.sp"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert sorted(os.path.basename(p) for p in xschem.previous_results(str(tmp_path), "tb")) \
        == ["tb.S10P", "tb.aborted", "tb.s2p", "tb.txt"]
    assert xschem.previous_results(str(tmp_path / "missing"), "tb") == []


def test_a_zombie_simulator_is_not_running(tmp_path, monkeypatch):
    """xschem leaves the simulator to PID 1, and a container whose PID 1 reaps nothing keeps
    every finished run as a zombie of that name.  Counted as running, a run that failed at
    once was only reported at its deadline."""
    for pid, comm, state in ((101, "Xyce", "S"), (102, "Xyce", "Z"), (103, "vacask", "R"),
                             (104, "vacask", "Z"), (105, "bash", "S")):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "comm").write_text(comm + "\n", encoding="utf-8")
        (d / "stat").write_text(f"{pid} ({comm}) {state} 1 {pid} {pid} 0 -1\n", encoding="utf-8")
    (tmp_path / "self").mkdir()
    monkeypatch.setattr(xschem, "_PROC", str(tmp_path))
    assert xschem.simulator_pids("xyce") == [101]
    assert xschem.simulator_pids("vacask") == [103]
    assert xschem.simulator_running("xyce") and not xschem.simulator_running("ngspice")
