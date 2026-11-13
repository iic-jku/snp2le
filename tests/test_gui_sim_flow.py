# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_sim_flow.py - the GUI's simulation-result detection, headless.

No simulator is needed for the decisions MainWindow makes after a run: which
file in the testbench's plot_simulations/data/ counts as the result, how a
VACASK abort is told apart from a success or a failure, and that a finished or
stopped run cannot restart the poll.  These tests drive the real MainWindow
offscreen (QT_QPA_PLATFORM=offscreen), so they run in CI without a display.
Run with: pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.gui.main_window import MainWindow            # noqa: E402


@pytest.fixture(scope="module")
def win():
    """One offscreen MainWindow for the whole module (Qt allows only one
    QApplication per process, and constructing the window is the slow part)."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    yield w
    w.close()
    app.processEvents()


@pytest.fixture()
def bench(win, tmp_path):
    """Point the window at a synthetic testbench tree and reset its run state.
    Returns (window, data_dir, figures_dir, simulations_dir)."""
    xdir = tmp_path / "testbenches" / "xschem"
    data = xdir / "plot_simulations" / "data"
    figs = xdir / "plot_simulations" / "figures"
    sims = xdir / "simulations"
    for d in (data, figs, sims):
        d.mkdir(parents=True)
    (xdir / "tb_vacask.sch").write_text("dummy\n", encoding="utf-8")
    win._sch_path = str(xdir / "tb_vacask.sch")
    win._sim_simulator = "vacask"
    win._sim_start = time.time() - 5.0
    win._sim_proc = None
    win._sim_timer = None
    win._sim_poll_stem = "tb_vacask"
    win._sim_poll_last = None
    return win, data, figs, sims


def test_result_dir_ignores_the_figures_log_line(bench):
    """The VACASK postprocess reports the data table and then the figure PNG;
    the result folder must resolve to data/, never figures/ (the restructure
    put them in sibling folders)."""
    win, data, figs, sims = bench
    (sims / "vacask.log").write_text(
        "Analysis 'acsp' completed.\n"
        f"postprocess: wrote {(data / 'tb_vacask.txt').as_posix()}\n"
        f"postprocess: wrote {(figs / 'tb_vacask.png').as_posix()}\n",
        encoding="utf-8")
    assert os.path.normpath(win._sim_output_dir()) == os.path.normpath(str(data))


def test_result_dir_table_only_log_unchanged(bench):
    """A log with only table lines (the pre-restructure postprocess format)
    resolves exactly as before: the last table's folder."""
    win, data, figs, sims = bench
    (sims / "vacask.log").write_text(
        "postprocess: wrote /somewhere/tb_vacask.txt\n", encoding="utf-8")
    assert win._sim_output_dir().replace("\\", "/") == "/somewhere"


def test_aborted_marker_is_never_the_result(bench):
    """A fresh <stem>.aborted marker lands in the same folder with the same
    stem; even when it is the newest file it must not be picked for import."""
    win, data, figs, sims = bench
    table = data / "tb_vacask.txt"
    marker = data / "tb_vacask.aborted"
    table.write_text("x" * 64, encoding="utf-8")
    marker.write_text("singular matrix\n", encoding="utf-8")
    later = time.time() + 2.0                     # marker strictly newest
    os.utime(marker, (later, later))
    result = win._find_sim_result("tb_vacask")
    assert result is not None and result.endswith("tb_vacask.txt")


def test_abort_only_run_is_detected_as_abort(bench):
    """An aborted analysis writes the marker and no table: no result must be
    found, and the fresh marker must be visible to the poll."""
    win, data, figs, sims = bench
    (data / "tb_vacask.aborted").write_text("no sweep data\n", encoding="utf-8")
    assert win._find_sim_result("tb_vacask") is None
    assert win._fresh_abort_marker("tb_vacask")


def test_poll_ends_exactly_once(bench, monkeypatch):
    """When the abort condition and the expired absolute deadline are both
    true in the same tick, the poll must end once (as 'aborted!'), not twice."""
    win, data, figs, sims = bench
    (data / "tb_vacask.aborted").write_text("no sweep data\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(win, "_end_detached_poll",
                        lambda status, aborted: calls.append(status))
    win._sim_poll_deadline = time.time() - 10.0   # backstop already expired
    win._sim_detached_seen = True
    win._poll_sim_result()
    assert calls == ["aborted!"]


def test_finished_after_stop_or_crash_is_a_noop(bench):
    """QProcess can emit finished after the run was already handled (user
    Stop, or errorOccurred on a crash); that must not restart the poll."""
    win, data, figs, sims = bench
    win._on_sim_finished(0, None)
    assert win._sim_timer is None


# --------------------------------------------------------------------------- #
#  Xyce, the second simulator xschem runs detached
# --------------------------------------------------------------------------- #
import shutil                                               # noqa: E402

from snp2le.core import xschem                              # noqa: E402

_XYCE_RESULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "testbenches", "xschem", "plot_simulations", "data",
                            "two_port_tb_acsp_xyce.s2p")


@pytest.fixture()
def xyce_bench(bench):
    win, data, figs, sims = bench
    sch = os.path.join(os.path.dirname(win._sch_path), "tb_xyce.sch")
    with open(sch, "w", encoding="utf-8") as fh:
        fh.write("dummy\n")
    win._sch_path = sch
    win._sim_simulator = "xyce"
    win._sim_poll_stem = "tb_xyce"
    return win, data, sims


def test_the_simulator_list_offers_xyce(win):
    combo = win.top.simulator
    assert [combo.itemData(i) for i in range(combo.count())] == list(xschem.SIMULATORS)
    assert [combo.itemText(i) for i in range(combo.count())] == ["Ngspice", "VACASK", "Xyce"]


def test_loading_a_bench_picks_its_simulator(win, tmp_path, monkeypatch):
    for name, want in (("two_port_tb_acsp_xyce.sch", "xyce"),
                       ("two_port_tb_acsp_vacask.sch", "vacask"),
                       ("two_port_tb_acsp_ngspice.sch", "ngspice")):
        path = str(tmp_path / name)
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (path, "")))
        win.on_load_sch()
        assert win.top.simulator.currentData() == want


def test_a_xyce_run_imports_its_touchstone(xyce_bench):
    """Xyce writes S-parameters only as Touchstone: the poll finds the .s2p the .LIN line
    names, and the overlay reads it."""
    win, data, sims = xyce_bench
    shutil.copyfile(_XYCE_RESULT, data / "tb_xyce.s2p")         # written now, by this run
    (sims / "tb_xyce.spice").write_text(
        ".LIN sparcalc=1 file=../plot_simulations/data/tb_xyce.s2p\n", encoding="utf-8")
    result = win._find_sim_result("tb_xyce")
    assert os.path.normpath(result) == os.path.normpath(str(data / "tb_xyce.s2p"))
    assert win.plots.import_sim_file(result)
    assert sorted(k for k in win.plots._sim if k != "f") == ["S11", "S12", "S21", "S22"]
    win.plots.clear_sim()


def test_a_xyce_run_without_a_result_fails_once(xyce_bench, monkeypatch):
    win, data, sims = xyce_bench
    calls = []
    monkeypatch.setattr(win, "_end_detached_poll",
                        lambda status, aborted: calls.append((status, aborted)))
    monkeypatch.setattr(win, "_detached_running", lambda: False)
    win._sim_detached_seen = True                    # it ran, and left 5 s ago
    win._sim_detached_gone_at = time.time() - 5.0
    win._sim_poll_deadline = time.time() + 100.0
    win._poll_sim_result()
    assert calls == [("failed!", False)]


def test_show_output_names_the_simulator(win):
    """One log window serves VACASK and Xyce, so its title follows the run."""
    for sim, title in (("xyce", "Xyce output"), ("vacask", "VACASK output")):
        win._sim_simulator = sim
        win._sim_log_path = None
        win._start_log_tail()
        assert win._log_win.windowTitle() == title
        win._stop_log_tail()
    win._log_win.close()


def test_stop_kills_the_detached_xyce(win, monkeypatch):
    asked = []
    monkeypatch.setattr(xschem, "simulator_pids", lambda sim: asked.append(sim) or [])
    win._sim_simulator = "xyce"
    win._kill_detached()
    assert asked == ["xyce"]
