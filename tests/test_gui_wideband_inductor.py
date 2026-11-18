# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_wideband_inductor.py - the wideband inductor structures in the window, headless.

A wideband model has no extraction frequency, so selecting one swaps f_ext and the option
slot for its own page: 'Basic model', Segments (Center tap for the 3-port), 'Peak-Q weight'
and 'Measured data'.  The page must not widen the control strip (it has to fit a 1920 px
screen) and at its natural width must keep every gap one _GAP, so its drop-down takes the
spare width.  The
Result panel names the top of the fitted band instead of f_ext, and a values table longer
than 12 rows goes in two columns.  These tests drive the real MainWindow and TopBar
offscreen (QT_QPA_PLATFORM=offscreen).  Run with: pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")

from snp2le.core.state import ConverterState            # noqa: E402
from snp2le.gui.main_window import MainWindow           # noqa: E402
from snp2le.gui.style import build_stylesheet           # noqa: E402
from snp2le.gui.top_bar import TopBar, _GAP             # noqa: E402

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


@pytest.fixture()
def bar(win):
    """A bare TopBar with the app stylesheet, laid out at its natural width."""
    app = QtWidgets.QApplication.instance()
    app.setStyleSheet(build_stylesheet())
    t = TopBar()
    t.resize(t.sizeHint().width(), t.sizeHint().height())
    t.show()
    app.processEvents()
    yield t
    t.close()
    app.processEvents()


def _select(top, key):
    top.mode.setCurrentIndex(top.mode.findData("structure"))
    top.structure.setCurrentIndex(top.structure.findData(key))


def test_a_wideband_structure_gets_its_own_page(bar):
    bar.set_ports(2)
    _select(bar, "inductor-pi")
    assert bar.mode_stack.currentWidget() is bar.struct_page
    _select(bar, "inductor-wideband")
    assert bar.mode_stack.currentWidget() is bar.wide_page
    assert not bar.segments_box.isHidden() and bar.ct_box.isHidden()
    bar.set_ports(3)
    _select(bar, "inductor-ct")
    assert bar.mode_stack.currentWidget() is bar.wide_page
    assert bar.segments_box.isHidden() and not bar.ct_box.isHidden()
    bar.mode.setCurrentIndex(bar.mode.findData("universal"))
    assert bar.mode_stack.currentWidget() is bar.uni_page


def test_the_page_keeps_the_strip_width_and_the_gaps(bar):
    """The page is no wider than the universal one, and its drop-down absorbs the spare
    width, so the fit range sits one _GAP after 'Measured data' as everywhere else."""
    app = QtWidgets.QApplication.instance()
    universal = bar.minimumSizeHint().width()
    row = bar.layout().itemAt(1).widget()

    def span(w):
        x = w.mapTo(row, QtCore.QPoint(0, 0)).x()
        return x, x + w.width()

    for ports, key in ((2, "inductor-wideband"), (3, "inductor-ct")):
        bar.set_ports(ports)
        _select(bar, key)
        bar.layout().activate()
        app.processEvents()
        assert bar.minimumSizeHint().width() == universal, key
        assert bar.wide_page.sizeHint().width() <= bar.uni_page.sizeHint().width(), key
        assert span(bar.band_box)[0] - span(bar.measured)[1] == _GAP, key


def test_the_tick_boxes_sit_on_the_button_line(bar):
    """Built like 'Enforce passivity': two lines, indicator pinned to the top."""
    bar.set_ports(2)
    _select(bar, "inductor-wideband")
    bar.layout().activate()
    QtWidgets.QApplication.instance().processEvents()
    row = bar.layout().itemAt(1).widget()
    button_y = bar.run_sim.mapTo(row, QtCore.QPoint(0, 0)).y()
    for cb in (bar.basic, bar.peak_q, bar.measured):
        opt = QtWidgets.QStyleOptionButton()
        cb.initStyleOption(opt)
        rect = cb.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator, opt, cb)
        assert cb.mapTo(row, rect.topLeft()).y() == button_y, cb.text()
        assert cb.objectName() == "wrapCheck" and "\n" in cb.text()


def test_basic_pins_the_segments_and_gives_them_back(bar):
    bar.set_ports(2)
    _select(bar, "inductor-wideband")
    bar.coil_segments.setCurrentIndex(bar.coil_segments.findData(3))
    assert bar.values()["coil_segments"] == 3
    bar.basic.setChecked(True)
    assert bar.coil_segments.currentData() == 1 and not bar.coil_segments.isEnabled()
    assert bar.values()["coil_segments"] == 0 and bar.values()["basic_model"] is True
    bar.basic.setChecked(False)
    assert bar.coil_segments.currentData() == 3 and bar.coil_segments.isEnabled()
    assert bar.values()["coil_segments"] == 3


def test_loading_a_design_releases_a_pinned_segment_count(bar):
    """'Basic model' ticked, then a design without it: Segments shows the design's count
    and can be changed again."""
    bar.set_ports(2)
    _select(bar, "inductor-wideband")
    bar.basic.setChecked(True)
    assert not bar.coil_segments.isEnabled()
    bar.set_values(ConverterState(mode="structure", structure_key="inductor-wideband",
                                  coil_segments=2))
    assert bar.coil_segments.isEnabled() and bar.coil_segments.currentData() == 2
    bar.set_values(ConverterState(mode="structure", structure_key="inductor-wideband",
                                  basic_model=True))
    assert not bar.coil_segments.isEnabled() and bar.coil_segments.currentData() == 1
    bar.basic.setChecked(False)
    assert bar.coil_segments.isEnabled() and bar.coil_segments.currentData() == 0


def test_a_hidden_segment_count_never_reaches_the_center_tap_fit(bar):
    """The center-tapped page has no Segments, so a count set on the 2-port page stays
    behind instead of fixing the center-tapped fit unseen."""
    bar.set_ports(2)
    _select(bar, "inductor-wideband")
    bar.coil_segments.setCurrentIndex(bar.coil_segments.findData(1))
    assert bar.values()["coil_segments"] == 1
    bar.set_ports(3)
    _select(bar, "inductor-ct")
    assert bar.segments_box.isHidden()
    assert bar.values()["coil_segments"] == 0
    bar.set_ports(2)
    _select(bar, "inductor-wideband")
    assert bar.values()["coil_segments"] == 1


def test_the_values_the_bar_reports(bar):
    """Tick boxes carry inductor_fit's default weights, the substrate is CLI only."""
    v = bar.values()
    assert (v["coil_segments"], v["substrate"], v["peak_q_weight"], v["shunt_accuracy"],
            v["center_tap"]) == (0, "auto", 0.0, 0.0, 0)
    bar.set_ports(3)
    _select(bar, "inductor-ct")
    bar.peak_q.setChecked(True)
    bar.measured.setChecked(True)
    bar.center_tap.setCurrentIndex(bar.center_tap.findData(1))
    v = bar.values()
    assert (v["peak_q_weight"], v["shunt_accuracy"], v["center_tap"]) == (2.0, 0.01, 1)


def test_the_options_reach_a_saved_design_and_back(win, top):
    _select(top, "inductor-wideband")
    top.coil_segments.setCurrentIndex(top.coil_segments.findData(2))
    top.center_tap.setCurrentIndex(top.center_tap.findData(3))
    top.peak_q.setChecked(True)
    top.measured.setChecked(True)
    win._pull()
    saved = win.state.to_json()
    top.reset_controls()
    assert top.coil_segments.currentData() == 0 and not top.peak_q.isChecked()
    top.set_values(ConverterState.from_json(saved))
    assert top.coil_segments.currentData() == 2 and top.center_tap.currentData() == 3
    assert top.peak_q.isChecked() and top.measured.isChecked()
    top.set_values(ConverterState())                      # a design without them
    assert top.coil_segments.currentData() == 0 and top.center_tap.currentData() == 0
    assert not top.peak_q.isChecked() and not top.measured.isChecked()


def test_a_cli_only_value_never_reaches_a_gui_conversion(win, top):
    """A design asking for 5 segments, another weight or a fixed substrate shows the
    nearest control state, and the pull that follows a load replaces it by what is shown."""
    top.set_values(ConverterState(mode="structure", structure_key="inductor-wideband",
                                  coil_segments=5, substrate="symmetric", peak_q_weight=5.0,
                                  shunt_accuracy=0.1))
    win._pull()
    s = win.state
    assert (s.coil_segments, s.substrate, s.peak_q_weight, s.shunt_accuracy) == (
        0, "auto", 2.0, 0.01)


def test_the_options_reach_the_conversion(win, top):
    _select(top, "inductor-wideband")
    top.coil_segments.setCurrentIndex(top.coil_segments.findData(1))
    top.peak_q.setChecked(True)
    top.measured.setChecked(True)
    _settle(win)
    res = win._res
    assert res.ok, res.error
    assert res.metrics["segments"] == 1
    text = win.design.msg_lbl.text()
    assert "1 coil segment (set)" in text
    assert "peak-Q weight 2" in text and "shunt accuracy 0.01" in text


def test_reset_restores_the_defaults(win, top):
    _select(top, "inductor-wideband")
    top.basic.setChecked(True)
    top.peak_q.setChecked(True)
    top.measured.setChecked(True)
    top.center_tap.setCurrentIndex(2)
    top.reset_controls()
    assert not top.basic.isChecked() and not top.peak_q.isChecked()
    assert not top.measured.isChecked()
    assert top.coil_segments.currentData() == 0 and top.coil_segments.isEnabled()
    assert top.center_tap.currentData() == 0


def test_the_center_tap_is_third_but_never_the_default(bar):
    """It sits right under the wideband inductor, yet a 3-port in structure mode still opens
    on the in-phase Wilkinson, also when a wideband 2-port model was selected before."""
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
