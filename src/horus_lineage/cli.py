#
# horus-lineage
# Copyright (C) 2026 QuietFlare
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""
The ``horus-lineage`` command.

Recording needs no command: the plugin registers itself and runs. This
exists for the things you do with a run directory afterwards.
"""

import sys

COMMANDS = {
    "report": ("horus_lineage.report", "render one run directory as HTML"),
}


def usage() -> str:
    """What the bare command prints."""
    width = max(len(name) for name in COMMANDS)
    lines = ["usage: horus-lineage <command> [options]", "", "commands:"]
    lines += [
        f"  {name.ljust(width)}  {help_}"
        for name, (_, help_) in COMMANDS.items()
    ]
    lines += [
        "",
        "Recording itself needs no command: install the package and "
        "Horus loads it.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Route to a subcommand, importing it only once chosen."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(usage())
        return 0
    if argv[0] not in COMMANDS:
        print(f"horus-lineage: unknown command {argv[0]!r}\n\n{usage()}")
        return 2

    import importlib

    module = importlib.import_module(COMMANDS[argv[0]][0])
    return int(module.main(argv[1:]) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
