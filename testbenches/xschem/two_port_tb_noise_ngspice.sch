v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
B 2 1660 -760 2460 -360 {flags=graph
y1=-2.6
y2=-2.5
ypos1=0
ypos2=2
divy=5
subdivy=8
unity=1
x1=1.2e+11
x2=2e+11
divx=5
subdivx=4
xlabmag=1.0
ylabmag=1.0
node="\\"Output Noise; onoise_spectrum\\""
color=4
dataset=-1
unitx=1
logx=0
logy=1
linewidth_mult=4}
B 2 1660 -1180 2460 -780 {flags=graph
y1=-1.9
y2=-0.32
ypos1=0
ypos2=2
divy=5
subdivy=8
unity=1
x1=1.2e+11
x2=2e+11
divx=5
subdivx=4
xlabmag=1.0
ylabmag=1.0
node="\\"Input Noise; inoise_spectrum\\""
color=4
dataset=-1
unitx=1
logx=0
logy=1
linewidth_mult=4}
T {Ngspice Testbench for Noise analysis - Bandpass Filter} 590 -1720 0 0 1 1 {}
N 940 -980 940 -920 {lab=vin}
N 940 -860 940 -800 {lab=GND}
N 860 -980 940 -980 {lab=vin}
N 1220 -980 1300 -980 {lab=vout}
N 1300 -860 1300 -800 {lab=GND}
N 1300 -980 1300 -920 {lab=vout}
N 1300 -980 1380 -980 {lab=vout}
N 940 -980 1020 -980 {lab=vin}
C {devices/code_shown.sym} 60 -1310 0 0 {name=NGSPICE
only_toplevel=true
lock=false
value="
.include ../../../netlist/spice/bpf_le.spice
.param temp=27
.options savecurrents method=gear reltol=1e-3 abstol=1e-15 gmin=1e-15
.control

save all

set wr_vecnames
set wr_singlescale
set enable_noisy_r

* User Constants
let f_min = 120.0e9
let f_max = 200.0e9

* Operating Point Analysis
op
remzerovec
write @schname\\\\.raw
set appendwrite

* Noise Analysis
noise v(vout) vin lin 1001 $&const.f_min $&const.f_max 1

* Plotting
setplot noise1
plot inoise_spectrum ylog ylabel 'Input Noise'
plot onoise_spectrum ylog ylabel 'Output Noise'
write @schname\\\\.raw
set appendwrite

* Write Data
unset appendwrite
set wr_vecnames
set wr_singlescale
wrdata ../../../sim_data/@schname\\\\.txt v(inoise_spectrum) v(onoise_spectrum)

* Measurements
setplot noise2
print inoise_total
print onoise_total

*quit
.endc
"}
C {title-3.sym} 0 0 0 0 {name=l2 author="Simon Dorrer" rev=1.0 lock=true}
C {lab_pin.sym} 1380 -980 0 1 {name=p3 sig_type=std_logic lab=vout}
C {devices/lab_pin.sym} 860 -980 0 0 {name=l19 sig_type=std_logic lab=vin
}
C {devices/gnd.sym} 940 -800 0 0 {name=l39 lab=GND}
C {devices/gnd.sym} 1300 -800 0 0 {name=l3 lab=GND}
C {devices/launcher.sym} 1710 -1340 0 0 {name=h2
descr="Simulate" 
tclcommand="xschem save; xschem netlist; xschem simulate"
}
C {devices/launcher.sym} 1710 -1220 0 0 {name=h1
descr="Load waves" 
tclcommand="xschem raw_read $netlist_dir/[file rootname [file tail [xschem get current_name]]].raw noise"
}
C {devices/launcher.sym} 1710 -1280 0 0 {name=h3
descr="Annotate OP" 
tclcommand="set show_hidden_texts 1; xschem annotate_op"
}
C {devices/code_shown.sym} 1970 -1330 0 0 {name=MODEL only_toplevel=true
format="tcleval( @value )"
value="
.lib cornerMOSlv.lib mos_tt
.lib cornerMOShv.lib mos_tt
.lib cornerHBT.lib hbt_typ
.lib cornerRES.lib res_typ
.lib cornerCAP.lib cap_typ
.lib cornerDIO.lib dio_tt
"}
C {two_port.sym} 1120 -980 0 0 {name=x1}
C {devices/vsource.sym} 940 -890 0 1 {name=vin value="dc 0 ac 1"
}
C {res.sym} 1300 -890 0 0 {name=R1
value=50
footprint=1206
device=resistor
m=1}
