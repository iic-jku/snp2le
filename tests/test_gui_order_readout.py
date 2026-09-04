# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_order_readout.py - the Result panel's order line, headless.

The line used to read "order  7 poles" under a top bar set to "Max order 6", which reads
as the cap being exceeded and was reported as a bug (iic-jku/snp2le issue 7).  The two
numbers are in different units: Max order counts n_real + 2 x n_complex, the pole count
counts a conjugate pair once.  The panel now leads with the order, so the comparison a
reader makes is between like quantities.
Run with: pytest -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core import engine                                 # noqa: E402
from snp2le.core.state import ConverterState                   # noqa: E402
from snp2le.gui.design_view import DesignView                  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_core import inductor_2port                           # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_order_line_leads_with_the_order(app):
    view = DesignView()
    res = engine.convert(ConverterState(mode="universal", max_order=6), inductor_2port())
    view.update_results(res)
    assert view.order_out.label.text() == "order"
    assert view.order_out.value.text() == f"{res.model_order} ({res.n_poles} poles)"
    # the number the eye compares against Max order is the one that respects it
    assert res.model_order <= 6


def test_structure_mode_keeps_the_extraction_frequency(app):
    """The same field carries f_ext in structure mode, so the label and the tooltip
    have to move with it rather than being set once at build time."""
    view = DesignView()
    res = engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"),
                         inductor_2port())
    view.update_results(res)
    assert view.order_out.label.text() == "ext. frequency"
    assert "poles" not in view.order_out.value.text()
    assert "extracted at" in view.order_out.toolTip()
