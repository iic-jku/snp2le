# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_plot_view.py - the Plot view's trace selectors, headless.

Each selector carries an S-parameter as its (i, j) index pair in the item data, and Qt keeps item data in a QVariant.
PySide6 6.10.1 converts a tuple stored there to a QVariantList and hands it back as a list, so a check for `tuple` alone drew no curve in any panel while the fit itself was fine (iic-jku/snp2le PR 8).
These tests pin that every S-parameter panel gets its data and model curve, whichever type the installed PySide6 hands back, and on a binding that returns lists whatever the installed one does.
Run with: pytest -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core import engine                                 # noqa: E402
from snp2le.core.state import ConverterState                   # noqa: E402
from snp2le.gui.plot_view import DATA, MODEL, SIDES, PlotView  # noqa: E402
from snp2le.gui.widgets import FitComboBox                     # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_core import inductor_2port                           # noqa: E402

CURVES = [DATA[0], MODEL[0]]            # what an S-parameter panel draws, in z-order


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(scope="module")
def universal():
    return engine.convert(ConverterState(mode="universal", max_order=6), inductor_2port())


@pytest.fixture(scope="module")
def pi_model():
    return engine.convert(ConverterState(mode="structure", structure_key="inductor-pi"),
                          inductor_2port())


def _curves(panel):
    """Labels of the curves in a panel. The unlabelled f_ext dot is left out."""
    return [ln.get_label() for ln in panel.ax.lines if not ln.get_label().startswith("_")]


def _view(res):
    view = PlotView()
    view.update_results(res)
    return view


def test_item_data_comes_back_as_the_index_pair(app, universal):
    """A tuple on most releases, a list on 6.10.1, never anything else."""
    view = _view(universal)
    for combo in view.selectors:
        sel = combo.currentData()
        assert isinstance(sel, (tuple, list)), type(sel)
        i, j = (int(c) - 1 for c in combo.currentText()[1:])
        assert list(sel) == [i, j]


def test_every_s_parameter_panel_draws_data_and_model(app, universal):
    view = _view(universal)
    assert [c.currentText() for c in view.selectors] == ["S11", "S21", "S12", "S22"]
    for side, combo in zip(SIDES, view.selectors):
        sub = combo.currentText()[1:]
        for kind in ("mag", "ph"):
            panel = view._panels[kind + side]
            assert _curves(panel) == CURVES, (side, kind)
            assert sub in panel.ax.get_ylabel()
            for ln in panel.ax.lines:
                y = ln.get_ydata()
                assert len(y) == len(universal.freq) and np.all(np.isfinite(y))


def test_switching_a_selector_redraws_its_column(app, universal):
    view = _view(universal)
    combo = view.selectors[0]
    combo.setCurrentIndex(combo.findText("S22"))
    for kind in ("mag", "ph"):
        panel = view._panels[kind + "A"]
        assert _curves(panel) == CURVES
        assert "22" in panel.ax.get_ylabel()


@pytest.mark.parametrize("container", [tuple, list])
def test_render_takes_the_pair_as_tuple_or_as_list(app, universal, monkeypatch, container):
    """Both shapes of the round trip, whatever the installed binding does."""
    orig = QtWidgets.QComboBox.currentData

    def current_data(self):
        sel = orig(self)
        return container(sel) if isinstance(sel, (tuple, list)) else sel

    monkeypatch.setattr(FitComboBox, "currentData", current_data)
    view = _view(universal)
    for side in SIDES:
        for kind in ("mag", "ph"):
            assert _curves(view._panels[kind + side]) == CURVES, (container, side, kind)


def test_extra_traces_and_s_parameters_are_told_apart(app, pi_model):
    """A string selects an extra trace, an index pair an S-parameter."""
    view = _view(pi_model)
    extra = pi_model.aux_traces
    assert extra
    last = view.selectors[-1]
    last.setCurrentIndex(last.findText("S21"))          # one of each kind on screen
    labels = [c.currentText() for c in view.selectors]
    assert labels[0] in extra and labels[-1] == "S21"
    for side, label in zip(SIDES, labels):
        top, bottom = view._panels["mag" + side], view._panels["ph" + side]
        if label in extra:
            assert top.head.text() == extra[label]["top"]["title"]
            assert _curves(top)[0] == DATA[0] and _curves(bottom)[0] == DATA[0]
        else:
            assert _curves(top) == CURVES and _curves(bottom) == CURVES
            assert label[1:] in top.ax.get_ylabel()
