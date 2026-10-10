# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_wideband_inductor.py - the wideband inductor structures in the window, headless.

A wideband model has no extraction frequency, so selecting one hides f_ext and puts the
'Basic model' tick box in the option slot, without widening the control strip (it has to
fit a 1920 px screen).  The Result panel names the top of the fitted band instead of f_ext,
and a values table longer than 12 rows goes in two columns.  These tests drive the real
MainWindow offscreen (QT_QPA_PLATFORM=offscreen).  Run with: pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core.state import ConverterState            # noqa: E402
from snp2le.gui.main_window import MainWindow           # noqa: E402

_IND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "snp2le", "examples", "ind_500pH_ihp-sg13cmos5l.s2p")


@pytest.fixture(scope="module")
def win():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow(_IND)
    yield w
    w.close()
    app.processEvents()


def _settle(win, timeout=120.0):
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


def _select(top, key):
    top.mode.setCurrentIndex(top.mode.findData("structure"))
    top.structure.setCurrentIndex(top.structure.findData(key))


def test_a_wideband_structure_swaps_f_ext_for_basic(win, top):
    _select(top, "inductor-pi")
    assert not top.f_ext_box.isHidden()
    assert top.opt_box.currentWidget() is top._opt_empty
    _select(top, "inductor-wideband")
    assert top.f_ext_box.isHidden()
    assert top.opt_box.currentWidget() is top.basic_box
    _select(top, "inductor-pi")
    assert not top.f_ext_box.isHidden()


def test_the_center_tap_is_third_but_never_the_default(win):
    """It sits right under the wideband inductor, yet a 3-port in structure mode still opens
    on the in-phase Wilkinson, also when a wideband 2-port model was selected before."""
    from snp2le.gui.top_bar import TopBar
    bar = TopBar()
    try:
        assert [bar.structure.itemData(i) for i in range(3)] == [
            "inductor-pi", "inductor-wideband", "inductor-ct"]
        bar.set_ports(3)
        _select(bar, "inductor-pi")                  # disabled for a 3-port, so it moves on
        assert bar.structure.currentData() == "wilkinson-inphase"
        bar.set_ports(2)
        _select(bar, "inductor-wideband")
        bar.set_ports(3)
        assert bar.structure.currentData() == "wilkinson-inphase"
        bar.set_ports(2)
        assert bar.structure.currentData() == "inductor-pi"
    finally:
        bar.close()


def test_the_strip_does_not_grow(win, top):
    """The option slot is sized to its widest page and 'Basic model' is narrower than
    'Resistive loss', so the strip keeps the width it has in universal mode."""
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    universal = top.minimumSizeHint().width()
    _select(top, "inductor-wideband")
    app.processEvents()
    assert top.minimumSizeHint().width() == universal
    assert top.basic_box.sizeHint().width() <= top.iso_r_box.sizeHint().width()


def test_the_result_names_the_fitted_band(win, top):
    _select(top, "inductor-wideband")
    _settle(win)
    res = win._res
    assert res.ok, res.error
    assert win.design.order_out.label.text() == "fitted up to"
    assert win.design.order_out.value.text() == "50 GHz"
    assert "coil segments" in win.design.msg_lbl.text()
    # 13 values: two columns, series branch left and substrate right
    host = win.design.values_host.itemAt(0).widget()
    grid = host.layout()
    assert isinstance(grid, QtWidgets.QGridLayout) and grid.columnCount() == 2
    assert grid.rowCount() == 7
    _select(top, "inductor-pi")
    _settle(win)
    assert win.design.order_out.label.text() == "ext. frequency"
    assert win.design.values_host.count() == len(win._res.value_rows)   # one column


def test_basic_reaches_the_conversion(win, top):
    _select(top, "inductor-wideband")
    top.basic.setChecked(True)
    _settle(win)
    assert win.state.basic_model is True
    assert win._res.metrics["basic"] and win._res.metrics["segments"] == 1
    assert len(win._res.value_rows) == 11
    assert win.design.values_host.count() == 11                          # one column


def test_basic_reaches_a_saved_design_and_back(win, top):
    top.basic.setChecked(True)
    win._pull()
    saved = win.state.to_json()
    top.reset_controls()
    assert not top.basic.isChecked()
    top.set_values(ConverterState.from_json(saved))
    assert top.basic.isChecked()
    top.set_values(ConverterState())                      # a design without it unticks it
    assert not top.basic.isChecked()
