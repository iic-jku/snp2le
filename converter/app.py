#!/usr/bin/env python3
"""app.py - launch the snp2le GUI."""
from __future__ import annotations
import sys
from PySide6 import QtWidgets

from gui.style import build_stylesheet
from gui.mpl_style import apply_style
from gui.logo import logo_icon
from gui.main_window import MainWindow


def _set_windows_app_id():
    """Show our own taskbar icon on Windows instead of the Python logo.

    Windows groups taskbar buttons by an "Application User Model ID". When the
    GUI is launched via python.exe the process inherits Python's AppID, so the
    taskbar shows the Python icon even though the window icon is ours. Setting an
    explicit AppID detaches us from the interpreter and lets the window icon
    through. Must run before the QApplication is created; purely cosmetic, so a
    failure (e.g. non-Windows) is never fatal.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "JKU.IICQC.snp2le")
    except Exception:                                     # noqa: BLE001
        pass


def main():
    _set_windows_app_id()
    apply_style()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("snp2le")
    app.setWindowIcon(logo_icon())
    app.setStyleSheet(build_stylesheet())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
