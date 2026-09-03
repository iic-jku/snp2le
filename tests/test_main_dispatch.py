# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_main_dispatch.py - the snp2le entry point's argument dispatch, without Qt.

`snp2le` opens the GUI, `snp2le <file.sNp>` opens it on that file (the hand-over a tool
such as setupEM needs after writing an EM result), and `-b` runs the command line.  The
GUI and CLI modules are replaced by recording stubs, so this needs no display and runs
no fit.  Run with: pytest -q
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import snp2le
from snp2le import __main__ as entry


@pytest.fixture()
def calls(monkeypatch):
    """Stub `snp2le.app` and `snp2le.cli`, recording what `main` hands them.

    `from snp2le import app` resolves the package attribute first and the submodule in
    sys.modules second, so both are replaced."""
    seen = {"app": [], "cli": []}
    app = types.SimpleNamespace(main=lambda *args: seen["app"].append(args) or 0)
    cli = types.SimpleNamespace(main=lambda argv: seen["cli"].append(list(argv)) or 0)
    for name, stub in (("app", app), ("cli", cli)):
        monkeypatch.setitem(sys.modules, f"snp2le.{name}", stub)
        monkeypatch.setattr(snp2le, name, stub, raising=False)
    return seen


def test_no_arguments_opens_the_gui(calls):
    assert entry.main([]) == 0
    assert calls["app"] == [()]
    assert calls["cli"] == []


def test_one_file_opens_the_gui_on_it(calls):
    assert entry.main(["result_deembedded.s4p"]) == 0
    assert calls["app"] == [("result_deembedded.s4p",)]
    assert calls["cli"] == []


def test_batch_forwards_to_the_cli(calls):
    assert entry.main(["-b", "convert", "a.s2p", "--order", "8"]) == 0
    assert calls["cli"] == [["convert", "a.s2p", "--order", "8"]]
    assert calls["app"] == []


def test_two_files_are_refused(calls, capsys):
    assert entry.main(["a.s2p", "b.s2p"]) == 2
    assert calls["app"] == [] and calls["cli"] == []
    err = capsys.readouterr().err
    assert "expected one Touchstone file, got 2" in err
    assert "snp2le <file.sNp>" in err               # the usage follows the reason


@pytest.mark.parametrize("argv", [["--nope"], ["a.s2p", "--nope"], ["--nope", "a.s2p"]])
def test_unknown_flags_are_refused(calls, capsys, argv):
    assert entry.main(argv) == 2
    assert calls["app"] == [] and calls["cli"] == []
    assert "unrecognised arguments" in capsys.readouterr().err


def test_help_names_the_file_form(calls, capsys):
    assert entry.main(["-h"]) == 0
    out = capsys.readouterr().out
    assert "snp2le <file.sNp>" in out
    assert "snp2le -b <command>" in out
    assert calls["app"] == [] and calls["cli"] == []


def test_version(calls, capsys):
    assert entry.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"snp2le {snp2le.__version__}"
