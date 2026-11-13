# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_gui_export_menu.py - the Export menu and the Xyce netlist tab, headless.

One Export button opens a menu with one entry per dialect, since three buttons do not fit
the top bar.  These tests drive the real MainWindow offscreen (QT_QPA_PLATFORM=offscreen).
Run with: pytest -q
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from snp2le.core import netlist                       # noqa: E402
from snp2le.gui.main_window import MainWindow         # noqa: E402

_BPF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "snp2le", "examples", "bpf_ihp-sg13g2.s2p")


@pytest.fixture(scope="module")
def win():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow(_BPF)
    _settle(w)
    yield w
    w.close()
    app.processEvents()


def _settle(win, timeout=60.0):
    app = QtWidgets.QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if not win._fit.busy() and not win._timer.isActive():
            app.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("the conversion never finished")


def test_the_menu_offers_every_dialect(win):
    menu = win.top.export.menu()
    assert menu is win.top.export_menu
    assert [a.text() for a in menu.actions()] == ["Ngspice (.spice)", "VACASK (.inc)",
                                                  "Xyce (.cir)"]
    assert list(win.top.export_actions) == list(netlist.DIALECTS)


@pytest.mark.parametrize("dialect", netlist.DIALECTS)
def test_each_entry_writes_its_dialect(win, dialect, tmp_path, monkeypatch):
    ext = netlist.EXTENSION[dialect]
    asked = []

    def save(parent, caption, path, filters):
        asked.append((path, filters))
        return str(tmp_path / f"my_model.{ext}"), filters

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", save)
    win.top.export_actions[dialect].trigger()
    assert asked and asked[0][0].endswith(f"bpf_ihp-sg13g2_le.{ext}")
    assert f"*.{ext}" in asked[0][1]
    text = (tmp_path / f"my_model.{ext}").read_text(encoding="utf-8")
    assert text == netlist.render(win._res.ir, dialect)
    assert win._res.ir.name == "my_model"


def test_the_xyce_tab_shows_the_xyce_netlist(win):
    tabs = win.design.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Ngspice (SPICE)", "VACASK (Spectre)", "Xyce (SPICE)"]
    text = win.design.xyce_edit.toPlainText()
    assert text == win._res.xyce and text.startswith("* ") and "noisy" not in text


def test_greyed_export_opens_no_menu(win):
    win._set_exports_enabled(False)
    try:
        assert not win.top.export.isEnabled()
    finally:
        win._set_exports_enabled(True)
    assert win.top.export.isEnabled()
