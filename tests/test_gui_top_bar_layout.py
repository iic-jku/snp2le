# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_top_bar_layout.py - the tick boxes in the control strip, headless.

'Enforce passivity', 'Thermal noise' and 'Show output' are built the same way (a caption
slot, then a two-line box) for two reasons: wrapped text keeps the bar narrow, and the
identical shape is what puts the indicators on the same line.  Each is easy to break by
editing it alone, and none shows up in any functional test, so they are pinned here.
Run with: pytest -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")

from snp2le.gui.style import build_stylesheet                  # noqa: E402
from snp2le.gui.top_bar import (TopBar, _DIVIDER_PAD, _DIVIDER_SHARE,  # noqa: E402
                                _GAP)


@pytest.fixture(scope="module")
def bar():
    """A laid-out TopBar with the app stylesheet applied, since the caption font size
    comes from there and it is what makes the two caption slots equally tall."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyleSheet(build_stylesheet())
    t = TopBar()
    t.resize(1500, t.sizeHint().height())
    t.show()
    app.processEvents()
    yield t
    t.close()
    app.processEvents()


def _indicator_y(cb, ref):
    """Top edge of the tick box itself (not the widget) in `ref` coordinates."""
    opt = QtWidgets.QStyleOptionButton()
    cb.initStyleOption(opt)
    rect = cb.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator, opt, cb)
    return cb.mapTo(ref, rect.topLeft()).y(), rect.height()


def test_the_tick_boxes_share_a_line(bar):
    row = bar.layout().itemAt(1).widget()
    passive = _indicator_y(bar.passive, row)
    assert _indicator_y(bar.thermal_noise, row) == passive
    assert _indicator_y(bar.sim_output, row) == passive


def test_the_tick_boxes_sit_on_the_button_line(bar):
    """Their top edge is the buttons' top edge.  A wrapped label centres the indicator
    against both lines by default, which drops it 8 px below everything else in the row,
    so the two boxes carry #wrapCheck and style.py pins the indicator to the top."""
    row = bar.layout().itemAt(1).widget()
    button_y = bar.run_sim.mapTo(row, QtCore.QPoint(0, 0)).y()
    for cb in (bar.passive, bar.thermal_noise, bar.sim_output):
        assert _indicator_y(cb, row)[0] == button_y
        assert cb.objectName() == "wrapCheck"


def _laid_out(width_extra):
    """A separate TopBar, `width_extra` px wider than it needs, so the shared fixture's
    geometry stays untouched."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyleSheet(build_stylesheet())
    t = TopBar()
    t.resize(t.sizeHint().width() + width_extra, t.sizeHint().height())
    t.show()
    _pump(t)
    return t


def _pump(t):
    app = QtWidgets.QApplication.instance()
    for _ in range(4):                 # the fillers settle over a LayoutRequest round trip
        t.layout().activate()
        app.processEvents()


def _span(w, ref):
    x = w.mapTo(ref, QtCore.QPoint(0, 0)).x()
    return x, x + w.width()


def _column(t, w):
    """The span of the row item that holds `w`, its caption included: a caption wider than
    its field (the font decides) belongs to the column, not to the gap."""
    for host in (t._controls, t.uni_page, t.struct_page, t.wide_page):
        lay = host.layout()
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item.widget() is w or (item.layout() is not None and item.layout().indexOf(w) >= 0):
                x = host.mapTo(t, item.geometry().topLeft()).x()
                return x, x + item.geometry().width()
    raise LookupError(w)


def _gap(t, a, b):
    return _column(t, b)[0] - _column(t, a)[1]


def _gaps(t):
    """The gaps the tests compare."""
    return {"button": _gap(t, t.export, t.load_sch), "mode": _gap(t, t.mode, t.structure),
            "page": _gap(t, t.order, t.passive),
            "divider": (_gap(t, t.band_box, t.sep), _gap(t, t.sep, t.export))}


def test_the_divider_has_the_same_gap_on_both_sides():
    """The conversion controls end and the action buttons start the same distance from the
    vertical divider, _DIVIDER_PAD more than between two buttons, and a wide window gives
    those two gaps _DIVIDER_SHARE shares of its spare width.  The two sides differ by the
    odd pixel of the rounding remainder at most."""
    narrow, wide = _laid_out(0), _laid_out(400)
    tight, slack = _gaps(narrow), _gaps(wide)
    narrow.close(); wide.close()
    assert tight["button"] == _GAP
    assert tight["divider"] == (_GAP + _DIVIDER_PAD,) * 2
    share = slack["button"] - _GAP
    left, right = slack["divider"]
    assert share > 0 and abs(left - right) <= 1
    assert min(left, right) - _GAP - _DIVIDER_PAD >= _DIVIDER_SHARE * share


def test_the_spare_width_fills_every_gap():
    """A window wider than the bar needs gives every gap the same share, inside the mode
    page too, so Reset ends under Help instead of leaving the spare width at the right."""
    wide = _laid_out(400)
    g = _gaps(wide)
    reset_end, help_end = _span(wide.reset, wide)[1], _span(wide.help, wide)[1]
    wide.close()
    assert g["button"] > _GAP and g["mode"] == g["page"] == g["button"]
    assert reset_end == help_end


def test_the_other_mode_pages_fill_their_gaps_too():
    """The structure page and the wideband page take the same share per gap.  Segments
    and Center tap share one gap, since only one of them is shown."""
    wide = _laid_out(400)
    gap = _gaps(wide)["button"]
    wide.set_ports(2)
    wide.mode.setCurrentIndex(wide.mode.findData("structure"))
    wide.structure.setCurrentIndex(wide.structure.findData("inductor-pi"))
    _pump(wide)
    assert gap > _GAP
    assert _gap(wide, wide.f_ext, wide.opt_box) == gap
    for ports, key, box in ((2, "inductor-wideband", "segments_box"), (3, "inductor-ct", "ct_box")):
        wide.set_ports(ports)
        wide.structure.setCurrentIndex(wide.structure.findData(key))
        _pump(wide)
        shown = getattr(wide, box)
        assert _gap(wide, wide.basic, shown) == gap, key
        assert _gap(wide, shown, wide.peak_q) == gap, key
        assert _gap(wide, wide.peak_q, wide.measured) == gap, key
    wide.close()


def test_a_wide_window_shrinks_back():
    """The fillers' minimum is 0 at any width, so widening the window never raises the
    width it can shrink back to, and back at that width every gap is _GAP again."""
    t = _laid_out(0)
    floor = t.minimumSizeHint().width()
    t.resize(floor + 400, t.height()); _pump(t)
    assert t.minimumSizeHint().width() == floor
    t.resize(floor, t.height()); _pump(t)
    g = _gaps(t)
    t.close()
    assert g["button"] == g["mode"] == g["page"] == _GAP


def test_no_other_row_sets_the_window_floor(bar):
    """The control strip is the widest row in the window, so it is what the window's
    width is for.  The plot view's own control row used to be wider (1767 px against
    1710) and the difference showed up as dead space at the right of this bar, since
    nothing there could shrink."""
    from snp2le.gui.plot_view import PlotView
    plots = PlotView()
    try:
        assert plots.minimumSizeHint().width() <= bar.minimumSizeHint().width()
    finally:
        plots.close()
        plots.deleteLater()


def test_the_dc_pin_box_takes_no_width_or_height(bar):
    """It sits on the fit range's caption line, in width the two fields already take, since
    the bar has none to spare at its narrowest (a maximized window on a 1920 px screen), and at the
    caption's own height, so the fields stay in line with every other field in the strip."""
    fields = bar.f_min.parentWidget()
    assert bar.band_box.sizeHint().width() == fields.sizeHint().width()
    row = bar.layout().itemAt(1).widget()

    def top(w):
        return w.mapTo(row, QtCore.QPoint(0, 0)).y()
    assert top(bar.f_min) == top(bar.order) == top(bar.p_ceiling)


def test_the_max_order_box_holds_two_digits(bar):
    """Max order and Stages both show up to two digits.  At 66 px the order box left its
    text 19 px and Windows drew "13" as "1" and a sliver, while the 70 px Stages box shows
    "10" whole, so the order box gets at least the same room."""
    assert bar.order.maximumWidth() >= bar.stages.maximumWidth()
    assert bar.order.lineEdit().width() >= 23


def test_the_tick_box_labels_stay_wrapped(bar):
    """Unwrapping any one costs about 45 px of bar width, which is the whole point
    of the shape.  Compare against the same text on one line rather than a pixel
    constant, so the check holds at any font size or DPI."""
    for cb in (bar.passive, bar.thermal_noise, bar.sim_output):
        assert "\n" in cb.text()
        one_line = QtWidgets.QCheckBox(cb.text().replace("\n", " "))
        assert cb.sizeHint().width() < one_line.sizeHint().width()


def test_the_run_status_uses_the_caption_slot(bar):
    """It sits above the tick box, in the slot the field captions use, and its styling
    may set colour and weight but never a font size: a bigger caption would push its
    tick box out of line with the other one."""
    assert bar.sim_status.property("class") == "fieldLabel"
    for setter in (lambda: bar.set_sim_status("successful!", True),
                   lambda: bar.set_sim_status("failed!", False),
                   lambda: bar.set_sim_progress("running...")):
        setter()
        assert "font-size" not in bar.sim_status.styleSheet()
        row = bar.layout().itemAt(1).widget()
        bar.layout().activate()
        assert _indicator_y(bar.passive, row) == _indicator_y(bar.sim_output, row)
    bar.clear_sim_status()


def test_the_title_bar_has_no_logo(bar):
    """The window manager draws the window icon in its own title bar right above this one,
    so a logo here showed it twice. The title starts where Load starts in the strip below."""
    titlebar = bar.layout().itemAt(0).widget()
    assert all(lab.pixmap().isNull() for lab in titlebar.findChildren(QtWidgets.QLabel))

    def left(w):
        return w.mapTo(bar, QtCore.QPoint(0, 0)).x()
    assert left(bar.title) == left(bar.load)
