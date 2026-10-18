# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""help_dialog.py - scrollable usage guide opened from the Help button."""
from __future__ import annotations
from PySide6 import QtWidgets

_HTML = """
<h2>S-Parameter to Lumped-Element Netlist Converter</h2>

<p>This tool turns a Touchstone <b>.sNp</b> S-parameter file (for example from an
AWS&nbsp;Palace EM simulation) into an equivalent <b>lumped-element netlist</b> that
reproduces the same S-parameters when simulated. The result drops into a circuit-level
simulation (<b>Ngspice</b> or <b>VACASK</b>) so an EM-extracted structure co-simulates
with the rest of your design, without re-running the field solve.</p>

<h3>Top bar</h3>
<ul>
<li><b>Load .sNp</b>: open any Touchstone file. The header shows the port count and
frequency range. A file named on the command line (<tt>snp2le design.s4p</tt>) is loaded
at start-up in place of the bundled example, which is how a tool such as setupEM hands
over the result it just wrote, and <b>Reset</b> returns to that file. A file that cannot
be read is reported and the example is loaded instead.
A file whose ports do not share one real reference impedance (one per port, complex, or varying with frequency) is renormalised to 50&nbsp;ohm before the conversion, and the message line says so. A Touchstone 1.1 option line with one reference resistance per port needs scikit-rf 2.2 or later and is refused on older versions, which read only its first value.</li>
<li><b>Mode</b>:
  <ul>
  <li><b>Universal</b> (any N-port): vector-fits the S-parameters into a passive
  macromodel of R, C and controlled sources. Works for any structure and port count.
  Electrically exact but not physically interpretable. Its <b>Max&nbsp;order</b>,
  <b>Enforce&nbsp;passivity</b>, <b>Passivity&nbsp;ceiling</b> and <b>Thermal&nbsp;noise</b>
  controls sit next to the (greyed) Structure box.</li>
  <li><b>Structure-specific</b>: fits a known physical topology, so every component maps
  to reality. Its <b>extraction frequency</b> and any model-specific option sit next to
  the Structure box.</li>
  </ul></li>
<li><b>Structure</b> (structure mode): the physical model to fit. Models whose port count
does not match the loaded file are greyed out:
  <ul>
  <li><b>Inductor</b>, <b>Inductor (wideband)</b>, <b>MIM capacitor</b> (also use this
  for MOM caps), <b>Tline (RLGC)</b> (2-port)</li>
  <li><b>Wilkinson (in-phase)</b>, <b>Wilkinson (quadrature)</b>,
  <b>Inductor (center tap)</b> (3-port)</li>
  <li><b>Balun (transformer)</b>, <b>Branch-line coupler</b> (4-port)</li>
  </ul>
  The two wideband inductors are fitted over the whole band instead of read off at one
  frequency: series R<sub>s</sub>, L<sub>s</sub> and two skin sections
  R<sub>skin</sub>&nbsp;||&nbsp;L<sub>skin</sub>, C<sub>s</sub> across the coil and a
  C<sub>ox</sub>&nbsp;&ndash;&nbsp;(R<sub>si</sub>&nbsp;||&nbsp;C<sub>si</sub>) substrate
  network at each port. The fit uses the data up to 1.2&nbsp;x the self-resonance
  frequency, splits an electrically long coil into up to 3 segments, and keeps the model
  symmetric where the data is. <b>Inductor (center tap)</b> couples its two half coils with
  k and finds the center tap itself (the port in the middle of the coil), the Conversion
  panel names it. A fit takes a few seconds (about 6&nbsp;s for the bundled center tap).
  An element the data does not determine (one the fit can move by a factor of 3 or more at 1&nbsp;% more fit error, typically a skin section whose corner lies above the fit band) is named in the message line with that factor. <b>Basic model</b> leaves the second skin section out.
  Keep the low-frequency data in the fit range: it pins down the DC resistance and
  inductance.</li>
<li><b>f<sub>ext</sub></b> (structure mode): the single frequency at which the lumped
values are read off the data. Accepts engineering notation (e.g. <i>7&nbsp;GHz</i>). If
it is outside the data or the fit range, the Wilkinson dividers and the branch-line coupler
fall back to their design point (best match), the balun to mid-band, and the inductor, MIM
capacitor and line to the nearest data point. The message line names the frequency used.
The wideband
inductors have no extraction frequency and show their own options in its place (below).</li>
<li><b>Max order</b> (universal mode): the largest model order the vector fit may use,
counted as n<sub>real</sub> + 2 x n<sub>complex</sub>, which is the number of internal
states per port in the netlist (an N-port has N times that). A higher order tracks sharp
resonances but enlarges the netlist. The <i>order</i> line in the Result panel reports the
order the fit settled on and, in brackets, its pole count, where a complex-conjugate pair
counts once.</li>
<li><b>Enforce passivity</b> / <b>Passivity ceiling</b> (universal mode): a model is
<i>passive</i> when the largest singular value of its S-matrix, &sigma;<sub>max</sub>,
stays at or below 1 at every frequency, which is the same as saying it can never deliver
more power than it absorbs. A non-passive model is not just inaccurate: a transient run
can feed on the excess energy and grow without bound, so the simulation blows up or
refuses to converge even though the AC response looked fine.
<p>Making it passive is not free. A vector fit typically violates passivity outside the
band it was fitted to, and pushing it back below 1 there costs accuracy inside the band,
often by one to two orders of magnitude in RMS error. The <b>Passivity ceiling</b> is how
far the enforcement has to go, so it buys that accuracy back in exchange for a bounded,
known violation.</p>
  <ul>
  <li><b>Ticked</b> (the default): the fit is perturbed until it reaches the ceiling. At
  <i>1.00</i> that is strict passivity, which is what you want for anything simulated in
  the time domain. Raise it to stop short: on <tt>wpd_ihp-sg13g2.s3p</tt> at order 6 the
  raw fit sits at 1.083 with RMS 8.7e-04, a ceiling of 1.00 gives 0.9999 at 2.6e-03, and a
  ceiling of 1.05 gives 1.0499 at 1.3e-03, half the accuracy cost. A ceiling above what the
  fit already measures leaves the model untouched rather than adding gain to reach it.</li>
  <li><b>Unticked</b>: nothing is enforced and the raw fit is exported as it is. The
  ceiling field greys out at <i>1.00</i>, since nothing is aiming at it, and
  &sigma;<sub>max</sub> is still measured and reported so you can see what you are
  shipping.</li>
  </ul>
The range is <i>1.00</i> to <i>1.20</i>. A number outside it is replaced by the limit it
overshot, so entering <i>9.9</i> leaves <i>1.20</i> in the field and <i>0.5</i> leaves
<i>1.00</i>, which is the quickest way to see what the limits are. Text that is not a
number falls back to <i>1.00</i>. Reasonable ceilings: <i>1.00</i> for a transient or a
long harmonic-balance run, <i>1.01</i> to <i>1.05</i> for an AC or S-parameter sweep where
a per-cent-level violation outside your band cannot do anything, and up to <i>1.20</i>
only as a diagnostic while you are looking at what the fit is doing.
<p><b>A ceiling is not always reachable.</b> The perturbation only moves the model's
residues, so a violation band that runs to infinity, caused by a non-passive constant
term, cannot be corrected at any ceiling. <tt>tline_100um_ihp-sg13g2.s2p</tt> at order 13
has its constant term at 5.24. A file that carries a 0 Hz point, as this one does, then
also gets a refit that includes it, which scikit-rf meets through the constant term, and
it is kept if it passes and fits closer than a lower-order refit (the line comes out passive
at model order 9 that way).
That outcome is fragile: a random change of 1e-12 in the file's S values made the refit miss in 1 or 2 of 8 tries, and the line then reads <i>near-passive</i> at 5.24, while order 6 gave the same result every time.
The refit needs a fit range that starts at the file's first
sample above 0&nbsp;Hz. With <b>Thermal noise</b> ticked, a strictly passive candidate wins
over one that only meets a raised ceiling, since only it can carry the noise. When nothing
reaches the ceiling, the accurate fit is kept rather than a wrecked one and the result
reads <i>near-passive</i>. The fix is a lower <b>Max order</b>, not a higher ceiling, since
order 6 brings the same file to 0.9997. Whenever the constant term D, the model's value
at infinite frequency, is above the ceiling, the message line says so with its singular
value.</p></li>
<li><b>Thermal noise</b> (universal mode): a lossy passive at temperature T is a noise
source, and its noise follows from its S-parameters alone, kT(I&nbsp;&minus;&nbsp;S&nbsp;S<sup>H</sup>)
at its ports (Bosma's theorem). Unticked (the default), the model is noiseless, an ideal
block. Ticked, snp2le computes a noise generator from the fitted model (its spectral factor)
and appends it to the subcircuit: one 0.25&nbsp;&Omega; resistor per port
(<tt>Rnz_e1</tt>, <tt>Rnz_e2</tt>, ...) is the only noise source, driving controlled sources
that inject the correlated noise waves into the ports. Nothing feeds back into the fitted
network, so the S-parameters and the operating point stay exactly as they are. A noise
analysis shows the block's noise as the sum of its <tt>Rnz_e*</tt> contributions. VACASK
sees it in <tt>noise</tt>, <tt>hbnoise</tt>, <tt>pnoise</tt> and transient noise, Ngspice in
<tt>.noise</tt> only, since it has no periodic noise analysis and adds no resistor noise to a
transient run. The noise is only as good as the loss in the S-parameter data.
<p><b>It needs a strictly passive model</b>, so keep <b>Enforce passivity</b> ticked and
the <b>Passivity ceiling</b> at <i>1.00</i>. If the model is not strictly passive at every
frequency, far outside the data included,
no generator exists: the noise is not added, the <i>noise</i> result reads <i>NOT added</i>,
the message line names &sigma;<sub>max</sub>, and <b>Export</b> refuses until it is fixed
or the box is unticked. Structure models need no option: their resistors are the
structure's loss, and an RLC network with noisy resistors already emits exactly its own
kT(I&nbsp;&minus;&nbsp;S&nbsp;S<sup>H</sup>), so their noise is as complete as the loss the
model contains.</p></li>
<li><b>Fit range (GHz)</b> (both modes): the band of the loaded file the model is fitted
to, as two plain numbers in GHz (the unit is in the label, so there is nothing to type but
the number). Loading a file puts its own span in the fields, so they always name the band
being fitted, and the default is still the whole file. Narrow them to fit a sub-band, e.g.
<i>110</i> to <i>170</i>. Spending the model order on the band you actually operate in
gives a much better fit there than spreading it over a wide EM sweep, at the price of a
model that says nothing outside the band. An edge outside the data is clamped to the data
and reported, an empty or inverted band is refused, and clearing a field leaves that side
at the file's own edge. The band applies to everything downstream: the RMS error, the
tolerances, the plots, and the sweep written into a testbench run. The <b>Result</b> panel
shows the band actually fitted, highlighted while it is a sub-band.
<p><b>DC pin</b>, the tick box on the caption line (universal mode, ticked by default): a
file can carry a 0 Hz sample, which the fit drops and extrapolates to, so a coil's DC
resistance comes out tens of percent off. The pin adds the difference at DC through a
low-pass with a 160&nbsp;Hz corner, so the model meets the 0 Hz sample exactly while the
fitted band moves by less than the fit's own error. It is checked first, and skipped with a
note if it would cost passivity, move the band by more than the fit's error, or make the DC
operating point singular. In a transient run a bias step settles on a 1&nbsp;ms scale, and
below a few kHz the thermal noise is the fit's. It acts only on a file with a 0 Hz sample,
also below a fit range that starts above it.</p></li>
<li><b>Model option</b> (shown only for the structure it belongs to):
  <ul>
  <li><b>Stages</b>: number of RLGC ladder cells for the transmission line (1 to 10).</li>
  <li><b>Isolation R</b>: include the in-phase Wilkinson's
  2&middot;Z<sub>0</sub> isolation resistor (untick to model a divider without it).</li>
  <li><b>Resistive loss</b>: add fitted series resistance to the branch-line
  coupler's arms (one arm Q matched to the device's loss), lifting its otherwise ideal
  reflection and isolation terms toward the measured values.</li>
  </ul></li>
<li><b>Wideband inductor options</b> (in place of f<sub>ext</sub> for the two wideband
inductors):
  <ul>
  <li><b>Basic model</b>: a fixed topology, 1 coil segment, 1 skin section and no
  substrate coupling, so every fit has the same elements (e.g. for data tables). Untick to
  let the fit add what the data needs.</li>
  <li><b>Segments</b> (2-port): <i>auto</i> lets the fit pick the fewest of 1, 2 and 3
  segments within 10&nbsp;% of the best, a number fixes it. <b>Basic model</b> fixes it
  at 1.</li>
  <li><b>Center tap</b> (center-tapped inductor): <i>auto</i> takes the port the data puts
  in the middle of the coil, a number sets it. The netlist keeps the file's port order
  either way.</li>
  <li><b>Peak-Q weight</b>: weights L and Q up to 3x where the data's Q is at least
  0.8&nbsp;x its peak, e.g. for a VCO tank, at a little more error elsewhere.</li>
  <li><b>Measured data</b>: for measured or FDTD data, tolerates substrate errors below
  0.01&nbsp;x the series branch, so noise at low frequency cannot pull the substrate values
  off. Clean EM data does not need it.</li>
  </ul>
  The CLI also takes other weights, up to 10 segments and a fixed substrate network
  (<tt>--peak-q-weight</tt>, <tt>--shunt-accuracy</tt>, <tt>--segments</tt>,
  <tt>--substrate</tt>).</li>
<li><b>View</b>: the two-segment switch at the right of the title bar, holding
<i>Design&nbsp;&amp;&nbsp;Schematic</i> and <i>Plot</i> side by side. The view you are on
is the filled one, and one click moves to the other. It follows the plots too: popping
them out into their own window leaves the design on screen, docking them brings the plot
view back, and an imported simulation switches to it so the overlay is visible.</li>
</ul>

<h3>Conversion progress</h3>
<p>Progress shows in the <b>Conversion</b> panel, under the loaded file name and just
above the <i>Result</i> rows it fills in, and again in the <b>Plot</b> view's header row
so switching views does not lose sight of a running fit. While one runs it shows what the
fit is doing, how long it has been running, and a progress bar. When it ends the line
becomes the outcome and the bar stays where it stopped: green
<i>conversion complete</i> with the total time beside it and the bar full, or red with
the reason and the bar left where the attempt got to. It stands there until the next
conversion starts.</p>
<ul>
<li>The window stays usable while a fit runs: the conversion is not on the UI thread.</li>
<li>No time-left estimate is shown. The progress fraction is not linear in time, since
there is no way to know in advance how many iterations the fit will take, so any figure
derived from it would be guesswork.</li>
<li>The completion line carries only the elapsed time. The pole count and RMS error are
in the <i>Result</i> rows below it.</li>
<li>Changing controls during a fit does not queue one conversion per change. The running
fit finishes, then the newest settings are converted, once.</li>
<li>A long fit that ends while you are in another window flashes the taskbar entry.</li>
<li><b>Export</b> writes the conversion that finished, so it is greyed out while one is
running.</li>
</ul>

<h3>Design &amp; Schematic</h3>
<ul>
<li><b>Load design</b> / <b>Save design</b> (top of the Conversion panel): save every
conversion setting and the path of the loaded file as JSON, and load it back, which also
reloads that file. A design written by hand or by a script can carry the CLI's DC pin
corner and island leak, which the window has no control for and keeps until
<b>Reset</b>. Whenever the DC pin acts, its note in the message line names those that
differ from the defaults. In the file, null means the default, a value that is no number
(true, a string) refuses the design, and a number out of range, NaN included, skips the
pin with a note.
A design that names no file, or one that cannot be read, is applied to the file already
loaded, and a dialog names a file that is missing.</li>
<li><b>Result</b>: fit/extraction quality. RMS error against the data, passivity,
&sigma;<sub>max</sub> against the ceiling it was judged against (green below the
ceiling, red above it), the model order (universal), the extraction frequency (structure)
or the top of the fitted band (wideband inductors),
and the <i>noise</i> the netlist carries: <i>noiseless</i>, <i>thermal (R) &#10003;</i> in
green when <b>Thermal noise</b> added the generator, <i>NOT added</i> (red) when the model could not
carry it, or <i>thermal (R)</i> without colour for a structure model, whose resistors carry
their own noise. A structure model without resistors, such as the branch-line coupler
without <b>Resistive loss</b>, reads <i>noiseless</i>.
Passivity reads <i>passive &#10003;</i> below 1, <i>below ceiling &#10003;</i> when a raised
ceiling was reached, <i>near-passive</i> when enforcement ran and could not reach it, and <i>not
passive</i> when the model is above its ceiling. Structure models are passive by
construction, so they show no &sigma;<sub>max</sub>. When there is a violation, the
message line under the panel also names the frequency of the peak: at 0&nbsp;Hz or inside
your band it is a real hazard, while one far above the top data point is the model's
high-frequency asymptote and usually means the order is too high for the file. For a
universal
macromodel it also reports a <b>DC operating point</b> check: the model is linear, so its
DC solve only fails if the network is singular (typically an internal node with no DC path
to ground). A solvable model is marked. A singular one is flagged, with a hint to lower
the order or enable passivity, before you hand the netlist to a simulator.</li>
<li><b>Element values</b>: the extracted components (e.g. L<sub>s</sub>, R<sub>s</sub>,
C, k, M) for a physical model, or a summary of the synthesised network for the
universal macromodel. The schematic draws component <i>names</i> only. The numeric values
live here.</li>
<li><b>Tolerances</b> (the inductor, MIM capacitor, line and balun models: the Wilkinson
dividers and the branch-line coupler are synthesised from their design frequency, and the
wideband inductors are fitted over the band): the per-element agreement at the extraction
frequency, |data&nbsp;&minus;&nbsp;model|&nbsp;/&nbsp;model in&nbsp;%. Directly-read
reciprocal terms (a series L, R) read about 0&nbsp;%, because the model reproduces them
exactly. Terms the model can only approximate (e.g. a shunt C forced symmetric across two
slightly asymmetric ports) carry the residual. The line model builds its elements from the
magnitude of the data's R', L', G' and C', and the message line names any the data puts
below zero. A loss term R' or G' a hair under zero, as an EM solver gives, still reads
about 0&nbsp;%. A negative L' or C' reads 200&nbsp;%, since the model's reactance then has
the wrong sign. The &#9675; marker on each
model curve in the Plot view sits at this frequency.</li>
<li><b>Schematic</b>: the drawn topology for a physical model. The universal macromodel
shows a note instead.</li>
<li><b>Netlist</b>: the generated text for both dialects, in two tabs. <b>Export
Ngspice</b> and <b>Export VACASK</b> in the top bar write it to a file, and its header
names the snp2le version that wrote it. <b>Ngspice</b>
(Berkeley SPICE3, <tt>.spice</tt>) and <b>VACASK</b> (Spectre syntax, <tt>.inc</tt>).
Transformer coupling is emitted as a builtin <tt>mutual</tt> instance. Device models and
OSDI loads come from your testbench, not the exported subcircuit. A universal macromodel's
resistors carry <tt>noisy=0</tt> (understood by both simulators): they exist to reproduce
the fitted response, not to model a device, and charging thermal noise against them would
report noise that tracks the fit order instead of the structure. Without <b>Thermal
noise</b> the model is therefore fully noiseless. With it, the generator's
<tt>Rnz_e*</tt> resistors are the only ones without <tt>noisy=0</tt>.
A structure model's resistors are real loss (an isolation resistor, a coil's conductor
loss) and keep their noise. In VACASK the
subcircuit's ground is node <tt>GND</tt>: Spectre has no implicit node-0 ground the way
SPICE does, so your testbench must declare <tt>ground&nbsp;GND</tt> (Xschem's spectre
netlist does this automatically). A subcircuit grounded to a bare <tt>0</tt> would float
and give a flat / wrong result. Ngspice keeps node <tt>0</tt>. The subcircuit is named
after the export file, but only letters, digits and '_' are valid in a SPICE / Spectre
subcircuit name: a file like <tt>two-port</tt> is exported as subckt <tt>two_port</tt>
(since '-' is the minus operator), and a note window reports the actual name. Use '_'
rather than '-' in the file name to keep the file and the subcircuit identical.</li>
</ul>

<h3>Plot</h3>
<p>Overlays the <b>loaded data</b> (solid grey) against the <b>fitted/extracted model</b>
(dashed blue), plus an imported simulation (red) once you run one. Up to <b>four</b>
traces are shown side by side, each with its own selector: any S-parameter (magnitude in
dB on top, phase in &deg; below), or, for structure models, an
extracted-parameter view over frequency (e.g. L<sub>diff</sub>&nbsp;/&nbsp;Q for the inductor, or
L<sub>p</sub>/R<sub>p</sub>, Q<sub>p</sub>/Q<sub>s</sub> and k/M for the balun). A
&#9675; marker on each model curve marks the extraction frequency (structure models).</p>

<p>Each plot has a live x/y read-out and a <b>marker mode</b> (the crosshair toolbar
button): with it on, click a curve to drop a labelled data-point marker (up to three per
plot), click a marker to remove it, right-click to clear all. The plots pop out into their
own window and export to CSV. <b>Import simulation</b> loads a simulation result table by
hand (Ngspice or VACASK, from <tt>plot_simulations/data/</tt>) and turns into <b>Clear
simulation</b> once one is shown.</p>

<h3>Simulating a testbench</h3>
<p>To verify the netlist in a real simulator, export it, drop the subcircuit into an
Xschem testbench, then run it from here:</p>
<ul>
<li><b>Load .sch</b>: pick the Xschem testbench. The <b>Simulator</b> is auto-set from the
file name (a name containing <i>vacask</i> selects VACASK) and can be overridden.</li>
<li><b>Simulator</b>: <b>Ngspice</b> or <b>VACASK</b>. Both netlist&nbsp;+&nbsp;simulate
through Xschem and write their result to the testbench's <tt>plot_simulations/data/</tt>
folder, which is imported and overlaid on the plots automatically. The location is read from the
testbench itself (its <tt>wrdata</tt> target, or VACASK's log), so a testbench with a
custom output folder imports just the same.</li>
<li><b>Run Simulation</b>: runs the loaded testbench. The button turns green (successful)
or red (failed). If no result appears, the dialog shows the simulator log. Loading another
testbench frees the button if a run or import is still pending.</li>
<li><b>Frequency range</b>: each run writes the fitted band into the testbench sweep
(through an included <tt>sim_range</tt> file), so the simulated overlay covers the same
band as the data the model was fitted to (the full file unless a <b>Fit range</b> is
set). The design point <tt>f0</tt> stays in the testbench, and the testbench still runs
standalone in Xschem with the last-written range.</li>
<li><b>Show output</b>: tick to show the simulator's console and plot windows during the
run. For Ngspice these are its own console and plot windows. VACASK is launched detached,
so instead a live <b>VACASK output</b> window tails its captured log (banner, analysis
progress, <i>Completed</i> / <i>Failed</i> / <i>aborted</i> messages, postprocess lines).
Leave it unticked to run quietly. The result is imported either way, and VACASK's captured
log still appears in the dialog if a run fails or aborts.</li>
</ul>

<p><b>How a run's outcome is detected.</b> The two simulators report differently, so snp2le
uses the most reliable signal for each:</p>
<ul>
<li><b>Ngspice</b>: a non-zero Xschem exit code, or a failure line in Xschem's output, is
reported at once. Otherwise snp2le waits up to 60&nbsp;s for the result table and reports
<b>failed!</b> if none appears, since Xschem can return before Ngspice finishes and exits
cleanly even when it fails. A run that writes its result is imported as a success.</li>
<li><b>VACASK</b> is launched through Xschem, which always exits cleanly itself, and VACASK
keeps its <i>Completed</i> / <i>Failed</i> / <i>aborted</i> messages on its own console
rather than passing them back. So the outcome is read from the <b>result file</b>:
  <ul>
  <li><b>Completed</b> (success): the analysis ran and the postprocess wrote
  <tt>plot_simulations/data/&lt;testbench&gt;.txt</tt>, which is imported, and the button
  turns green (<b>successful!</b>).</li>
  <li><b>Aborted</b>: the analysis started but broke numerically (e.g. a singular matrix).
  No result is written, but the postprocess leaves an <tt>.aborted</tt> marker, so snp2le
  reports <b>aborted!</b>.</li>
  <li><b>Failed</b>: VACASK could not run at all (e.g. a netlist or model error). No result
  and no marker, so snp2le reports <b>failed!</b>.</li>
  </ul>
  VACASK runs detached, so snp2le watches for the result file and the abort marker and
  reports the outcome as soon as VACASK finishes. Either way, open VACASK's console or log
  for the specific cause.</li>
</ul>
<p><b>VACASK and high-order universal macromodels.</b> The vector-fit realisation is
numerically ill-conditioned at high order (its pole gains span ~1e-5 to ~1e11). Ngspice's
solver equilibrates the matrix internally and copes. VACASK's does not, and on its own
would mis-place the resonances above ~5 poles. snp2le conditions the exported macromodel
automatically (a lossless rescale of the state resistors plus a gain-balance of the
controlled sources), so high-order universal fits now reproduce the model in VACASK exactly
as they do in Ngspice. No action is needed, and structure-specific models are unaffected.</p>

<p>While a run is in progress the status reads <i>running...</i> (for as long as the
simulation takes, and for a VACASK run until its result appears) and then, for Ngspice,
<i>importing...</i>. The <b>Run Simulation</b> button becomes a <b>Stop</b> button you can
press to cancel. A run is not stopped for being slow. An Ngspice run without <b>Show
output</b> is stopped when it has used no CPU for 60&nbsp;s and looks hung, or after
30&nbsp;min on a system without <tt>/proc</tt>, such as Windows, where idle detection is
not available. A VACASK run, which Xschem starts detached, ends as failed 1.5&nbsp;s after
VACASK exits without a result. Every run has a 1&nbsp;h backstop.</p>

<p style="color:#7d828c"><i>Universal mode is built on scikit-rf vector fitting. The VACASK
passive, controlled-source (vccs, cccs) and ground (<tt>GND</tt>) handling are confirmed
against VACASK. So is the <tt>mutual</tt> coupling of the balun and the wideband inductors:
VACASK takes k from 0 to 1 only, so a negative k (the balun) is written as the positive one
with one coil's terminals swapped, and the bundled testbenches declare
<tt>model mutual mutual</tt>.</i></p>"""


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
