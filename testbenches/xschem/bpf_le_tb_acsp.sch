v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
B 2 1660 -760 2460 -360 {flags=graph
y1=-180
y2=180
ypos1=0
ypos2=2
divy=5
subdivy=1
unity=1
x1=7.4313638
x2=7.4627606
divx=5
subdivx=8
xlabmag=1.0
ylabmag=1.0
node="\\"S21; s21\\"
\\"S12; s12\\""
color="4 7"
dataset=-1
unitx=1
logx=1
logy=0
linewidth_mult=4}
B 2 1660 -1180 2460 -780 {flags=graph
y1=-69.222222
y2=-53.222222
ypos1=0
ypos2=2
divy=5
subdivy=4
unity=1
x1=7.4313638
x2=7.4627606
divx=5
subdivx=8
xlabmag=1.0
ylabmag=1.0
node="\\"S11; s11\\"
\\"S22; s22\\""
color="4 7"
dataset=-1
unitx=1
logx=1
logy=0
linewidth_mult=4}
T {Testbench for AC S-parameter analysis - Bandpass Filter} 480 -1720 0 0 1 1 {}
N 1000 -920 1000 -860 {lab=vin}
N 1000 -800 1000 -740 {lab=GND}
N 920 -920 1000 -920 {lab=vin}
N 1280 -920 1360 -920 {lab=vout}
N 1360 -800 1360 -740 {lab=GND}
N 1360 -920 1360 -860 {lab=vout}
N 1360 -920 1440 -920 {lab=vout}
N 1000 -920 1080 -920 {lab=vin}
C {devices/code_shown.sym} 120 -1330 0 0 {name=NGSPICE
only_toplevel=true
lock=true
value="
.include ../../../netlist/bpf_le.spice
.param temp=27
.options savecurrents klu method=gear reltol=1e-3 abstol=1e-15 gmin=1e-15
.control

save all

set wr_vecnames
set wr_singlescale

* User Constants
let f_min = 120.0e9
let f_max = 200.0e9
let f0 = 160.0e9

* Operating Point Analysis
op
remzerovec
write @schname\\\\.raw
set appendwrite

* AC S-Parameter Analysis
sp dec 1001 $&const.f_min $&const.f_max
let s11 = db(S_1_1)
let s21 = db(S_2_1)
let s12 = db(S_1_2)
let s22 = db(S_2_2)
remzerovec
write @schname\\\\.raw
set appendwrite

* Plotting
plot s11 s22
plot s21 s12

quit
.endc
"}
C {title-3.sym} 0 0 0 0 {name=l2 author="Simon Dorrer" rev=1.0 lock=true}
C {lab_pin.sym} 1440 -920 0 1 {name=p3 sig_type=std_logic lab=vout}
C {devices/lab_pin.sym} 920 -920 0 0 {name=l19 sig_type=std_logic lab=vin
}
C {devices/gnd.sym} 1000 -740 0 0 {name=l39 lab=GND}
C {devices/vsource.sym} 1000 -830 0 1 {name=v1 value="dc 0 ac 1 portnum 1 z0 50"
}
C {devices/gnd.sym} 1360 -740 0 0 {name=l3 lab=GND}
C {devices/launcher.sym} 1720 -1340 0 0 {name=h2
descr="Simulate" 
tclcommand="xschem save; xschem netlist; xschem simulate"
}
C {devices/launcher.sym} 1720 -1220 0 0 {name=h1
descr="Load waves" 
tclcommand="xschem raw_read $netlist_dir/[file rootname [file tail [xschem get current_name]]].raw ac"
}
C {devices/launcher.sym} 1720 -1280 0 0 {name=h3
descr="Annotate OP" 
tclcommand="set show_hidden_texts 1; xschem annotate_op"
}
C {devices/code_shown.sym} 1980 -1330 0 0 {name=MODEL only_toplevel=true
format="tcleval( @value )"
value="
.lib cornerMOSlv.lib mos_tt
.lib cornerMOShv.lib mos_tt
.lib cornerHBT.lib hbt_typ
.lib cornerRES.lib res_typ
.lib cornerCAP.lib cap_typ
.lib cornerDIO.lib dio_tt
"}
C {devices/vsource.sym} 1360 -830 0 0 {name=v2 value="dc 0 ac 1 portnum 2 z0 50"
}
C {bpf_le.sym} 1180 -920 0 0 {name=x1}
