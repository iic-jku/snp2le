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
DISABLED_FG = "#aab2bd"        # greyed-out text (inputs, disabled combo items)

# Status-text colours, tuned to read as small text on the light panels.  The JKU
# fills above (e.g. JKU_GREEN) are too light for text, so these status shades run
# darker while keeping the same red as JKU_RED.
STATUS_GREEN = "#2e7d32"
STATUS_AMBER = "#b8860b"
STATUS_RED = JKU_RED


def build_stylesheet() -> str:
    import os
    _assets = os.path.join(os.path.dirname(__file__), "assets")
    # QSS url() wants forward slashes, even on Windows
    spin_up = os.path.join(_assets, "spin_up.svg").replace("\\", "/")
    spin_down = os.path.join(_assets, "spin_down.svg").replace("\\", "/")
    from .combobox_style import combobox_qss
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
QLineEdit:disabled {{ background: #eef1f5; color: #aab2bd; }}
QLineEdit[error="true"] {{ border: 1px solid {JKU_RED}; background: #fdeeec; }}
QSpinBox {{ background: #ffffff; border: 1px solid {FIELD_BORDER};
    border-radius: 5px; padding: 3px 6px; }}
/* greyed-out look for controls that do not apply to the current mode
   (QComboBox styling lives in combobox_style.combobox_qss, appended below) */
QSpinBox:disabled {{ background: #eef1f5; color: #aab2bd; }}
QCheckBox:disabled {{ color: #aab2bd; }}
/* spin box up/down buttons: give them real geometry + visible arrows so both
   are clickable (a bare QSpinBox stylesheet collapses them otherwise). */
QSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; background: #f1f4f8;
    border-left: 1px solid {FIELD_BORDER}; }}
QSpinBox::up-button {{ subcontrol-position: top right;
    border-top-right-radius: 5px; border-bottom: 1px solid {FIELD_BORDER}; }}
QSpinBox::down-button {{ subcontrol-position: bottom right;
    border-bottom-right-radius: 5px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #e7ecf3; }}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: #dbe2ec; }}
QSpinBox::up-arrow {{ image: url("{spin_up}"); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url("{spin_down}"); width: 9px; height: 9px; }}

/* ---- buttons ---- */
QPushButton {{ background: #ffffff; border: 1px solid {FIELD_BORDER};
    border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ background: #f1f4f8; }}
QPushButton:disabled {{ color: #aab2bd; }}
QPushButton#primary {{ background: {JKU_BLUE}; color: #ffffff; border: none;
    font-weight: 600; }}
QPushButton#primary:hover {{ background: #0072a3; }}
QPushButton#primary:disabled {{ background: #aab2bd; color: #eef1f5; }}
/* Run Simulation outcome: green on success, red on failure (white, bold) */
QPushButton#runOk {{ background: {JKU_GREEN}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#runOk:hover {{ background: #4f9249; }}
QPushButton#runFail {{ background: {JKU_RED}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#runFail:hover {{ background: #c54e3f; }}

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
""" + combobox_qss()
