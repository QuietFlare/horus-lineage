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
Tests for where records go and how much work goes into them.
"""

from pathlib import Path

import pytest

from horus_lineage.config import (
    BESIDE_THE_RUN,
    DEFAULT_ROOT,
    ENV_COMMAND,
    ENV_DIGESTS,
    ENV_MERGE,
    ENV_ROOT,
    LineageConfig,
)


class TestRoot:
    """
    Choosing the destination directory.
    """

    def test_it_defaults_to_the_launch_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Zero setup has to work, so an unset variable is not an error.
        """
        monkeypatch.delenv(ENV_ROOT, raising=False)
        assert LineageConfig.from_env().root == DEFAULT_ROOT

    def test_an_explicit_path_is_used_as_given(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        Pointing several hosts at one filesystem is a supported choice.
        """
        monkeypatch.setenv(ENV_ROOT, str(tmp_path))
        config = LineageConfig.from_env()
        assert config.resolve_root(Path("/somewhere/else")) == tmp_path

    def test_beside_the_run_follows_the_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Lineage travels with the results it describes.
        """
        monkeypatch.setenv(ENV_ROOT, BESIDE_THE_RUN)
        config = LineageConfig.from_env()
        assert config.root is None
        assert config.resolve_root(Path("/work/run")) == Path(
            "/work/run/.horus-lineage"
        )

    def test_an_empty_value_falls_back_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        An exported but empty variable is not a request for the CWD.
        """
        monkeypatch.setenv(ENV_ROOT, "   ")
        assert LineageConfig.from_env().root == DEFAULT_ROOT


class TestDigests:
    """
    The one switch ADR 0003 promises.
    """

    def test_digests_are_on_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Records without digests have no edges, so on is the default.
        """
        monkeypatch.delenv(ENV_DIGESTS, raising=False)
        assert LineageConfig.from_env().digests is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
    def test_it_can_be_switched_off(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """
        Cost-sensitive runs turn hashing off however they spell it.
        """
        monkeypatch.setenv(ENV_DIGESTS, value)
        assert LineageConfig.from_env().digests is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "anything"])
    def test_anything_else_leaves_it_on(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """
        A typo must not silently disable recording.
        """
        monkeypatch.setenv(ENV_DIGESTS, value)
        assert LineageConfig.from_env().digests is True


class TestMerge:
    """
    Folding a run's task records into one file.
    """

    def test_it_is_off_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        One file per task is the crash-safe layout, so it stays the norm.
        """
        monkeypatch.delenv(ENV_MERGE, raising=False)
        assert LineageConfig.from_env().merge is False

    def test_it_can_be_switched_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A few hundred tasks is where one file starts to be worth it.
        """
        monkeypatch.setenv(ENV_MERGE, "1")
        assert LineageConfig.from_env().merge is True


class TestCommand:
    """
    Leaving the resolved command out of records.
    """

    def test_it_is_recorded_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The command is the most useful line in a record.
        """
        monkeypatch.delenv(ENV_COMMAND, raising=False)
        assert LineageConfig.from_env().command is True

    def test_it_can_be_switched_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        For a workflow that passes a secret as an argument.
        """
        monkeypatch.setenv(ENV_COMMAND, "0")
        assert LineageConfig.from_env().command is False
