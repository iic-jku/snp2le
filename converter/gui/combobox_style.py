"""combobox_style.py - a clean, modern QComboBox style.

Draws a custom down-chevron (enabled + disabled) into the temp dir at runtime and
returns the matching QSS.  Requires a running QApplication (QPixmap needs one), so
call combobox_qss() from build_stylesheet() after the QApplication exists.
"""
import os, tempfile
from PySide6 import QtCore, QtGui

ACCENT_ARROW = "#0084bb"     # enabled arrow colour
DISABLED_ARROW = "#aab2bd"   # disabled arrow colour


def _chevron_png(color, path, size=12):
    """Draw a clean down-chevron and save it as a transparent PNG."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color), size * 0.14)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    m = size / 2.0
    p.drawPolyline(QtGui.QPolygonF([
        QtCore.QPointF(m - 3.3, m - 1.5),
        QtCore.QPointF(m,       m + 1.8),
        QtCore.QPointF(m + 3.3, m - 1.5)]))
    p.end()
    pm.save(path, "PNG")


def combobox_qss(accent=ACCENT_ARROW, disabled=DISABLED_ARROW):
    """QSS for a clean, modern QComboBox: custom chevron, no separator box.

    Generates the arrow images once into the temp dir, then references them.
    Requires a running QApplication (QPixmap needs one). Apply with
    app.setStyleSheet(combobox_qss()) or widget.setStyleSheet(...).
    """
    d = tempfile.gettempdir()
    normal = os.path.join(d, "combo_chevron.png").replace("\\", "/")
    dis = os.path.join(d, "combo_chevron_disabled.png").replace("\\", "/")
    _chevron_png(accent, normal)
    _chevron_png(disabled, dis)
    return f"""
QComboBox {{
    background: #ffffff; color: #000000;
    border: 1px solid #c4ccd6; border-radius: 6px;
    padding: 3px 6px; padding-right: 18px;
    font-size: 12px; font-weight: 600;
}}
QComboBox:hover {{ border: 1px solid {accent}; }}
QComboBox:disabled {{ background: #f0f1f3; color: {disabled}; }}

/* drop-down button: no separator box (removes the faint left/top lines) */
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 18px; border: none; background: transparent; margin: 0;
}}
QComboBox::down-arrow {{ image: url("{normal}"); width: 11px; height: 11px; }}
QComboBox::down-arrow:disabled {{ image: url("{dis}"); }}
QComboBox::down-arrow:on {{ top: 1px; }}   /* nudge while popup is open */

/* the popup list */
QComboBox QAbstractItemView {{
    background: #ffffff; outline: none;
    border: 1px solid #c4ccd6; border-radius: 6px;
    selection-background-color: #e9f5fb; selection-color: #000000;
}}
"""
