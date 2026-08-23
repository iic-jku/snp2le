# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_top_bar_layout.py - the two tick boxes in the control strip, headless.

'Enforce passivity' and 'Show output' are built the same way (a caption slot, then a
two-line box) for two reasons: wrapped text keeps the bar narrow, and the identical shape
is what puts the two indicators on the same line.  Both are easy to break by editing one
of them alone, and neither shows up in any functional test, so they are pinned here.
Run with: pytest -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.gui.style import build_stylesheet                  # noqa: E402
from snp2le.gui.top_bar import TopBar                          # noqa: E402


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


def test_the_two_tick_boxes_share_a_line(bar):
    row = bar.layout().itemAt(1).widget()
    passive_y, passive_h = _indicator_y(bar.passive, row)
    output_y, output_h = _indicator_y(bar.sim_output, row)
    assert (passive_y, passive_h) == (output_y, output_h)


def test_both_tick_box_labels_stay_wrapped(bar):
    """Unwrapping either one costs about 45 px of bar width, which is the whole point
    of the shape.  Compare against the same text on one line rather than a pixel
    constant, so the check holds at any font size or DPI."""
    for cb in (bar.passive, bar.sim_output):
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
