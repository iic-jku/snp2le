"""test_xschem.py - sim_data_dir resolution (no Qt, no xschem needed). Run with: pytest -q

The result folder is the testbench's choice, so sim_data_dir must read it from the
testbench itself: the Ngspice `wrdata` target (from the .sch or the generated netlist),
the VACASK log's `postprocess: wrote` line, and only fall back to the bundled layout
(`sim_data/` next to the testbench) when neither says anything.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snp2le.core.xschem import sim_data_dir


def _make_sch(tmp_path, body, name="tb_ngspice.sch"):
    d = tmp_path / "testbenches" / "xschem"
    d.mkdir(parents=True, exist_ok=True)
    sch = d / name
    sch.write_text(body, encoding="utf-8")
    return sch


def test_ngspice_wrdata_bundled_layout(tmp_path):
    """The bundled testbenches' wrdata target resolves to sim_data next to the .sch."""
    sch = _make_sch(tmp_path, "value=\"\nwrdata ../sim_data/@schname\\\\\\\\.txt\n\"")
    assert sim_data_dir(str(sch), "ngspice") == str(
        tmp_path / "testbenches" / "xschem" / "sim_data")


def test_ngspice_wrdata_custom_folder(tmp_path):
    """A testbench writing somewhere else is followed there."""
    sch = _make_sch(tmp_path, "wrdata ../my_results/@schname.txt\n")
    assert sim_data_dir(str(sch), "ngspice") == str(
        tmp_path / "testbenches" / "xschem" / "my_results")


def test_ngspice_wrdata_from_generated_netlist(tmp_path):
    """No wrdata in the .sch: the generated netlist is the secondary source."""
    sch = _make_sch(tmp_path, "no control block here\n")
    sim = sch.parent / "simulations"
    sim.mkdir()
    (sim / "tb_ngspice.spice").write_text("wrdata out/tb_ngspice.txt\n", encoding="utf-8")
    assert sim_data_dir(str(sch), "ngspice") == str(sim / "out")


def test_vacask_folder_from_log(tmp_path):
    """The VACASK log's last 'postprocess: wrote' line names the exact file."""
    sch = _make_sch(tmp_path, "", name="tb_vacask.sch")
    sim = sch.parent / "simulations"
    sim.mkdir()
    (sim / "vacask.log").write_text(
        "Analysis 'acsp' completed.\n"
        "postprocess: wrote /somewhere/old/tb_vacask.txt\n"
        "postprocess: wrote /somewhere/new/tb_vacask.txt\n", encoding="utf-8")
    assert sim_data_dir(str(sch), "vacask") == "/somewhere/new"


def test_fallback_bundled_layout(tmp_path):
    """Nothing to read: fall back to sim_data next to the testbench."""
    sch = _make_sch(tmp_path, "no wrdata anywhere\n")
    expect = str(tmp_path / "testbenches" / "xschem" / "sim_data")
    assert sim_data_dir(str(sch), "ngspice") == expect
    assert sim_data_dir(str(sch), "vacask") == expect
