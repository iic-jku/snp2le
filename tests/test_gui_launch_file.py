# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_launch_file.py - the GUI opened on a command-line file, headless.

`snp2le <file.sNp>` reaches the GUI as MainWindow(snp_path).  The window must open on
that file rather than the bundled example, seed the fit range from it, convert it, and
come back to it on Reset.  A file that cannot be read must not stop the window from
opening: the example is loaded instead and the reason is reported once, in a dialog.
These tests drive the real MainWindow offscreen (QT_QPA_PLATFORM=offscreen), so they run
in CI without a display.  Run with: pytest -q
"""
import contextlib
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.gui.main_window import MainWindow            # noqa: E402

EXAMPLES = os.path.join(ROOT, "snp2le", "examples")
BPF = os.path.join(EXAMPLES, "bpf_ihp-sg13g2.s2p")       # the launch file (2-port)
EXAMPLE = os.path.join(EXAMPLES, "blc_ihp-sg13g2.s4p")   # what a bare launch opens (4-port)

_TIMEOUT = 60.0                     # generous: a fit on a slow CI box is still a fit


def _settle(window, timeout=_TIMEOUT):
    """Pump the event loop until no conversion is running.

    Conversions run on a worker thread (see gui/fit_runner.py), so `_res` only holds
    this call's result once the finished handler has run.  The first pass also fires
    the deferred launch-error report.  Same helper as in test_gui_fit_range.py."""
    app = QtWidgets.QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if not window._fit.busy():
            app.processEvents()             # let the finished handler run
            return window
        time.sleep(0.01)
    raise AssertionError("the conversion never finished")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def warnings(monkeypatch):
    """Record QMessageBox.warning calls as (title, text) instead of blocking on a
    modal dialog."""
    seen = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        lambda parent, title, text, *a, **k: seen.append((title, text)) or
        QtWidgets.QMessageBox.StandardButton.Ok)
    return seen


@contextlib.contextmanager
def _window(app, path):
    """A MainWindow opened on `path`, settled, and closed afterwards."""
    w = MainWindow(path)
    try:
        yield _settle(w)
    finally:
        w.close()
        app.processEvents()


def test_launch_file_is_loaded_and_converted(app, warnings, monkeypatch):
    monkeypatch.chdir(ROOT)                  # a relative path must come out absolute
    with _window(app, os.path.relpath(BPF, ROOT)) as w:
        assert w.state.source_path == BPF
        assert w.net.nports == 2
        v = w.top.values()                   # the fit range names the file's own span
        assert v["f_min"] == pytest.approx(float(w.net.f[0]))
        assert v["f_max"] == pytest.approx(float(w.net.f[-1]))
        assert "bpf_ihp-sg13g2" in w.design.file_lbl.text()
        assert w._res is not None and w._res.ok
        assert warnings == []


def test_reset_returns_to_the_launch_file(app, warnings, monkeypatch):
    with _window(app, BPF) as w:
        # load another file through the top bar, as a user would
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                            lambda *a, **k: (EXAMPLE, ""))
        w.on_load_snp()
        _settle(w)
        assert w.net.nports == 4 and w.state.source_path == EXAMPLE
        w.on_reset()
        _settle(w)
        assert w.net.nports == 2 and w.state.source_path == BPF
        assert warnings == []


def test_no_launch_file_still_opens_the_example(app, warnings):
    with _window(app, None) as w:
        assert w.state.source_path == EXAMPLE
        assert w.net.nports == 4
        assert warnings == []


@pytest.mark.parametrize("kind", ["missing", "garbage"])
def test_unreadable_launch_file_falls_back_to_the_example(app, warnings, tmp_path,
                                                          capsys, kind):
    path = str(tmp_path / f"{kind}.s2p")
    if kind == "garbage":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("this is not a Touchstone file\n")
    with _window(app, path) as w:
        assert w.state.source_path == EXAMPLE
        assert w.net.nports == 4
        assert w._res is not None and w._res.ok
        # reported once, naming the file, and echoed to stderr for a shell launch
        assert len(warnings) == 1
        title, text = warnings[0]
        assert title == "Load failed" and path in text and "example" in text
        assert f"snp2le: Could not load {path}" in capsys.readouterr().err
        # Reset stays on the example rather than failing on the bad file again
        w.on_reset()
        _settle(w)
        assert w.state.source_path == EXAMPLE
        assert len(warnings) == 1
