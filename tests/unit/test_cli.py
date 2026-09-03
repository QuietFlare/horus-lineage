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
Tests for the command, and the flag that gates the report.
"""

import pytest

from horus_lineage import cli
from horus_lineage.config import ENV_REPORT

USAGE_ERROR = 2
"""The exit code for a refused command."""


class TestReportFlag:
    """
    The HTML report is optional and off until asked for.
    """

    def test_report_is_off_by_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        A clear message and a non-zero exit, nothing rendered.
        """
        monkeypatch.delenv(ENV_REPORT, raising=False)
        assert cli.main(["report", "somewhere"]) == USAGE_ERROR
        assert ENV_REPORT in capsys.readouterr().out

    def test_usage_says_it_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Someone reading the help learns how to switch it on.
        """
        monkeypatch.delenv(ENV_REPORT, raising=False)
        assert f"set {ENV_REPORT}=1" in cli.usage()

    def test_the_flag_switches_it_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Once on, the subcommand is reached and parses its own arguments.
        """
        monkeypatch.setenv(ENV_REPORT, "1")
        assert "off" not in cli.usage().split("report")[1].split("\n")[0]
        with pytest.raises(SystemExit):
            cli.main(["report"])

    def test_conformance_is_never_gated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        """
        The format check is part of the core, not the report.
        """
        monkeypatch.delenv(ENV_REPORT, raising=False)
        assert cli.main(["conformance", str(tmp_path)]) == 1


class TestRouting:
    """
    The bare command and unknown commands.
    """

    def test_no_arguments_prints_usage(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Help, exit 0."""
        assert cli.main([]) == 0
        assert "usage:" in capsys.readouterr().out

    def test_an_unknown_command_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 2 with the usage attached."""
        assert cli.main(["frobnicate"]) == USAGE_ERROR
        assert "unknown command" in capsys.readouterr().out
