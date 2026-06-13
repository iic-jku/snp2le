"""help_dialog.py - scrollable usage guide opened from the Help button."""
from __future__ import annotations
from PySide6 import QtWidgets

_HTML = """
<h2>S-Parameter&nbsp;\u2192&nbsp;Lumped-Element Netlist Converter &mdash; Quick Guide</h2>

<p>This tool turns a Touchstone <b>.sNp</b> S-parameter file (for example from an
AWS&nbsp;Palace EM simulation) into an equivalent <b>lumped-element netlist</b>
that reproduces the same S-parameters when simulated. The result can be dropped
into a circuit-level simulation (ngspice or VACASK) so an EM-extracted structure
co-simulates with the rest of your design &mdash; without re-running the field solve.</p>

<h3>Top bar</h3>
<ul>
<li><b>Load .sNp</b> &mdash; open any Touchstone file. The header shows the port
count and frequency range.</li>
<li><b>Mode</b> &mdash; two philosophies:
  <ul>
  <li><b>Universal</b> (any N-port): vector-fits the S-parameters and synthesises
  a passive macromodel realised as R, C and controlled sources. Works for any
  structure and port count; the netlist is electrically exact but not physically
  interpretable.</li>
  <li><b>Structure-specific</b>: fits a known physical topology so every component
  maps to reality. Currently available: <i>Inductor</i> (&pi;-model), <i>MIM
  capacitor</i> and <i>Transmission line</i> (RLGC ladder) &mdash; all 2-port.
  Only valid for the matching structure and port count.</li>
  </ul>
  When <b>Universal</b> is selected the <b>Structure</b> dropdown is greyed out;
  when <b>Structure-specific</b> is selected the <b>Max order</b> and <b>Enforce
  passivity</b> controls are greyed out (they only affect the universal fit).</li>
<li><b>Structure</b> &mdash; which physical model to fit. Structures whose port
count does not match the loaded file are greyed out.</li>
<li><b>Max order</b> &mdash; the number of poles the universal vector fit may use.
More poles track sharp resonances and wideband data better but enlarge the
netlist; fewer poles are smaller but coarser.</li>
<li><b>Enforce passivity</b> &mdash; after fitting, adjust the model so it can
never generate energy, guaranteeing a stable transient simulation.</li>
<li><b>View</b> &mdash; switch between <i>Design &amp; Schematic</i> and <i>Plot</i>.</li>
</ul>

<h3>Design &amp; Schematic</h3>
<ul>
<li><b>Result</b> &mdash; the fit/extraction quality: RMS error against the data,
passivity, and the model order (universal) or quality factor (structure).</li>
<li><b>Element values</b> &mdash; the extracted components (physical models, shown
as L<sub>s</sub>&nbsp;=&nbsp;&hellip; etc.) or a summary of the synthesised network
(universal).</li>
<li><b>Schematic</b> &mdash; the drawn topology for a physical model. The universal
macromodel shows a note instead, since its state-space realisation is not a
human-readable schematic.</li>
<li><b>Netlist</b> &mdash; the generated text for both dialects, with export:
<b>Ngspice</b> (Berkeley SPICE3) and <b>VACASK</b> (Spectre syntax).</li>
</ul>

<h3>Plot</h3>
<p>Overlays the <b>loaded S-parameter data</b> (dashed grey) against the
<b>fitted/extracted model</b> (blue). Up to <b>four</b> S-parameters are shown
side by side; each has its own selector, with magnitude (dB) on top and phase
(deg) below. This is how you confirm the netlist reproduces the EM result. The
plots can be popped out into their own window and exported to CSV. Verification of
the final netlist itself is done in your own simulator (e.g. Xschem / ngspice /
VACASK).</p>

<p style="color:#7d828c"><i>Universal mode is built on scikit-rf vector fitting;
the VACASK (Spectre) controlled-source syntax should be checked against your
VACASK build.</i></p>
"""


class HelpDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help \u2014 snp2le")
        self.resize(680, 720)
        lay = QtWidgets.QVBoxLayout(self)
        browser = QtWidgets.QTextBrowser(); browser.setOpenExternalLinks(True)
        browser.setHtml(_HTML)
        browser.setStyleSheet("QTextBrowser{background:#ffffff;color:#000000;"
                              "border:1px solid #d4dae2;border-radius:8px;padding:10px;}")
        lay.addWidget(browser, 1)
        btn = QtWidgets.QPushButton("Close"); btn.setObjectName("primary")
        btn.clicked.connect(self.accept)
        row = QtWidgets.QHBoxLayout(); row.addStretch(1); row.addWidget(btn)
        lay.addLayout(row)
