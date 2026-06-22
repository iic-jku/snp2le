// ============================================================================
//  cheat_sheet.inc  --  VACASK / Spectre-dialect reference netlist
//  Lumped-element band-pass-filter DUT  +  component syntax cheat_sheet
// ----------------------------------------------------------------------------
//  Syntax recap (the parts below are confirmed against real VACASK netlists):
//    instance :  name (node1 node2 ...) master  par=value ...
//    subckt   :  subckt NAME (ports) parameters p=default ...  <body>  ends
//    model    :  model MODELNAME MODULENAME ( par=value ... )
//    load     :  load "module.osdi"      // brings in a compiled Verilog-A device
//    include  :  include "file.inc"      // verbatim text inclusion
//    ground   :  ground 0
//    vectors  :  [a, b, c]               // comma-separated (e.g. PWL wave=[...])
//    comments :  //                      // C++ style
//  >> Parentheses around the node list are REQUIRED (they delimit nodes/master).
//  >> Names are case-sensitive.
// ============================================================================


// ============================================================================
//  SECTION A -- THE DUT  (this is the only active part of the file)
//  A 2-port lumped-element band-pass filter. Values are placeholders.
//  Port order MUST match the symbol's @pinlist order:  (p1 = in, p2 = out).
// ============================================================================
subckt cheat_sheet (p1 p2)
parameters rs=0.5 l1=5n c1=2p l2=3n c2=1p

  // resistor :  name (n+ n-) resistor  r=<ohm>
  rs1  (p1 n1)  resistor  r=rs

  // inductor :  name (n+ n-) inductor  l=<henry>
  l1a  (n1 n2)  inductor  l=l1
  // capacitor:  name (n+ n-) capacitor c=<farad>
  c1a  (n2 0 )  capacitor c=c1

  l2a  (n2 p2)  inductor  l=l2
  c2a  (p2 0 )  capacitor c=c2
ends


// ============================================================================
//  SECTION B -- COMPONENT CHEAT-SHEET  (all commented; copy what you need)
//  NOTE: `load`/`model` are GLOBAL. In a normal flow they live in the
//  testbench (.sim), not in the DUT .inc, so the same module is not loaded
//  twice. They are shown here only for reference.
// ============================================================================

// ---- Verilog-A passives shipped with VACASK (resolved via SIM_MODULE_PATH) --
// load "resistor.osdi"     // module resistor(A,B)   param: r  [, has_noise=1]
// load "capacitor.osdi"    // module capacitor(A,B)  param: c
// load "inductor.osdi"     // module inductor(A,B)   param: l
// load "diode.osdi"        // module diode(...)      (see diode.va for params)

// Builtins (no load needed): vsource  isource  vcvs vccs ccvs cccs  + L-coupling

// ---- Passives ---------------------------------------------------------------
// r1   (a b)        resistor  r=2k
// c1   (a b)        capacitor c=1p
// l1   (a b)        inductor  l=3n

// ---- Independent voltage source --------------------------------------------
// DC operating point + AC small-signal stimulus (mag/phase = Spectre form):
// v1   (in 0)       vsource dc=0 mag=1 phase=0
// Transient waveforms (CONFIRMED forms):
// vpls (in 0)       vsource type="pulse" v0=0 v1=1 delay=1n rise=1n fall=1n width=5n
// vpwl (in 0)       vsource type="pwl"   wave=[0,0, 1n,1, 2n,1, 3n,0]
// vsin (in 0)       vsource type="sine"  ...    // sine exists; check param names

// ---- Independent current source --------------------------------------------
// i1   (n+ n-)      isource dc=1m               // same waveform options as vsource

// ---- Diode (nonlinear) ------------------------------------------------------
// model dmod diode ( ... )                      // params per diode.va
// d1   (anode cathode) dmod area=1

// ---- Linear controlled sources (builtins) ----------------------------------
// Node order shown is Spectre-style (out+ out- ctrl+ ctrl-) -- VERIFY against a
// VACASK demo (e.g. demo/gilbert) before relying on it:
// e1   (o+ o- c+ c-)  vcvs gain=2.0             // V-controlled V  (V/V)
// g1   (o+ o- c+ c-)  vccs gain=1m              // V-controlled I  (A/V)
// h1   (o+ o-)        ccvs ...                  // I-controlled V  (senses a branch)
// f1   (o+ o-)        cccs ...                  // I-controlled I  (senses a branch)

// ---- Mutual coupling of two inductors (builtin "inductive coupling") --------
// Exact keyword/params NOT confirmed -- check the LC-resonator demo. Sketch:
// k1   mutual ind1=l1a ind2=l2a coupling=0.3

// ---- Instantiating another subckt ------------------------------------------
// x1   (a b)        cheat_sheet l1=4n c1=1.5p        // override defaults inline
// ============================================================================
