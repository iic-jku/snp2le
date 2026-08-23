# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_fit_range.py - the Fit range (GHz) control, headless.

The fields hold the band the model is fitted to, in GHz, and are seeded from the loaded
file so they are never empty: what is on screen is what the fit sees.  Whatever they hold
must reach ConverterState.  These tests drive the real MainWindow offscreen
(QT_QPA_PLATFORM=offscreen), so they run in CI without a display.  Run with: pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
import skrf

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core.state import ConverterState            # noqa: E402
from snp2le.gui.main_window import MainWindow           # noqa: E402


_TIMEOUT = 60.0                     # generous: a fit on a slow CI box is still a fit


def _settle(window, timeout=_TIMEOUT):
    """Pump the event loop until no conversion is running.

    Conversions run on a worker thread (see gui/fit_runner.py), so `_res` only holds
    this call's result once the finished handler has run.  Same helper as the one in
    test_gui_fit_progress.py."""
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
def win():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    _settle(w)
    yield w
    w.close()
    app.processEvents()


@pytest.fixture()
def top(win):
    """The top bar with the bundled example loaded, restored after every test."""
    win.on_reset()
    _settle(win)
    yield win.top
    win.on_reset()
    _settle(win)


def _enter(top, f_min=None, f_max=None):
    if f_min is not None:
        top.f_min.setText(f_min)
    if f_max is not None:
        top.f_max.setText(f_max)
    top.f_min.editingFinished.emit()


def test_the_fields_start_at_the_loaded_file_s_own_span(win, top):
    """Fresh window: the band on screen is the file's full range, which is what the fit
    uses, so nothing is hidden behind an empty field."""
    assert (top.f_min.text(), top.f_max.text()) == ("120", "200")
    assert top.values()["f_min"] == float(win.net.f[0])
    assert top.values()["f_max"] == float(win.net.f[-1])
    assert not win._res.band_limited                   # the full file, as before
    assert len(win._res.freq) == len(win.net.f)


def test_a_plain_number_is_read_as_ghz(win, top):
    _enter(top, "140", "170")
    win._pull()
    assert (win.state.f_min, win.state.f_max) == (140e9, 170e9)
    win.recompute()
    _settle(win)
    assert win._res.band_limited
    assert win._res.freq[0] == 140e9 and win._res.freq[-1] == 170e9


def test_a_typed_unit_or_decimal_comma_is_accepted(top):
    """The unit is in the label, but typing it anyway must not be an error, and a decimal
    comma reads like a decimal point (as in the passivity-ceiling field)."""
    for entry, want in (("150 GHz", 150e9), ("150GHz", 150e9), ("155g", 155e9),
                        ("142,5", 142.5e9), ("142.5", 142.5e9)):
        _enter(top, entry)
        assert top.values()["f_min"] == want, entry
        assert top.f_min.text() == f"{want / 1e9:g}", entry     # normalised on the way in


def test_text_that_is_not_a_number_keeps_the_last_good_value(top):
    _enter(top, "140")
    _enter(top, "banana")
    assert top.values()["f_min"] == 140e9
    assert top.f_min.property("error")


def test_clearing_a_field_leaves_that_side_open(win, top):
    _enter(top, "")
    win._pull()
    assert win.state.f_min is None
    win.recompute()
    _settle(win)
    assert win._res.freq[0] == win.net.f[0]            # follows the data again


def test_loading_another_file_seeds_that_file_s_span(win, top, tmp_path):
    """A band from the previous file would not even overlap the new one, so the fields
    follow the file rather than the other way round."""
    _enter(top, "140", "170")
    stem = str(tmp_path / "low")
    f = skrf.Frequency(1, 20, 40, "ghz")
    skrf.Network(frequency=f, s=0.1 * np.ones((40, 2, 2)), z0=50).write_touchstone(
        stem, form="ri")
    from snp2le.core import io
    win.net = io.load_touchstone(stem + ".s2p")
    win._seed_band()
    win.recompute()
    _settle(win)
    assert (top.f_min.text(), top.f_max.text()) == ("1", "20")
    assert win._res.ok and not win._res.band_limited


def test_a_design_s_band_survives_a_load(win, top):
    """An explicit band in a design file wins, and a design that carries none is filled
    from the loaded file rather than left empty."""
    win.state = ConverterState.from_json('{"mode": "universal", "f_min": 1.4e11}')
    top.set_values(win.state)
    win._seed_band(keep=True)
    assert (top.f_min.text(), top.f_max.text()) == ("140", "200")
    assert top.values()["f_min"] == 1.4e11

    win.state = ConverterState.from_json('{"mode": "universal"}')
    top.set_values(win.state)
    win._seed_band(keep=True)
    assert (top.f_min.text(), top.f_max.text()) == ("120", "200")


def test_the_displayed_rounding_never_crops_the_fit(win, top):
    """The field shows a rounded GHz number while the stored value keeps the file's own
    edge, so a file whose first sample is not a round GHz keeps every point."""
    f = skrf.Frequency(0.10000001, 19.99999987, 33, "ghz")
    win.net = skrf.Network(frequency=f, s=0.1 * np.ones((33, 2, 2)), z0=50)
    win._seed_band()
    win.recompute()
    _settle(win)
    assert top.f_min.text() == "0.1" and top.f_max.text() == "20"
    assert top.values()["f_min"] == float(win.net.f[0])
    assert len(win._res.freq) == 33 and not win._res.band_limited

    _enter(top, None, "15")                            # edit only the stop field
    win._pull()
    win.recompute()
    _settle(win)
    assert win.state.f_min == float(win.net.f[0])      # the untouched side stays exact
    assert win._res.freq[0] == win.net.f[0]
