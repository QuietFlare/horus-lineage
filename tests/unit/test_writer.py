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
Tests for writing records to disk.
"""

import json
from datetime import datetime
from pathlib import Path

from horus_lineage.writer import (
    RunWriter,
    canonical,
    digest_of,
    now,
    safe_name,
)


class TestCanonicalForm:
    """
    The form digests are taken over.
    """

    def test_key_order_does_not_change_the_digest(self) -> None:
        """
        Two dicts with the same content digest the same.
        """
        assert digest_of({"a": 1, "b": 2}) == digest_of({"b": 2, "a": 1})

    def test_different_content_digests_differently(self) -> None:
        """
        A changed value changes the digest.
        """
        assert digest_of({"a": 1}) != digest_of({"a": 2})

    def test_canonical_form_is_compact(self) -> None:
        """
        No incidental whitespace, so the bytes are stable.
        """
        assert canonical({"a": 1, "b": 2}) == b'{"a":1,"b":2}'


class TestSafeName:
    """
    Task ids are author strings and must not escape the directory.
    """

    def test_a_plain_id_stays_readable(self) -> None:
        """
        The common case is still recognisable on disk.
        """
        assert safe_name("prep").startswith("prep.")

    def test_separators_cannot_escape(self) -> None:
        """
        A traversal attempt becomes an ordinary filename.
        """
        name = safe_name("../../etc/passwd")
        assert "/" not in name
        assert ".." not in name.removesuffix(".json").split(".")[0]

    def test_map_clone_brackets_survive(self) -> None:
        """
        Clone ids differ from each other after sanitizing.
        """
        assert safe_name("score[00]") != safe_name("score[01]")

    def test_ids_differing_only_in_unsafe_characters_stay_distinct(
        self,
    ) -> None:
        """
        The digest suffix keeps two ids apart when sanitizing collides.
        """
        assert safe_name("a/b") != safe_name("a:b")

    def test_an_id_of_only_unsafe_characters_still_names_a_file(self) -> None:
        """
        An id that sanitizes to nothing readable is still a plain
        filename, not a hidden one and not a path.
        """
        name = safe_name("///")
        assert not name.startswith(".")
        assert "/" not in name


class TestRunWriter:
    """
    Writing a run's records.
    """

    def test_it_creates_its_directory(self, tmp_path: Path) -> None:
        """
        The caller does not have to make the directory first.
        """
        RunWriter(tmp_path / "deep" / "nested")
        assert (tmp_path / "deep" / "nested").is_dir()

    def test_a_record_round_trips(self, tmp_path: Path) -> None:
        """
        What goes in comes back out as JSON.
        """
        writer = RunWriter(tmp_path)
        path = writer.write("run.json", {"format": "horus-lineage/v1"})
        assert json.loads(path.read_text()) == {"format": "horus-lineage/v1"}

    def test_rewriting_replaces_rather_than_appends(
        self, tmp_path: Path
    ) -> None:
        """
        run.json is written twice, at start and at the end.
        """
        writer = RunWriter(tmp_path)
        writer.write("run.json", {"status": None})
        path = writer.write("run.json", {"status": "completed"})
        assert json.loads(path.read_text()) == {"status": "completed"}

    def test_no_temporary_files_are_left_behind(self, tmp_path: Path) -> None:
        """
        A reader listing the directory sees only finished records.
        """
        writer = RunWriter(tmp_path)
        writer.write("run.json", {"a": 1})
        assert [p.name for p in tmp_path.iterdir()] == ["run.json"]

    def test_raw_bytes_are_copied_untouched(self, tmp_path: Path) -> None:
        """
        The workflow source is a copy, not a re-serialization.
        """
        writer = RunWriter(tmp_path)
        path = writer.write_bytes("workflow.yaml", b"kind: horus_workflow\n")
        assert path.read_bytes() == b"kind: horus_workflow\n"

    def test_a_task_record_is_named_from_its_id(self, tmp_path: Path) -> None:
        """
        Records are findable by the task they describe.
        """
        writer = RunWriter(tmp_path)
        path = writer.write_task("prep", {"task": {"id": "prep"}})
        assert path.name.startswith("prep.")


class TestTimestamps:
    """
    Times recorded in run.json and every task record.
    """

    def test_the_timestamp_carries_a_timezone(self) -> None:
        """
        A naive timestamp cannot be compared across machines.
        """
        assert datetime.fromisoformat(now()).tzinfo is not None
