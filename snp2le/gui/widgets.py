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


def section_title(text: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 5, 0, 2); lay.setSpacing(8)
    tick = QtWidgets.QFrame(); tick.setFixedSize(3, 14)
    tick.setStyleSheet(f"background:{JKU_BLUE};border-radius:1px;")
    lab = QtWidgets.QLabel(text); lab.setProperty("class", "sectionTitle")
    lay.addWidget(tick); lay.addWidget(lab); lay.addStretch(1)
    return w
