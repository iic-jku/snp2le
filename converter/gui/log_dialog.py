"""log_dialog.py - a non-modal window that shows (and live-tails) a simulator log.

Used for VACASK's "Show output": xschem launches VACASK detached and then quits, so
its console never reaches a terminal.  The run redirects it to a log file, which this
window displays and refreshes while the simulation runs.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtGui


class LogWindow(QtWidgets.QDialog):
    def __init__(self, parent=None, title="Simulator output"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 480)
        self.setModal(False)                          # keep the main window usable
        lay = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(self.text, 1)
        btn = QtWidgets.QPushButton("Close")
        btn.setObjectName("primary")
        btn.clicked.connect(self.close)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        lay.addLayout(row)

    def set_text(self, s: str):
        """Replace the contents, keeping the view pinned to the bottom if it already was
        (so a live tail scrolls, but a user who scrolled up to read stays put)."""
        sb = self.text.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        if s != self.text.toPlainText():
            self.text.setPlainText(s)
        if at_bottom:
            sb.setValue(sb.maximum())
