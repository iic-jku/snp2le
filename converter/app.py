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
    through. Must run before the QApplication is created. It is purely cosmetic, so a
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


def _install_message_filter():
    """Hide one benign Qt warning, passing every other message through.

    On some Windows setups Qt prints "QFont::setPointSize: Point size <= 0 (-1)"
    once at startup. It is a side effect of the stylesheet defining fonts in
    pixels (so QFont.pointSize() is -1) being read back by a widget during the
    first paint. Qt keeps the current size, so it is only console noise. We drop
    just that line so genuine warnings stay visible.
    """
    from PySide6 import QtCore
    _default = [None]

    def _filter(mode, ctx, msg):
        if "setPointSize" in msg:
            return
        if _default[0] is not None:
            _default[0](mode, ctx, msg)
        else:
            sys.stderr.write(msg + "\n")

    _default[0] = QtCore.qInstallMessageHandler(_filter)


def main():
    _set_windows_app_id()
    _install_message_filter()
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
