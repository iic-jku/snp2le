# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_thermal_noise.py - the Thermal noise control, headless.

The box is off by default, so a fresh window converts the noiseless model it always did.
Ticked, the conversion appends the passive's thermal noise and the Result panel says so.
A model that cannot carry it (not strictly passive) is converted and shown, but Export
refuses rather than write a noiseless netlist while the box says otherwise.  These tests
drive the real MainWindow offscreen (QT_QPA_PLATFORM=offscreen).  Run with: pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core import io                              # noqa: E402
from snp2le.core.state import ConverterState, Results   # noqa: E402
from snp2le.core.noise import NoiseHealth               # noqa: E402
from snp2le.gui.main_window import MainWindow           # noqa: E402
from snp2le.gui.widgets import noise_text               # noqa: E402

_WPD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "snp2le", "examples", "wpd_ihp-sg13g2.s3p")


def test_noise_text_names_what_the_netlist_carries():
    """Pure function, no window."""
    assert noise_text(Results(ok=True, mode="universal")) == "noiseless (ideal)"
    assert noise_text(Results(ok=True, mode="universal",
                              noise=NoiseHealth(True, "added"))) == "thermal ✓"
    assert noise_text(Results(ok=True, mode="universal",
                              noise=NoiseHealth(False, "no"))) == "NOT added"
    assert noise_text(Results(ok=True, mode="structure")) == "thermal (resistors)"
    assert noise_text(Results(ok=False, error="boom")) == "—"


@pytest.fixture(scope="module")
def win():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow(_WPD)
    yield w
    w.close()
    app.processEvents()


def _settle(win, timeout=60.0):
    """Pump the event loop until the conversion has finished (it runs on a worker)."""
    app = QtWidgets.QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if not win._fit.busy() and not win._timer.isActive():
            app.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("the conversion never finished")


@pytest.fixture()
def top(win):
    win.top.reset_controls()
    win._pull()
    yield win.top
    win.top.reset_controls()
    win._pull()


def test_off_by_default_and_on_the_universal_page(top):
    assert not top.thermal_noise.isChecked()
    assert top.values()["thermal_noise"] is False
    assert top.thermal_noise.parent() is top.uni_page    # hidden with the universal page


def test_ticking_it_adds_the_generator(win, top):
    top.thermal_noise.setChecked(True)                    # emits changed, debounced recompute
    _settle(win)
    assert win.state.thermal_noise is True
    assert win._res.noise is not None and win._res.noise.ok
    assert win.design.noise_out.value.text() == "thermal ✓"
    assert "Rnz_e1" in win.design.ngspice_edit.toPlainText()
    assert "Rnz_e1" in win.design.vacask_edit.toPlainText()
    top.thermal_noise.setChecked(False)
    _settle(win)
    assert win._res.noise is None
    assert win.design.noise_out.value.text() == "noiseless (ideal)"
    assert "nz_" not in win.design.ngspice_edit.toPlainText()


def test_a_model_that_cannot_carry_it_is_shown_but_not_exported(win, top, monkeypatch):
    """The raw WPD fit at order 6 sits at sigma_max 1.083: converted and plotted, flagged
    in the Result panel, and Export explains instead of opening a save dialog."""
    top.passive.setChecked(False)
    top.thermal_noise.setChecked(True)
    _settle(win)
    res = win._res
    assert res.ok and not res.noise.ok
    assert win.design.noise_out.value.text() == "NOT added"
    assert "not strictly passive" in win.design.msg_lbl.text()
    warned = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[2]))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *a, **k: pytest.fail("Export must not ask for a file"))
    win.on_export("ngspice")
    assert warned and "Untick 'Thermal noise'" in warned[0]


def test_the_option_reaches_a_saved_design_and_back(win, top):
    top.thermal_noise.setChecked(True)
    win._pull()
    saved = win.state.to_json()
    top.reset_controls()
    assert not top.thermal_noise.isChecked()
    top.set_values(ConverterState.from_json(saved))
    assert top.thermal_noise.isChecked()
    top.set_values(ConverterState())                      # a design without it unticks it
    assert not top.thermal_noise.isChecked()


def test_reset_unticks_it(win, top):
    top.thermal_noise.setChecked(True)
    top.reset_controls()
    assert not top.thermal_noise.isChecked()
