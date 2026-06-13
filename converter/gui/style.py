"""style.py - the application stylesheet, in the JKU palette.

Reconstructed to match the filter-designer look: dark titlebar with white title
and a Help chip, light control row, white 'panel' frames with blue section
ticks, JKU-blue values, red error fields, and a dark footer.
"""
from __future__ import annotations

# --- JKU colours ----------------------------------------------------------
JKU_BLUE = "#0084bb"
JKU_GRAY = "#7d828c"
JKU_RED = "#d95c4c"
JKU_GREEN = "#5ba755"
JKU_YELLOW = "#f1bc3f"

DARK = "#1b1f24"
PANEL_BORDER = "#d4dae2"
FIELD_BORDER = "#c4ccd6"
LIGHT_BG = "#eef1f5"


def build_stylesheet() -> str:
    return f"""
* {{ font-family: "DejaVu Sans", "Segoe UI", sans-serif; font-size: 12px;
     color: #1a1d21; }}
#root {{ background: {LIGHT_BG}; }}

/* ---- title bar ---- */
#titlebar {{ background: {DARK}; }}
#title {{ color: #ffffff; font-size: 14px; font-weight: 600; }}
#viewLabel {{ color: #aab2bd; font-size: 11px; }}
QPushButton#chip {{ background: rgba(255,255,255,0.10); color: #ffffff;
    border: 1px solid rgba(255,255,255,0.25); border-radius: 6px; padding: 4px 12px; }}
QPushButton#chip:hover {{ background: rgba(255,255,255,0.20); }}

/* ---- control row ---- */
#topbar {{ background: #ffffff; border-bottom: 1px solid {PANEL_BORDER}; }}
.fieldLabel, [class="fieldLabel"] {{ color: {JKU_GRAY}; font-size: 10px; }}
[class="varLabel"] {{ color: #1a1d21; font-size: 12px; }}
[class="sectionTitle"] {{ font-size: 12px; font-weight: 600; color: #1a1d21; }}
[class="panelTitle"] {{ font-size: 12px; font-weight: 600; color: #1a1d21; }}
[class="hint"] {{ color: {JKU_GRAY}; font-size: 11px; }}
[class="tableHead"] {{ color: {JKU_GRAY}; font-size: 10px; font-weight: 600; }}

/* ---- panels ---- */
[class="panel"] {{ background: #ffffff; border: 1px solid {PANEL_BORDER};
    border-radius: 8px; }}
#scrollInner {{ background: #ffffff; }}
QScrollArea {{ background: #ffffff; border: none; }}

/* ---- inputs ---- */
QLineEdit {{ background: #ffffff; border: 1px solid {FIELD_BORDER};
    border-radius: 5px; padding: 3px 6px; }}
QLineEdit:read-only {{ color: {JKU_BLUE}; font-weight: 600; background: #fbfcfe; }}
QLineEdit[error="true"] {{ border: 1px solid {JKU_RED}; background: #fdeeec; }}
QComboBox, QSpinBox {{ background: #ffffff; border: 1px solid {FIELD_BORDER};
    border-radius: 5px; padding: 3px 6px; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: #ffffff; selection-background-color: {JKU_BLUE};
    selection-color: #ffffff; }}

/* ---- buttons ---- */
QPushButton {{ background: #ffffff; border: 1px solid {FIELD_BORDER};
    border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ background: #f1f4f8; }}
QPushButton:disabled {{ color: #aab2bd; }}
QPushButton#primary {{ background: {JKU_BLUE}; color: #ffffff; border: none;
    font-weight: 600; }}
QPushButton#primary:hover {{ background: #0072a3; }}

/* ---- tabs ---- */
QTabWidget::pane {{ border: 1px solid {PANEL_BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 6px 16px; color: {JKU_GRAY};
    font-size: 11px; }}
QTabBar::tab:selected {{ color: {JKU_BLUE}; border-bottom: 2px solid {JKU_BLUE}; }}

/* ---- check / radio ---- */
QRadioButton, QCheckBox {{ spacing: 6px; }}

/* ---- footer ---- */
#footer {{ background: #ffffff; border-top: 1px solid {PANEL_BORDER}; }}
#footerText {{ color: #000000; font-size: 11px; font-weight: 600; }}
QPlainTextEdit {{ background: #ffffff; border: 1px solid {PANEL_BORDER};
    border-radius: 8px; font-family: "DejaVu Sans Mono", monospace; font-size: 11px;
    color: #1a1d21; }}
QTableWidget {{ border: none; gridline-color: #ececf0; }}
QHeaderView::section {{ background: {LIGHT_BG}; border: none; padding: 5px;
    color: {JKU_GRAY}; font-size: 10px; }}
"""
