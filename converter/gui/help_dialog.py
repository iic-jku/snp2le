"""help_dialog.py - scrollable usage guide opened from the Help button."""
from __future__ import annotations
from PySide6 import QtWidgets

_HTML = """
<h2>S-Parameter to Lumped-Element Netlist Converter</h2>

<p>This tool turns a Touchstone <b>.sNp</b> S-parameter file (for example from an
AWS&nbsp;Palace EM simulation) into an equivalent <b>lumped-element netlist</b> that
reproduces the same S-parameters when simulated. The result drops into a circuit-level
simulation (<b>ngspice</b> or <b>VACASK</b>) so an EM-extracted structure co-simulates
with the rest of your design, without re-running the field solve.</p>

<h3>Top bar</h3>
<ul>
<li><b>Load .sNp</b>: open any Touchstone file. The header shows the port count and
frequency range.</li>
<li><b>Mode</b>:
  <ul>
  <li><b>Universal</b> (any N-port): vector-fits the S-parameters into a passive
  macromodel of R, C and controlled sources. Works for any structure and port count;
  electrically exact but not physically interpretable. Its <b>Max&nbsp;order</b> and
  <b>Enforce&nbsp;passivity</b> controls sit next to the (greyed) Structure box.</li>
  <li><b>Structure-specific</b>: fits a known physical topology, so every component maps
  to reality. Its <b>extraction frequency</b> and any model-specific option sit next to
  the Structure box.</li>
  </ul></li>
<li><b>Structure</b> (structure mode): the physical model to fit. Models whose port count
does not match the loaded file are greyed out:
  <ul>
  <li><b>Inductor</b>, <b>MIM capacitor</b> (also use this for MOM caps),
  <b>Tline (RLGC)</b> &mdash; 2-port</li>
  <li><b>Wilkinson (in-phase)</b>, <b>Wilkinson (quadrature)</b> &mdash; 3-port</li>
  <li><b>Balun (transformer)</b>, <b>Branch-line coupler</b> &mdash; 4-port</li>
  </ul></li>
<li><b>f<sub>ext</sub></b> (structure mode): the single frequency at which the lumped
values are read off the data. Accepts engineering notation (e.g. <i>7&nbsp;GHz</i>); if
it is outside the data it falls back to the device's natural design point.</li>
<li><b>Max order</b> / <b>Enforce passivity</b> (universal mode): the number of poles the
vector fit may use (more poles track sharp resonances but enlarge the netlist), and
whether to make the model strictly passive for a stable transient run.</li>
<li><b>Model option</b> (shown only for the structure it belongs to):
  <ul>
  <li><b>Stages</b> &mdash; number of RLGC ladder cells for the transmission line.</li>
  <li><b>Isolation R</b> &mdash; include the in-phase Wilkinson's
  2&middot;Z<sub>0</sub> isolation resistor (untick to model a divider without it).</li>
  <li><b>Resistive loss</b> &mdash; add fitted series resistance to the branch-line
  coupler's arms (one arm Q matched to the device's loss), lifting its otherwise ideal
  reflection / isolation terms toward the measured values.</li>
  </ul></li>
<li><b>View</b>: switch between <i>Design &amp; Schematic</i> and <i>Plot</i>.</li>
</ul>

<h3>Design &amp; Schematic</h3>
<ul>
<li><b>Result</b>: fit/extraction quality &mdash; RMS error against the data, passivity,
and the model order (universal) or the extraction frequency (structure).</li>
<li><b>Element values</b>: the extracted components (e.g. L<sub>s</sub>, R<sub>s</sub>,
C, k, M&hellip;) for a physical model, or a summary of the synthesised network for the
universal macromodel. The schematic draws component <i>names</i> only; the numeric values
live here.</li>
<li><b>Tolerances</b> (structure models): the per-element agreement at the extraction
frequency, |data&nbsp;&minus;&nbsp;model|&nbsp;/&nbsp;model in&nbsp;%. Directly-read
reciprocal terms (a series L, R) read ~0&nbsp;% &mdash; the model reproduces them exactly;
terms the model can only approximate (e.g. a shunt C forced symmetric across two slightly
asymmetric ports) carry the residual. The &#9675; marker on each model curve in the Plot
view sits at this frequency.</li>
<li><b>Schematic</b>: the drawn topology for a physical model. The universal macromodel
shows a note instead.</li>
<li><b>Netlist</b>: the generated text for both dialects, with export &mdash;
<b>Ngspice</b> (Berkeley SPICE3, <tt>.spice</tt>) and <b>VACASK</b> (Spectre syntax,
<tt>.inc</tt>). Transformer coupling is emitted as a builtin <tt>mutual</tt> instance;
device models and OSDI loads come from your testbench, not the exported subcircuit.</li>
</ul>

<h3>Plot</h3>
<p>Overlays the <b>loaded data</b> (solid grey) against the <b>fitted/extracted model</b>
(dashed blue), plus an imported simulation (red) once you run one. Up to <b>four</b>
traces are shown side by side, each with its own selector: any S-parameter (magnitude in
dB on top, phase in &deg; below), or &mdash; for structure models &mdash; an
extracted-parameter view over frequency (e.g. L&nbsp;/&nbsp;Q for the inductor, or
L<sub>p</sub>/R<sub>p</sub>, Q<sub>p</sub>/Q<sub>s</sub> and k/M for the balun). A
&#9675; marker on each model curve marks the extraction frequency (structure models).</p>

<p>Each plot has a live x/y read-out and a <b>marker mode</b> (the crosshair toolbar
button): with it on, click a curve to drop a labelled data-point marker (up to three per
plot), click a marker to remove it, right-click to clear all. The plots pop out into their
own window and export to CSV.</p>

<h3>Simulating a testbench</h3>
<p>To verify the netlist in a real simulator, export it, drop the subcircuit into an
Xschem testbench, then run it from here:</p>
<ul>
<li><b>Load .sch</b>: pick the Xschem testbench. The <b>Simulator</b> is auto-set from the
file name (&hellip;<i>_vacask</i> &rarr; VACASK) and can be overridden.</li>
<li><b>Simulator</b>: <b>Ngspice</b> or <b>VACASK</b>. Both netlist&nbsp;+&nbsp;simulate
through Xschem and write their result to <tt>sim_data/</tt>, which is imported and
overlaid on the plots automatically.</li>
<li><b>Run Simulation</b>: runs the loaded testbench. The button turns green (successful)
or red (failed); if no result appears, the dialog shows the simulator log. Loading another
testbench frees the button if a run/import is still pending.</li>
<li><b>Show output</b>: tick to show the simulator's console / plot windows during the run;
leave unticked to run quietly (the result is imported either way).</li>
</ul>

<p style="color:#7d828c"><i>Universal mode is built on scikit-rf vector fitting. The
VACASK passive and <tt>mutual</tt>-coupling syntax follows the confirmed reference
netlists; the universal controlled-source syntax (vccs&nbsp;/&nbsp;vcvs&nbsp;/&nbsp;cccs)
should still be checked against your VACASK build.</i></p>"""


class HelpDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
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
