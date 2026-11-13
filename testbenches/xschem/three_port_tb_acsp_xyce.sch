v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
T {SPDX-FileCopyrightText: 2026 Simon Dorrer
SPDX-License-Identifier: Apache-2.0
} 2750 -140 0 0 0.4 0.4 {}
T {Xyce Testbench for AC S-parameter analysis - Three-Port} 870 -2330 0 0 1 1 {}
N 1420 -1540 1420 -1480 {lab=v1}
N 1420 -1420 1420 -1360 {lab=GND}
N 1340 -1540 1420 -1540 {lab=v1}
N 1420 -1540 1500 -1540 {lab=v1}
N 1780 -1500 1780 -1460 {lab=v2}
N 1700 -1500 1780 -1500 {lab=v2}
N 1780 -1400 1780 -1360 {lab=GND}
N 1780 -1500 1820 -1500 {lab=v2}
N 1980 -1400 1980 -1360 {lab=GND}
N 1980 -1580 2020 -1580 {lab=v3}
N 1980 -1580 1980 -1460 {lab=v3}
N 1700 -1580 1980 -1580 {lab=v3}
C {devices/code_shown.sym} 80 -2250 0 0 {name=XYCE
only_toplevel=true
lock=false
value="
.include ../../../netlist/xyce/three_port.cir
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
.LIN SPARCALC=1 FORMAT=TOUCHSTONE2 DATAFORMAT=RI FILE=../plot_simulations/data/@schname\\\\.s3p
"}
C {title-2.sym} 0 0 0 0 {name=l2 author="Simon Dorrer" rev=1.0 lock=true}
C {lab_pin.sym} 1820 -1500 0 1 {name=p3 sig_type=std_logic lab=v2}
C {devices/lab_pin.sym} 1340 -1540 0 0 {name=l19 sig_type=std_logic lab=v1
}
C {devices/gnd.sym} 1420 -1360 0 0 {name=l39 lab=GND}
C {devices/vsource.sym} 1420 -1450 0 1 {name=P1 value="port=1 z0=50"
}
C {devices/gnd.sym} 1780 -1360 0 0 {name=l3 lab=GND}
C {devices/launcher.sym} 2600 -2120 0 0 {name=h2
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
C {devices/vsource.sym} 1780 -1430 0 0 {name=P2 value="port=2 z0=50"
}
C {three_port.sym} 1600 -1540 0 0 {name=x1}
C {lab_pin.sym} 2020 -1580 0 1 {name=p1 sig_type=std_logic lab=v3}
C {devices/gnd.sym} 1980 -1360 0 0 {name=l1 lab=GND}
C {devices/vsource.sym} 1980 -1430 0 0 {name=P3 value="port=3 z0=50"
}
