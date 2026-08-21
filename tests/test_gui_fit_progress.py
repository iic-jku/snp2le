# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_fit_progress.py - the GUI's non-blocking conversion, headless.

The point of moving the fit off the event loop is that the window stays alive
while it runs, so these tests drive the real MainWindow offscreen
(QT_QPA_PLATFORM=offscreen) and check the behaviour a frozen UI cannot have:
the event loop keeps turning during a fit, a burst of control changes starts one
extra fit rather than one per change, and Export writes the finished model
instead of quietly re-running the fit on the GUI thread.
Run with:  pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest                                             # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core import engine                            # noqa: E402
from snp2le.gui import fit_runner                         # noqa: E402
from snp2le.gui.main_window import MainWindow             # noqa: E402

_TIMEOUT = 60.0                     # generous: a fit on a slow CI box is still a fit


@pytest.fixture(scope="module")
def win():
    """One offscreen MainWindow for the module (Qt allows one QApplication)."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
    _settle(window, app)
    yield window
    window.close()
    app.processEvents()


def _app():
    return QtWidgets.QApplication.instance()


def _settle(window, app=None, timeout=_TIMEOUT):
    """Pump the event loop until no conversion is running."""
    app = app or _app()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if not window._fit.busy():
            app.processEvents()             # let the finished handler run
            return
        time.sleep(0.01)
    raise AssertionError("the conversion never finished")


def test_the_first_fit_runs_off_the_event_loop(win):
    """Construction leaves a usable window with a rendered result behind it."""
    assert not win._fit.busy()
    assert win._res is not None and win._res.ok
    assert win.top.exp_ng.isEnabled() and win.top.exp_va.isEnabled()


def test_the_strip_reports_the_outcome(win):
    """The standing outcome line is the completion notice: no polling needed."""
    text = win.fit_status.message.text()
    assert text.startswith("conversion complete")
    assert "poles" in text or "element" in text
    # isHidden(), not isVisible(): the window is never show()n in a headless run,
    # so isVisible() is False for every child regardless of what was asked for.
    assert win.fit_status.bar.isHidden(), "the bar must go when the fit ends"


def test_a_running_fit_shows_progress_and_keeps_the_ui_alive(win, monkeypatch):
    """While a fit runs the event loop still turns and the strip moves."""
    real = engine.convert

    def slow(state, net, progress=None):
        if progress is not None:
            progress(0.5, "halfway through a slow fit")
        time.sleep(0.8)                     # long enough to pass the bar's delay
        return real(state, net, progress=progress)

    monkeypatch.setattr(fit_runner.engine, "convert", slow)
    win.recompute()
    _app().processEvents()
    seen_running = []
    deadline = time.time() + _TIMEOUT
    while time.time() < deadline and win._fit.busy():
        _app().processEvents()
        snap = win._fit.snapshot()
        if snap.running:
            seen_running.append((snap.fraction, not win.fit_status.bar.isHidden()))
        time.sleep(0.05)
    _settle(win)
    assert seen_running, "the event loop never ran during the fit"
    assert max(f for f, _ in seen_running) > 0.0, "no progress was reported"
    assert any(visible for _, visible in seen_running), "the bar never appeared"


def test_a_burst_of_changes_starts_one_extra_fit(win, monkeypatch):
    """Dragging a control must not queue one conversion per intermediate value."""
    real = engine.convert
    orders = []

    def counting(state, net, progress=None):
        orders.append(state.max_order)
        time.sleep(0.3)
        return real(state, net, progress=progress)

    monkeypatch.setattr(fit_runner.engine, "convert", counting)
    _settle(win)
    orders.clear()
    for order in (10, 11, 12, 13):
        win.state.max_order = order
        win.recompute()
    _settle(win)
    assert orders == [10, 13], f"expected the first and the last fit, got {orders}"


def test_the_worker_state_is_a_snapshot(win, monkeypatch):
    """The worker must read the state it was handed, not one edited mid-fit."""
    real = engine.convert
    seen = []

    def capture(state, net, progress=None):
        time.sleep(0.3)                     # the test edits win.state meanwhile
        seen.append(state.max_order)
        return real(state, net, progress=progress)

    monkeypatch.setattr(fit_runner.engine, "convert", capture)
    _settle(win)
    seen.clear()
    win.state.max_order = 7
    win.recompute()
    _app().processEvents()
    win.state.max_order = 33                # edited while the worker runs
    _settle(win)
    assert seen[0] == 7, "the worker saw a state edited after it started"


def test_export_uses_the_finished_fit(win, monkeypatch):
    """Export must never convert inline: that is the freeze this change removed."""
    calls = []
    monkeypatch.setattr(fit_runner.engine, "convert",
                        lambda *a, **k: calls.append(1))
    warned = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[-1] if a else ""))
    saved = win._res
    try:
        win._res = None                     # nothing has finished yet
        win.on_export("ngspice")
        assert warned and "nothing to export" in warned[0]
        assert not calls, "Export ran a conversion on the GUI thread"
    finally:
        win._res = saved


def test_reset_clears_the_outcome_line(win):
    """Reset drops the previous outcome, then the reloaded example reports its own."""
    win.on_reset()
    # on_reset clears the strip and immediately recomputes, so what is on screen
    # here is the new run, never the finished line from before it.
    assert not win.fit_status.message.text().startswith("conversion complete")
    _settle(win)
    assert win.fit_status.message.text().startswith("conversion complete")


def test_shutdown_while_a_fit_runs_is_safe(win, monkeypatch):
    """Closing during a fit must not destroy a running QThread (that aborts Qt)."""
    real = engine.convert

    def slow(state, net, progress=None):
        time.sleep(0.5)
        return real(state, net, progress=progress)

    monkeypatch.setattr(fit_runner.engine, "convert", slow)
    _settle(win)
    win.recompute()
    _app().processEvents()
    assert win._fit.busy()
    win._fit.shutdown(msec=5000)            # the closeEvent path
    assert not win._fit.busy()
    _app().processEvents()


def test_changing_a_control_greys_export_before_the_fit_starts(win):
    """The recompute is debounced, so there is a window where nothing runs yet.

    Export must not stay live through it: `_res` still holds the previous
    settings' model, and writing that under the new settings is silent and wrong.
    """
    # Start from a completed conversion of our own: the shutdown test above
    # deliberately abandons a run, which leaves Export greyed.
    win.recompute()
    _settle(win)
    assert win.top.exp_ng.isEnabled()
    win.on_change()                             # what a control change emits
    assert not win._fit.busy(), "the debounce fired early, the window is untested"
    assert not win.top.exp_ng.isEnabled(), "Export stayed live during the debounce"
    assert not win.top.exp_va.isEnabled()
    _settle(win)                                # let the debounced fit run
    deadline = time.time() + _TIMEOUT
    while time.time() < deadline and not win.top.exp_ng.isEnabled():
        _app().processEvents()
        time.sleep(0.02)
    assert win.top.exp_ng.isEnabled(), "Export never came back"


def test_a_superseded_result_keeps_the_typed_extraction_frequency(win, monkeypatch):
    """A finished fit that a newer request already replaces must not write its
    own f_ext back over the value the user typed while it was running."""
    from snp2le.core.state import Results
    _settle(win)
    monkeypatch.setattr(win.design, "update_results", lambda res: None)
    monkeypatch.setattr(win.plots, "update_results", lambda res: None)
    monkeypatch.setattr(win._fit, "has_pending", lambda: True)
    win.top._set_fext(12e9)                     # what the user just typed
    stale = Results(ok=True, mode="structure")
    stale.metrics = {"f_extract": 3e9}          # what the outgoing fit used
    win._on_fit_finished(stale)
    assert win.top._f_extract_hz == pytest.approx(12e9)
    assert not win.top.exp_ng.isEnabled(), "a superseded model must not be exportable"
