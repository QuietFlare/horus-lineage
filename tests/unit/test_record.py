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
Tests for the projections, which need no run to exercise.
"""

from pathlib import Path
from typing import Any

from horus_builtin.artifact.file import FileArtifact

from horus_lineage.record import labels_of


class Unlabelled:
    """
    An artifact from an engine predating ``BaseArtifact.labels``.
    """

    id = "measurements"
    path = Path("/data/x.csv")


class TestLabelsOf:
    """
    Domain metadata, read defensively.

    A recorder that raised on an older engine would fail the run it is
    supposed to observe, so every shape short of a string mapping reads
    as "no labels".
    """

    def test_an_engine_without_the_field_reports_none(self) -> None:
        """
        The field arrived upstream after this recorder did.
        """
        assert labels_of(Unlabelled()) == {}  # type: ignore[arg-type]

    def test_an_unlabelled_artifact_reports_none(self) -> None:
        """
        The common case, and it must not add an empty key to records.
        """
        artifact = FileArtifact(id="measurements", path=Path("/data/x.csv"))
        assert labels_of(artifact) == {}

    def test_string_labels_survive(self) -> None:
        """
        What a reader groups on.
        """
        artifact = FileArtifact(id="scored", path=Path("/data/x.parquet"))
        labels = {"subject": "batch_017", "role": "measurement"}
        object.__setattr__(artifact, "labels", dict(labels))
        assert labels_of(artifact) == labels

    def test_values_a_reader_cannot_compare_are_dropped(self) -> None:
        """
        Labels are index keys. A value that is not a string is worse than
        an absent one, because it looks groupable and is not.
        """
        artifact = FileArtifact(id="scored", path=Path("/data/x.parquet"))
        mixed: dict[Any, Any] = {"subject": "batch_017", "replicate": 3}
        object.__setattr__(artifact, "labels", mixed)
        assert labels_of(artifact) == {"subject": "batch_017"}

    def test_something_that_is_not_a_mapping_reports_none(self) -> None:
        """
        A plugin could put anything there. Refuse rather than guess.
        """
        artifact = FileArtifact(id="scored", path=Path("/data/x.parquet"))
        object.__setattr__(artifact, "labels", ["subject=batch_017"])
        assert labels_of(artifact) == {}
