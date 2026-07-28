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
    monkeypatch.setattr(win, "_end_vacask_poll",
                        lambda status, aborted: calls.append(status))
    win._sim_poll_deadline = time.time() - 10.0   # backstop already expired
    win._sim_vacask_seen = True
    win._poll_sim_result()
    assert calls == ["aborted!"]


def test_finished_after_stop_or_crash_is_a_noop(bench):
    """QProcess can emit finished after the run was already handled (user
    Stop, or errorOccurred on a crash); that must not restart the poll."""
    win, data, figs, sims = bench
    win._on_sim_finished(0, None)
    assert win._sim_timer is None
