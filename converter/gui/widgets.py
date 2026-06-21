"""widgets.py - small reusable Qt widgets (math labels, entries, section title).

Ported from the filter designer so the two tools share look and behaviour.
"""
from __future__ import annotations
from PySide6 import QtCore, QtWidgets

from .style import JKU_BLUE

_GREEK = {"omega": "\u03c9", "Omega": "\u03a9", "Delta": "\u0394", "mu": "\u00b5",
          "pi": "\u03c0", "tau": "\u03c4", "alpha": "\u03b1", "beta": "\u03b2"}


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


def passivity_text(res) -> str:
    """The passivity status for a result: 'passive', 'near-passive' or 'not
    enforced'.  Shared by the design and plot views so they always agree."""
    if res.passive:
        return "passive ✓"
    if any("passivity enforced" in m for m in res.messages):
        return "near-passive"
    return "not enforced"


def section_title(text: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 5, 0, 2); lay.setSpacing(8)
    tick = QtWidgets.QFrame(); tick.setFixedSize(3, 14)
    tick.setStyleSheet(f"background:{JKU_BLUE};border-radius:1px;")
    lab = QtWidgets.QLabel(text); lab.setProperty("class", "sectionTitle")
    lay.addWidget(tick); lay.addWidget(lab); lay.addStretch(1)
    return w
