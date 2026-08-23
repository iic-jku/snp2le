# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""fit_status.py - the conversion progress indicator.

One compact widget: what the fit is doing on the left, how long it has been
running on the right, and a bar under (or beside) them tracking it.  When the
fit ends the line becomes the outcome and the bar stays where it stopped, full
on a completed conversion.  Green throughout on success, red on failure, and it
stands there until the next fit starts: that is the completion notice, so
nothing has to be watched while a fit runs and nothing has to be clicked to
learn how it went.

It lives inside panels that already exist rather than in a bar of its own: in
the Design view under the loaded-file line, where the RMS error and pole count
it summarises sit a few rows below, and in the Plot view's header row next to
the passivity and order figures mirrored from that same panel.  Both hosts had
the room, so the indicator costs no window height.

Two things it deliberately does not show:

- **No estimated time left.**  The fraction is not linear in time and cannot be:
  the fit stage reports a saturating curve because `auto_fit`'s iteration count
  is not knowable in advance.  A remaining-time figure derived from it would be
  a number the code cannot stand behind.
- **No result summary on completion.**  The line is the verdict and the clock,
  because the pole count and RMS error are already on screen in the panel below.

Nothing here is ever hidden once a conversion has started, which is what keeps a
run of fast fits calm: dragging a spin box moves the bar's value and rewrites two
labels, where showing and hiding them would strobe.  The widget also never
changes height, so a fit that finishes in 80 ms cannot make the panel jump.
"""
from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets

from snp2le.core.progress import format_duration
from .style import JKU_GRAY, STATUS_GREEN, STATUS_RED

# Compact mode sits in the Plot view's header row, which already carries a title,
# four selectors, a legend, three figures and three buttons.  Every part of it is
# therefore a fixed width and the message elides into its own: a label that grew
# with its text would push the buttons sideways on every report, and off the edge
# of a laptop screen entirely.
#
# That width comes from Qt's own metrics for the line that must always be legible,
# not from a pixel count, so it holds on any platform font and DPI.  Longer
# running messages elide, and the tooltip carries the full text.
_COMPACT_FITS = "conversion complete"
_COMPACT_BAR = (78, 6)


def _retain(widget):
    """Keep `widget`'s space in the layout while it is hidden."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)
    return widget


class FitProgress(QtWidgets.QWidget):
    """Progress and outcome of the running conversion.

    `compact` picks the layout for the host.  A panel column gets the message and
    the clock on one line with a full-width bar under it.  A header row that is
    already full of controls gets all three on one line with a short bar.
    """

    def __init__(self, compact=False, parent=None):
        super().__init__(parent)
        self._compact = compact
        self.message = QtWidgets.QLabel("")
        self.message.setObjectName("fitMessage")
        self.elapsed = _retain(QtWidgets.QLabel(""))
        self.elapsed.setObjectName("fitTime")
        self.elapsed.setFixedWidth(44 if compact else 52)
        self.elapsed.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.bar = _retain(QtWidgets.QProgressBar())
        self.bar.setObjectName("fitProgress")
        self.bar.setRange(0, 1000)               # per-mille, so the bar creeps smoothly
        self.bar.setValue(0)
        self.bar.setTextVisible(False)

        if compact:
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
            self.message.setFixedWidth(
                self.message.fontMetrics().horizontalAdvance(_COMPACT_FITS) + 6)
            self.bar.setFixedSize(*_COMPACT_BAR)
            lay.addWidget(self.message)
            lay.addWidget(self.elapsed)
            lay.addWidget(self.bar)
        else:
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(3)
            self.bar.setFixedHeight(4)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
            row.addWidget(self.message); row.addStretch(1); row.addWidget(self.elapsed)
            lay.addLayout(row)
            lay.addWidget(self.bar)
        self.clear()

    # ---- states ----------------------------------------------------------
    def clear(self):
        """Idle and silent: no fit has run yet, or the window was just reset."""
        self._set_message("", JKU_GRAY)
        self._set_elapsed("", JKU_GRAY)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        self.elapsed.setVisible(False)

    def start(self, message="starting"):
        """A fit has begun.  Everything stays on screen from here on."""
        self._set_message(message, JKU_GRAY)
        self._set_elapsed("", JKU_GRAY)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.elapsed.setVisible(True)

    def update_progress(self, state):
        """Render one `ProgressState` sampled from the running fit."""
        if not state.running:
            return
        self._set_message(state.message or "converting", JKU_GRAY)
        self._set_elapsed(format_duration(state.elapsed), JKU_GRAY)
        self.bar.setValue(int(round(state.fraction * 1000)))

    def finish(self, ok, message, elapsed=None):
        """Show the outcome and leave it standing until the next fit.

        A completed conversion fills the bar; a failed one leaves it where it
        stopped, which is the honest picture of how far the attempt got.  The
        clock keeps the total either way, in the outcome's colour.
        """
        colour = STATUS_GREEN if ok else STATUS_RED
        self._set_message(message or ("conversion complete" if ok
                                      else "conversion failed"), colour)
        self._set_elapsed("" if elapsed is None else format_duration(elapsed), colour)
        if ok:
            self.bar.setValue(self.bar.maximum())
        self.bar.setVisible(True)
        self.elapsed.setVisible(elapsed is not None)

    # ---- internals -------------------------------------------------------
    def _set_message(self, text, color):
        self.message.setStyleSheet(f"color:{color}; font-size:11px; font-weight:600;")
        self.message.setToolTip(text)            # the full text, before any eliding
        if self._compact:                        # fixed width, so elide rather than clip
            text = QtGui.QFontMetrics(self.message.font()).elidedText(
                text, QtCore.Qt.ElideRight, self.message.width())
        self.message.setText(text)

    def _set_elapsed(self, text, color):
        self.elapsed.setStyleSheet(f"color:{color}; font-size:11px; font-weight:600;")
        self.elapsed.setText(text)
