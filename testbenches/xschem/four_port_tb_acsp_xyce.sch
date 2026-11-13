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
T {Xyce Testbench for AC S-parameter analysis - Four-Port} 870 -2390 0 0 1 1 {}
N 1800 -2100 1800 -2060 {lab=v3}
N 1720 -2100 1800 -2100 {lab=v3}
N 1800 -2000 1800 -1960 {lab=GND}
N 1800 -2100 1840 -2100 {lab=v3}
N 2000 -2000 2000 -1960 {lab=GND}
N 2000 -2180 2040 -2180 {lab=v4}
N 2000 -2180 2000 -2060 {lab=v4}
N 1720 -2180 2000 -2180 {lab=v4}
N 1440 -2100 1520 -2100 {lab=v2}
N 1440 -2000 1440 -1960 {lab=GND}
N 1440 -2100 1440 -2060 {lab=v2}
N 1400 -2100 1440 -2100 {lab=v2}
N 1240 -2000 1240 -1960 {lab=GND}
N 1200 -2180 1240 -2180 {lab=v1}
N 1240 -2180 1240 -2060 {lab=v1}
N 1240 -2180 1520 -2180 {lab=v1}
C {devices/code_shown.sym} 80 -2130 0 0 {name=XYCE
only_toplevel=true
lock=false
value="
.include ../../../netlist/xyce/four_port.cir
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
.LIN SPARCALC=1 FORMAT=TOUCHSTONE2 DATAFORMAT=RI FILE=../plot_simulations/data/@schname\\\\.s4p
"}
C {title-2.sym} 0 0 0 0 {name=l2 author="Simon Dorrer" rev=1.0 lock=true}
C {lab_pin.sym} 1840 -2100 0 1 {name=p3 sig_type=std_logic lab=v3}
C {devices/lab_pin.sym} 1400 -2100 0 0 {name=l19 sig_type=std_logic lab=v2
}
C {devices/gnd.sym} 1440 -1960 0 0 {name=l39 lab=GND}
C {devices/vsource.sym} 1440 -2030 0 1 {name=P2 value="port=2 z0=50"
}
C {devices/gnd.sym} 1800 -1960 0 0 {name=l3 lab=GND}
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
C {devices/vsource.sym} 1800 -2030 0 0 {name=P3 value="port=3 z0=50"
}
C {lab_pin.sym} 2040 -2180 0 1 {name=p1 sig_type=std_logic lab=v4}
C {devices/gnd.sym} 2000 -1960 0 0 {name=l1 lab=GND}
C {devices/vsource.sym} 2000 -2030 0 0 {name=P4 value="port=4 z0=50"
}
C {four_port.sym} 1620 -2140 0 0 {name=x1}
C {lab_pin.sym} 1200 -2180 0 0 {name=p2 sig_type=std_logic lab=v1}
C {devices/gnd.sym} 1240 -1960 0 1 {name=l4 lab=GND}
C {devices/vsource.sym} 1240 -2030 0 1 {name=P1 value="port=1 z0=50"
}
