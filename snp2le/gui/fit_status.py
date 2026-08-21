# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""fit_status.py - the conversion progress strip under the control row.

One slim always-present row: what the fit is doing on the left, elapsed time,
time left, and a determinate progress bar on the right.  When the fit ends the
bar goes and the message becomes the outcome, green or red, and it stays there
until the next fit starts.  That standing line is the completion notice: nothing
has to be watched while a fit runs, and nothing has to be clicked to learn how
it went.

The strip never changes height and never re-lays-out, so a fit that finishes in
80 ms cannot make the window flicker:

- every widget keeps its space when hidden (`setRetainSizeWhenHidden`)
- the bar only appears once the fit has run past `_BAR_DELAY_S`, which is the
  point where a user starts wondering whether anything is happening
- the numeric fields are fixed-width, so a jump from '9.9 s' to '10.0 s' does
  not shift the text next to it
"""
from __future__ import annotations
from PySide6 import QtCore, QtWidgets

from snp2le.core.progress import format_duration
from .style import JKU_GRAY, STATUS_GREEN, STATUS_RED

# A fit shorter than this never shows a bar: it is done before the eye resolves it.
_BAR_DELAY_S = 0.35


def _retain(widget):
    """Keep `widget`'s space in the layout while it is hidden."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)
    return widget


class FitStatusBar(QtWidgets.QWidget):
    """Progress and outcome of the running conversion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fitbar")
        self.setFixedHeight(26)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        self.message = QtWidgets.QLabel("")
        self.message.setObjectName("fitMessage")

        self.elapsed = _retain(QtWidgets.QLabel(""))
        self.elapsed.setObjectName("fitTime")
        self.elapsed.setFixedWidth(58)
        self.elapsed.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.eta = _retain(QtWidgets.QLabel(""))
        self.eta.setObjectName("fitTime")
        self.eta.setFixedWidth(92)
        self.eta.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.bar = _retain(QtWidgets.QProgressBar())
        self.bar.setObjectName("fitProgress")
        self.bar.setRange(0, 1000)               # per-mille, so the bar creeps smoothly
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(190, 8)

        lay.addWidget(self.message)
        lay.addStretch(1)
        lay.addWidget(self.elapsed)
        lay.addWidget(self.eta)
        lay.addWidget(self.bar)
        self.clear()

    # ---- states ----------------------------------------------------------
    def clear(self):
        """Idle and silent: no fit has run, or the window was just reset."""
        self._set_message("", JKU_GRAY)
        self.bar.setValue(0)
        for w in (self.bar, self.elapsed, self.eta):
            w.setVisible(False)

    def start(self, message="starting"):
        """A fit has begun.  The bar itself waits for `_BAR_DELAY_S`."""
        self._set_message(message, JKU_GRAY)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        self.elapsed.setText("")
        self.elapsed.setVisible(True)
        self.eta.setText("")
        self.eta.setVisible(True)

    def update_progress(self, state):
        """Render one `ProgressState` sampled from the running fit."""
        if not state.running:
            return
        self._set_message(state.message or "converting", JKU_GRAY)
        self.bar.setValue(int(round(state.fraction * 1000)))
        self.elapsed.setText(format_duration(state.elapsed))
        self.eta.setText("" if state.eta != state.eta      # nan: not estimable yet
                         else f"~{format_duration(state.eta)} left")
        self.bar.setVisible(state.elapsed >= _BAR_DELAY_S)

    def finish(self, ok, message, elapsed=None):
        """Show the outcome and leave it standing until the next fit."""
        text = message or ("conversion complete" if ok else "conversion failed")
        if elapsed is not None:
            text = f"{text}  ({format_duration(elapsed)})"
        self._set_message(text, STATUS_GREEN if ok else STATUS_RED)
        for w in (self.bar, self.elapsed, self.eta):
            w.setVisible(False)

    # ---- internals -------------------------------------------------------
    def _set_message(self, text, color):
        self.message.setText(text)
        self.message.setStyleSheet(f"color:{color}; font-size:11px; font-weight:600;")
        self.message.setToolTip(text)
