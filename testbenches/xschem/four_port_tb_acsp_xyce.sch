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
T {Xyce Testbench for AC S-parameter analysis - Four-Port} 530 -1710 0 0 1 1 {}
N 1440 -620 1440 -580 {lab=v3}
N 1360 -620 1440 -620 {lab=v3}
N 1440 -520 1440 -480 {lab=GND}
N 1440 -620 1480 -620 {lab=v3}
N 1640 -520 1640 -480 {lab=GND}
N 1640 -700 1680 -700 {lab=v4}
N 1640 -700 1640 -580 {lab=v4}
N 1360 -700 1640 -700 {lab=v4}
N 1080 -620 1160 -620 {lab=v2}
N 1080 -520 1080 -480 {lab=GND}
N 1080 -620 1080 -580 {lab=v2}
N 1040 -620 1080 -620 {lab=v2}
N 880 -520 880 -480 {lab=GND}
N 840 -700 880 -700 {lab=v1}
N 880 -700 880 -580 {lab=v1}
N 880 -700 1160 -700 {lab=v1}
C {devices/code_shown.sym} 180 -1370 0 0 {name=XYCE
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
C {title-3.sym} 0 0 0 0 {name=l2 author="Simon Dorrer" rev=1.0 lock=true}
C {lab_pin.sym} 1480 -620 0 1 {name=p3 sig_type=std_logic lab=v3}
C {devices/lab_pin.sym} 1040 -620 0 0 {name=l19 sig_type=std_logic lab=v2
}
C {devices/gnd.sym} 1080 -480 0 0 {name=l39 lab=GND}
C {devices/vsource.sym} 1080 -550 0 1 {name=P2 value="port=2 z0=50"
}
C {devices/gnd.sym} 1440 -480 0 0 {name=l3 lab=GND}
C {devices/launcher.sym} 1860 -1380 0 0 {name=h2
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
C {devices/vsource.sym} 1440 -550 0 0 {name=P3 value="port=3 z0=50"
}
C {lab_pin.sym} 1680 -700 0 1 {name=p1 sig_type=std_logic lab=v4}
C {devices/gnd.sym} 1640 -480 0 0 {name=l1 lab=GND}
C {devices/vsource.sym} 1640 -550 0 0 {name=P4 value="port=4 z0=50"
}
C {four_port.sym} 1260 -660 0 0 {name=x1}
C {lab_pin.sym} 840 -700 0 0 {name=p2 sig_type=std_logic lab=v1}
C {devices/gnd.sym} 880 -480 0 1 {name=l4 lab=GND}
C {devices/vsource.sym} 880 -550 0 1 {name=P1 value="port=1 z0=50"
}
