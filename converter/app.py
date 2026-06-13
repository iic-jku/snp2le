#!/usr/bin/env python3
"""app.py - launch the snp2le GUI."""
from __future__ import annotations
import sys
from PySide6 import QtWidgets

from gui.style import build_stylesheet
from gui.mpl_style import apply_style
from gui.logo import logo_icon
from gui.main_window import MainWindow


def main():
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
