"""snp2le entry point.

    snp2le                 launch the graphical interface (default)
    snp2le -b <command>    batch (command-line) mode

Batch mode forwards everything after -b to the command-line parser, for example:

    snp2le -b convert design.s2p --mode structure --structure inductor-pi
    snp2le -b list-structures
    snp2le -b -h           (full command-line help)
"""
from __future__ import annotations
import sys

_USAGE = (
    "snp2le - S-parameter to lumped-element netlist converter\n\n"
    "  snp2le                 launch the graphical interface\n"
    "  snp2le -b <command>    batch (command-line) mode, for example:\n"
    "      snp2le -b convert design.s2p --mode structure --structure inductor-pi\n"
    "      snp2le -b list-structures\n"
    "      snp2le -b -h        full command-line help\n"
)


def main(argv=None):
    """Dispatch: no arguments opens the GUI, -b / --batch runs the command line."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-b", "--batch"):
        from snp2le import cli
        return cli.main(argv[1:])
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(_USAGE)
        return 0
    if argv and argv[0] in ("-V", "--version"):
        from snp2le import __version__
        sys.stdout.write(f"snp2le {__version__}\n")
        return 0
    if argv:
        sys.stderr.write("snp2le: unrecognised arguments (use -b for command-line mode)\n\n")
        sys.stderr.write(_USAGE)
        return 2
    from snp2le import app                # no arguments: launch the GUI
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
