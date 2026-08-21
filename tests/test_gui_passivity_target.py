# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_passivity_target.py - the passivity-target control, headless.

The field holds the sigma_max the enforcement works towards, so it is editable while
'Enforce passivity' is ticked and greyed at the strict default once it is unticked,
where nothing aims at it.  Whatever it holds must reach ConverterState so the fit is
actually enforced against it.  These tests drive the real MainWindow offscreen
(QT_QPA_PLATFORM=offscreen), so they run in CI without a display.  Run with: pytest -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core import universal                        # noqa: E402
from snp2le.core.state import ConverterState, Results    # noqa: E402
from snp2le.gui.main_window import MainWindow            # noqa: E402
from snp2le.gui.widgets import passivity_text, sigma_text  # noqa: E402


def test_passivity_text_follows_the_measurement_not_the_target():
    """The verdict must come from the measured sigma_max.  Reading it off the target
    alone would report a strictly passive model as merely 'within target' whenever the
    target happens to be raised, which understates it.  Pure functions, no window."""
    strict = Results(ok=True, passive=True, sigma_max=0.98, passivity_target=1.2)
    assert passivity_text(strict) == "passive ✓"          # passive, despite the target
    assert sigma_text(strict) == "0.980 / 1.20"

    relaxed = Results(ok=True, passive=True, sigma_max=1.05, passivity_target=1.2)
    assert passivity_text(relaxed) == "within target ✓"
    over = Results(ok=True, passive=False, sigma_max=1.30, passivity_target=1.2)
    assert passivity_text(over) == "not passive"
    near = Results(ok=True, passive=False, sigma_max=1.01, passivity_target=1.0,
                   messages=["passivity enforced (near-passive)"])
    assert passivity_text(near) == "near-passive"

    # a structure model measures no sigma_max and is passive by construction
    struct = Results(ok=True, passive=True)
    assert passivity_text(struct) == "passive ✓" and sigma_text(struct) == "—"
    # a failed conversion has no model to judge
    bad = Results(ok=False, error="boom")
    assert passivity_text(bad) == "—" and sigma_text(bad) == "—"


@pytest.fixture(scope="module")
def win():
    """One offscreen MainWindow for the whole module (Qt allows only one
    QApplication per process, and constructing the window is the slow part)."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    yield w
    w.close()
    app.processEvents()


@pytest.fixture()
def top(win):
    """The top bar, back at its defaults after every test."""
    win.top.reset_controls()
    yield win.top
    win.top.reset_controls()


def test_default_is_enforced_at_the_strict_target(top):
    """Fresh window: enforcement on, the target editable and sitting at 1.00, which is
    exactly what the tool did before the target existed."""
    assert top.passive.isChecked()
    assert top.p_target.isEnabled()
    assert top.p_target.text() == f"{universal.PASSIVITY_TARGET_DEFAULT:.2f}"
    assert top.values()["passivity_target"] == universal.PASSIVITY_TARGET_DEFAULT


def test_the_target_is_editable_while_enforcing(top):
    top.p_target.setText("1.15")
    top.p_target.editingFinished.emit()
    assert top.values()["passivity_target"] == 1.15


def test_unticking_greys_the_target_back_to_the_default(top):
    """With enforcement off nothing aims at the target, so the field greys out and
    returns to 1.00 rather than implying a relaxation that is not happening."""
    top.p_target.setText("1.15")
    top.p_target.editingFinished.emit()
    assert top.values()["passivity_target"] == 1.15
    top.passive.setChecked(False)
    assert not top.p_target.isEnabled()
    assert top.p_target.text() == f"{universal.PASSIVITY_TARGET_DEFAULT:.2f}"
    assert top.values()["passivity_target"] == universal.PASSIVITY_TARGET_DEFAULT


def test_out_of_range_input_shows_the_limit_it_overshot(top):
    """Too big leaves the maximum in the field and too small leaves the minimum, so the
    limits are discoverable without reading the tooltip.  Text that is not a number has
    no edge to clamp to and falls back to the strict default."""
    lo, hi = universal.PASSIVITY_TARGET_MIN, universal.PASSIVITY_TARGET_MAX
    cases = [("9.9", hi), ("1.5", hi), ("1.21", hi),
             ("0.5", lo), ("0.99", lo), ("-3", lo),
             ("abc", universal.PASSIVITY_TARGET_DEFAULT),
             ("", universal.PASSIVITY_TARGET_DEFAULT)]
    for entry, want in cases:
        top.passive.setChecked(True)
        top.p_target.setText("1.05")                      # a good value to move away from
        top.p_target.editingFinished.emit()
        assert top.values()["passivity_target"] == 1.05

        top.p_target.setText(entry)
        top.p_target.editingFinished.emit()
        assert top.p_target.text() == f"{want:.2f}", entry
        assert top.values()["passivity_target"] == want, entry


def test_the_range_edges_are_accepted(top):
    for edge in (universal.PASSIVITY_TARGET_MIN, universal.PASSIVITY_TARGET_MAX):
        top.p_target.setText(f"{edge:.2f}")
        top.p_target.editingFinished.emit()
        assert top.values()["passivity_target"] == edge


def test_a_decimal_comma_is_accepted(top):
    top.p_target.setText("1,10")
    top.p_target.editingFinished.emit()
    assert top.values()["passivity_target"] == 1.10
    assert top.p_target.text() == "1.10"                  # normalised on the way in


def test_the_target_reaches_the_state_and_is_enforced(win, top):
    """The value in the field is what the conversion is enforced against, and the Result
    panel shows the measured sigma_max against that same target."""
    top.p_target.setText("1.05")
    top.p_target.editingFinished.emit()
    win._pull()
    assert win.state.passivity_target == 1.05
    win.recompute()
    assert win.design.sigma_out.value.text() != "—"
    assert win.design.sigma_out.value.text().endswith("/ 1.05")


def test_set_values_restores_a_saved_target(top):
    """Loading a design saved with enforcement on restores its target, while one saved
    with enforcement off pins the field back to the strict default."""
    top.set_values(ConverterState(mode="universal", enforce_passivity=True,
                                  passivity_target=1.08))
    assert top.p_target.isEnabled() and top.values()["passivity_target"] == 1.08

    top.set_values(ConverterState(mode="universal", enforce_passivity=False,
                                  passivity_target=1.08))
    assert not top.p_target.isEnabled()
    assert top.values()["passivity_target"] == universal.PASSIVITY_TARGET_DEFAULT

    # a hand-edited design file cannot put an impossible target on screen either
    top.set_values(ConverterState(mode="universal", enforce_passivity=True,
                                  passivity_target=7.5))
    assert top.p_target.text() == f"{universal.PASSIVITY_TARGET_MAX:.2f}"
    assert top.values()["passivity_target"] == universal.PASSIVITY_TARGET_MAX
