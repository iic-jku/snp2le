# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""widgets.py - small reusable Qt widgets (math labels, entries, section title).

Ported from the filter designer so the two tools share look and behaviour.
"""
from __future__ import annotations
from PySide6 import QtCore, QtWidgets

from .style import JKU_BLUE

_GREEK = {"omega": "\u03c9", "Omega": "\u03a9", "Delta": "\u0394", "mu": "\u00b5",
          "pi": "\u03c0", "tau": "\u03c4", "alpha": "\u03b1", "beta": "\u03b2",
          "sigma": "\u03c3"}


def math_html(spec: str) -> str:
    base, _, sub = spec.partition("_")

    def fmt(tok, allow_italic):
        if tok in _GREEK:
            return _GREEK[tok]
        if allow_italic and len(tok) == 1 and tok.isalpha():
            return f"<i>{tok}</i>"
        return tok
    html = fmt(base, True)
    if sub:
        html += f"<sub>{fmt(sub, False)}</sub>"
    return html


class MathLabel(QtWidgets.QLabel):
    def __init__(self, spec: str, parent=None):
        super().__init__(parent)
        self.setText(math_html(spec))
        self.setTextFormat(QtCore.Qt.RichText)


class OutputField(QtWidgets.QWidget):
    def __init__(self, label_spec: str, value: str = "\u2014", label_w: int = 46,
                 equals: bool = True, field_w: int | None = 120, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.label = MathLabel(label_spec)
        if equals:
            self.label.setText(math_html(label_spec) + " =")
        self.label.setFixedWidth(label_w)
        self.label.setProperty("class", "varLabel")
        self.value = QtWidgets.QLineEdit(value); self.value.setReadOnly(True)
        lay.addWidget(self.label)
        if field_w:
            self.value.setFixedWidth(field_w); lay.addWidget(self.value)
        else:
            lay.addWidget(self.value, 1)

    def set_value(self, text: str):
        self.value.setText(text)


class FitComboBox(QtWidgets.QComboBox):
    """A QComboBox that is always exactly wide enough for a reference string.

    Width is derived at layout time from Qt's own size hint, so it adapts to the
    real font, DPI, style and stylesheet padding on any platform (no hard-coded
    pixel chrome, which is what made earlier fixed-width attempts clip on Linux).
    With AdjustToContents the base hint is `chrome + width(widest item)`, so
    adding `width(ref) - width(widest item)` yields `chrome + width(ref)`, the
    tightest width that still fits `ref`, constant across selections and items.
    """

    def __init__(self, ref, parent=None):
        super().__init__(parent)
        self._ref = ref
        self.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                           QtWidgets.QSizePolicy.Policy.Fixed)

    def _hint(self):
        base = super().sizeHint()                      # chrome + widest current item
        fm = self.fontMetrics()
        widest = max((fm.horizontalAdvance(self.itemText(i))
                      for i in range(self.count())), default=0)
        extra = fm.horizontalAdvance(self._ref) - widest
        return QtCore.QSize(base.width() + max(0, extra), base.height())

    def sizeHint(self):
        return self._hint()

    def minimumSizeHint(self):
        return self._hint()


class SegmentedSwitch(QtWidgets.QWidget):
    """A row of mutually exclusive buttons, one per destination.

    Used for the title bar's view switch, where a drop-down used to sit.  A
    drop-down keeps its other entries behind a popup and looks like the setting
    fields beside it, so nothing on the opening screen says a second view exists.
    Segments say it without being opened, and switching costs one click instead
    of a click, a popup and a second click.

    `changed` carries the selected key and fires on a programmatic `set_current`
    too, which is what the drop-down's `currentIndexChanged` did and what the
    plot pop-out and dock round trip relies on to move the window with it.
    """

    changed = QtCore.Signal(str)

    def __init__(self, items, parent=None):
        """`items` is (key, label, tooltip) per segment, left to right."""
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self._keys = [key for key, _, _ in items]
        self._buttons = {}
        # an exclusive group keeps exactly one segment selected, so a second click
        # on the current one leaves it where it is rather than clearing the switch
        self._group = QtWidgets.QButtonGroup(self)
        for i, (key, label, tip) in enumerate(items):
            # a button label's '&' marks the next character as a mnemonic and is
            # swallowed, so it has to be doubled to reach the screen
            b = QtWidgets.QPushButton(label.replace("&", "&&"))
            b.setObjectName("viewSeg")
            # style.py rounds the outer corners of the end segments and drops the
            # borders neighbours would share, so the row reads as one outlined
            # control with the fill as the only boundary inside it
            b.setProperty("seg", "first" if i == 0 else
                          ("last" if i == len(items) - 1 else "mid"))
            b.setCheckable(True)
            b.setToolTip(tip)
            self._group.addButton(b, i)
            self._buttons[key] = b
            lay.addWidget(b)
        # seeded before the connect: the first segment being selected on opening is
        # the initial state, not a change anything should be told about
        self._buttons[self._keys[0]].setChecked(True)
        self._group.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, button, checked):
        # a change toggles two buttons, and the one going off says nothing new
        if checked:
            self.changed.emit(self._keys[self._group.id(button)])

    def current(self):
        """The selected key."""
        return self._keys[self._group.checkedId()]

    def set_current(self, key):
        """Select `key`.  Emits `changed` unless it is selected already."""
        b = self._buttons.get(key)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def button(self, key):
        """The segment for `key`, e.g. to measure or enable it."""
        return self._buttons[key]


def passivity_text(res) -> str:
    """The passivity status for a result.  Shared by the design and plot views so they
    always agree.

    'passive' means the measured sigma_max is at or below 1, 'below ceiling' means it
    is above 1 but at or below the raised ceiling the user set, 'near-passive' means
    enforcement ran and could not reach the ceiling, 'not passive' means the model is
    above the ceiling it was judged against.  The verdict follows the measured value
    rather than the ceiling, so a strictly passive model still reads 'passive' when the
    ceiling happens to be raised.  A failed conversion has no model to judge."""
    if not res.ok:
        return "—"
    sigma = getattr(res, "sigma_max", float("nan"))
    if res.passive:
        # NaN means nothing was measured: a structure model, passive by construction
        return "below ceiling ✓" if sigma > 1.0 else "passive ✓"
    if any("passivity enforced" in m for m in res.messages):
        return "near-passive"
    return "not passive"


_SYMBOLS = {"sigma_max": "σ_max"}


def with_symbols(text: str) -> str:
    """Swap the ASCII names the core writes into messages for their Greek symbols.

    The core keeps those strings ASCII because the CLI prints them to a terminal, and a
    Windows console in cp1252 turns a Greek sigma into '?'.  A Qt label has no such
    limit, so the substitution happens here, at the point of drawing."""
    for ascii_name, symbol in _SYMBOLS.items():
        text = text.replace(ascii_name, symbol)
    return text


def sigma_text(res) -> str:
    """The measured sigma_max against the ceiling it was judged against, e.g. '1.016 / 1.05'.
    An em dash when there is no measured value: a failed conversion, or any structure
    model, which is passive by construction."""
    sigma = getattr(res, "sigma_max", float("nan"))
    if not res.ok or sigma != sigma:               # failed, or NaN
        return "—"
    return f"{sigma:.3f} / {getattr(res, 'passivity_ceiling', 1.0):.2f}"


# Space above a section heading in the Conversion panel, its own top margin.  The
# panel layout's spacing sits under it, so the visible gap from the block above is
# this plus that.  See design_view._ROW_GAP for the other half of the rhythm.
_HEADING_TOP_GAP = 10


def section_title(text: str) -> QtWidgets.QWidget:
    """A section heading for the Conversion panel: a blue tick and a label.

    The margins are asymmetric on purpose.  A heading belongs close to the rows
    it introduces and well clear of the block above it, so the panel reads as
    separate sections rather than one long column.  The bottom margin is the
    tight side and stays that way.
    """
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, _HEADING_TOP_GAP, 0, 2); lay.setSpacing(8)
    tick = QtWidgets.QFrame(); tick.setFixedSize(3, 14)
    tick.setStyleSheet(f"background:{JKU_BLUE};border-radius:1px;")
    lab = QtWidgets.QLabel(text); lab.setProperty("class", "sectionTitle")
    lay.addWidget(tick); lay.addWidget(lab); lay.addStretch(1)
    return w
