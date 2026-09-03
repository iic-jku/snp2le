# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_view_switch.py - the title bar's two-segment View switch, headless.

The switch replaced a drop-down, and the whole point of the shape is that both views
are on screen before anything is clicked: as a drop-down the Plot view only existed
once the popup was opened.  That is a layout property, so no functional test would
notice it going away, and it is pinned here together with the invariants that keep the
segments on the title bar's line and keep the window following the switch.
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
from snp2le.gui.top_bar import TopBar                          # noqa: E402

VIEWS = {"design": "Design & Schematic", "plot": "Plot"}


@pytest.fixture
def bar():
    """A laid-out TopBar with the app stylesheet applied, one per test.

    Function scope on purpose: half of these tests move the switch, and a shared
    instance would hand the next test whatever the last one left selected."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyleSheet(build_stylesheet())
    t = TopBar()
    t.resize(1500, t.sizeHint().height())
    t.show()
    app.processEvents()
    yield t
    t.close()
    app.processEvents()


def _titlebar(bar):
    return bar.layout().itemAt(0).widget()


def _rect(w, ref):
    """Top edge and height of `w` in `ref` coordinates."""
    return w.mapTo(ref, QtCore.QPoint(0, 0)).y(), w.height()


def test_both_views_are_on_screen_unopened(bar):
    """The reason for the shape.  Each view is a visible button carrying its own name,
    with nothing to open first, and the title bar holds no drop-down that could be
    hiding one of them."""
    row = _titlebar(bar)
    for key, label in VIEWS.items():
        b = bar.view.button(key)
        assert b.isVisibleTo(row)
        # '&' in a button label marks a mnemonic and is eaten unless it is doubled
        assert b.text().replace("&&", "&") == label
    assert not row.findChildren(QtWidgets.QComboBox)


def test_exactly_one_segment_is_selected(bar):
    """Design on opening, and the pair is exclusive, so the switch always says which
    view the window is on."""
    assert bar.view.current() == "design"
    for key in VIEWS:
        bar.view.set_current(key)
        checked = [k for k in VIEWS if bar.view.button(k).isChecked()]
        assert checked == [key]


def test_clicking_the_selected_segment_keeps_it(bar):
    """A second click on the current view must not leave the switch with nothing
    selected, which is what an ordinary pair of checkable buttons would do."""
    bar.view.button("design").click()
    assert bar.view.current() == "design"
    assert bar.view.button("design").isChecked()


def test_a_click_reports_the_view_once(bar):
    """One `view_changed` per change, carrying the key the window switches on.  A
    change toggles two buttons, so the segment going off must stay quiet."""
    seen = []
    bar.view_changed.connect(seen.append)
    bar.view.button("plot").click()
    assert seen == ["plot"]
    bar.view.button("design").click()
    assert seen == ["plot", "design"]


def test_set_view_reports_only_a_real_change(bar):
    """`set_view` is how the pop-out, dock and reset paths move the window, so it has
    to emit like a click does.  Re-selecting the current view changes nothing and must
    stay silent, or docking the plots would switch the window twice."""
    seen = []
    bar.view_changed.connect(seen.append)
    bar.set_view("design")               # already there
    assert seen == []
    bar.set_view("plot")
    bar.set_view("plot")
    assert seen == ["plot"]


def test_the_segments_sit_on_the_help_line(bar):
    """Same line and same height as the Help chip beside them, which is what the shared
    padding and border in the stylesheet are for."""
    row = _titlebar(bar)
    help_rect = _rect(bar.help, row)
    for key in VIEWS:
        assert _rect(bar.view.button(key), row) == help_rect


def test_selecting_a_view_does_not_move_the_row(bar):
    """The selected segment differs from the others in fill and text colour only.  A
    heavier font or extra padding on the selection would resize it, and the title bar
    would shuffle on every switch."""
    row = _titlebar(bar)
    before = {k: bar.view.button(k).width() for k in VIEWS}
    bar.set_view("plot")
    bar.layout().activate()
    assert {k: bar.view.button(k).width() for k in VIEWS} == before
    assert _rect(bar.view.button("plot"), row) == _rect(bar.help, row)


def test_the_title_bar_does_not_set_the_window_floor(bar):
    """The control strip is what the window's width is for.  The switch is wider than
    the drop-down it replaced (it shows both labels at once), so the title bar has to
    be checked against the row that actually binds."""
    assert (_titlebar(bar).minimumSizeHint().width()
            <= bar.layout().itemAt(1).widget().minimumSizeHint().width())
