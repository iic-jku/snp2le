v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
T {SPDX-FileCopyrightText: 2026 Simon Dorrer
SPDX-License-Identifier: Apache-2.0
} 1820 -140 0 0 0.4 0.4 {}
T {Xyce Testbench for AC S-parameter analysis - Two-Port} 480 -1720 0 0 1 1 {}
N 1000 -1240 1000 -1180 {lab=v1}
N 1000 -1120 1000 -1060 {lab=GND}
N 920 -1240 1000 -1240 {lab=v1}
N 1280 -1240 1360 -1240 {lab=v2}
N 1360 -1120 1360 -1060 {lab=GND}
N 1360 -1240 1360 -1180 {lab=v2}
N 1360 -1240 1440 -1240 {lab=v2}
N 1000 -1240 1080 -1240 {lab=v1}
C {devices/code_shown.sym} 40 -1330 0 0 {name=XYCE
only_toplevel=true
lock=false
value="
.include ../../../netlist/xyce/two_port.cir
.include ../sim_range.cir

* User Constants
* f_min / f_max come from ../sim_range.cir (.param),
* auto-synced by snp2le to the band it fitted.
* edit that file for a standalone run.

* Xschem's ground symbol netlists node GND, which Xyce takes as ground only with this.
.PREPROCESS REPLACEGROUND TRUE

* AC S-Parameter Analysis
* Xyce writes S-parameters only as a Touchstone file, which snp2le imports.
.AC LIN 1001 \{f_min\} \{f_max\}
.LIN SPARCALC=1 FORMAT=TOUCHSTONE2 DATAFORMAT=RI FILE=../plot_simulations/data/@schname\\\\.s2p
"}
C {title-3.sym} 0 0 0 0 {name=l2 author="Simon Dorrer" rev=1.0 lock=true}
C {lab_pin.sym} 1440 -1240 0 1 {name=p3 sig_type=std_logic lab=v2}
C {devices/lab_pin.sym} 920 -1240 0 0 {name=l19 sig_type=std_logic lab=v1
}
C {devices/gnd.sym} 1000 -1060 0 0 {name=l39 lab=GND}
C {devices/vsource.sym} 1000 -1150 0 1 {name=P1 value="port=1 z0=50"
}
C {devices/gnd.sym} 1360 -1060 0 0 {name=l3 lab=GND}
C {devices/launcher.sym} 1740 -1180 0 0 {name=h2
descr="Simulate Xyce"
tclcommand="
# Setup the default simulation commands if not already set up
# for example by already launched simulations.
set_sim_defaults

# change the simulator to be used (#3 in spice category is Xyce batch)
set sim(spice,default) 3
xschem set netlist_type spice

# run netlist and simulation
xschem netlist
simulate
"}
C {devices/vsource.sym} 1360 -1150 0 0 {name=P2 value="port=2 z0=50"
}
C {two_port.sym} 1180 -1240 0 0 {name=x1
}
