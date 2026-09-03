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
The conformance suite, tested against the thing it is meant to catch.

A checker is only worth its false negatives, so most of what follows
breaks a conforming record in one specific way and asserts that the
break is reported. A suite that only ever passes proves nothing.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from horus_lineage import conformance

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
DEFINITION_DIGEST = "c" * 64

PLAN: dict[str, Any] = {
    "format": "horus-lineage/v1",
    "run": "9c1f4a70e2b84d15",
    "run_scope": None,
    "run_directory": "/work/experiments",
    "workflow": {"id": "3f2a1c88", "slug": "probe", "name": "Probe"},
    "started_at": "2026-09-01T14:20:02+00:00",
    "finished_at": "2026-09-01T15:41:17+00:00",
    "status": "completed",
    "definition": {"file": "definition.json", "sha256": DEFINITION_DIGEST},
    "source": {"file": "workflow.yaml", "sha256": OTHER_DIGEST},
    "code": [{"path": "scripts/prep.py", "size": 4312, "sha256": DIGEST}],
    "tasks": ["prep"],
}

RECORD: dict[str, Any] = {
    "format": "horus-lineage/v1",
    "run": "9c1f4a70e2b84d15",
    "execution": "7d40e6b2c1f34a09",
    "definition_sha256": DEFINITION_DIGEST,
    "recorded_at": "2026-09-01T14:22:31+00:00",
    "task": {
        "id": "prep",
        "definition_id": "prep",
        "kind": "horus_task",
        "name": "Prepare",
        "status": "completed",
        "skip_reason": None,
        "runs": 1,
    },
    "target": {"kind": "local", "location_id": "local://workstation-01"},
    "working_dir": "/scratch/prep/7d40e6b2",
    "command": "python prep.py --out prepared.json",
    "environment": {
        "executor": {"kind": "shell", "sha256": DIGEST},
        "runtime": {"kind": "python_script", "sha256": OTHER_DIGEST},
        "config_sha256": DIGEST,
    },
    "code": [
        {
            "path": "scripts/prep.py",
            "size": 4312,
            "sha256": DIGEST,
            "role": "script",
        }
    ],
    "inputs": [
        {
            "id": "raw",
            "path": "/data/raw.csv",
            "size": 21,
            "sha256": DIGEST,
            "labels": {"subject": "batch_017"},
        }
    ],
    "outputs": [
        {
            "id": "prepared",
            "path": "/work/prepared.json",
            "size": 101,
            "sha256": OTHER_DIGEST,
        }
    ],
    "incomplete": [],
}


def write(directory: Path, plan: Any = None, records: Any = None) -> Path:
    """A run directory on disk, conforming unless an argument says not."""
    (directory / "run.json").write_text(json.dumps(plan or PLAN))
    for name, record in (records or {"prep.abcd1234.json": RECORD}).items():
        (directory / name).write_text(json.dumps(record))
    return directory


def violations(directory: Path) -> list[str]:
    """The reported violations, as strings, for readable assertions."""
    return [str(v) for v in conformance.check_run(directory)]


class TestAConformingRun:
    """
    The baseline. Everything below breaks this in exactly one way.
    """

    def test_it_passes(self, tmp_path: Path) -> None:
        """
        A record built to ADR 0005 reports nothing.
        """
        assert conformance.check_run(write(tmp_path)) == []

    def test_the_merged_layout_also_passes(self, tmp_path: Path) -> None:
        """
        HORUS_LINEAGE_MERGE folds records into one file. Same contract.
        """
        (tmp_path / "run.json").write_text(json.dumps(PLAN))
        (tmp_path / "records.jsonl").write_text(json.dumps(RECORD) + "\n")
        assert conformance.check_run(tmp_path) == []


class TestTheVersionGate:
    """
    The check a reader makes before trusting any other field.
    """

    def test_an_unknown_version_is_refused(self, tmp_path: Path) -> None:
        """
        v2 may mean anything. Guessing is what the version exists to stop.
        """
        plan = dict(PLAN, format="horus-lineage/v2")
        found = violations(write(tmp_path, plan=plan))
        assert any("format" in v for v in found)

    def test_a_record_of_the_wrong_version_is_refused(
        self, tmp_path: Path
    ) -> None:
        """
        A directory can be mixed if a run spans an upgrade.
        """
        record = dict(RECORD, format="horus-lineage/v2")
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("format" in v for v in found)


class TestTheRenameTrap:
    """
    A field renamed inside v1: the change the version gate cannot see.

    This is the failure the suite exists for. It costs a reader every
    edge through the artifact and raises nothing on its own.
    """

    def test_a_renamed_digest_is_caught(self, tmp_path: Path) -> None:
        """
        sha256 -> digest reads as an unhashed artifact, not an error,
        unless the record is held to declaring why a digest is absent.
        """
        record = json.loads(json.dumps(RECORD))
        for side in ("inputs", "outputs"):
            for entry in record[side]:
                entry["digest"] = entry.pop("sha256")
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("no sha256" in v for v in found)

    def test_a_declared_gap_is_allowed(self, tmp_path: Path) -> None:
        """
        A folder genuinely has no digest. Saying so is conformant; the
        violation is silence, not absence.
        """
        record = json.loads(json.dumps(RECORD))
        record["outputs"][0].pop("sha256")
        record["incomplete"] = ["digests_partial"]
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert found == []

    def test_an_unknown_incomplete_code_is_caught(
        self, tmp_path: Path
    ) -> None:
        """
        A code a reader does not know is a blind spot it cannot size.
        """
        record = dict(RECORD, incomplete=["something_new"])
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("unknown code" in v for v in found)


class TestJoins:
    """
    Promises between files, which is where a reader actually lives.
    """

    def test_a_record_from_another_run_is_caught(self, tmp_path: Path) -> None:
        """
        Mixed runs in one directory would join into a graph that never
        existed.
        """
        record = dict(RECORD, run="0000000000000000")
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("does not match run.json" in v for v in found)

    def test_a_record_under_another_plan_is_caught(
        self, tmp_path: Path
    ) -> None:
        """
        The plan is what makes declared edges meaningful; the wrong one
        makes them fiction.
        """
        record = dict(RECORD, definition_sha256=OTHER_DIGEST)
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("definition_sha256" in v for v in found)

    def test_a_task_absent_from_the_plan_is_caught(
        self, tmp_path: Path
    ) -> None:
        """
        A record for a task the plan never declared means one of the two
        is wrong, and a reader cannot tell which.
        """
        record = json.loads(json.dumps(RECORD))
        record["task"]["id"] = "ghost"
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("absent from run.json tasks" in v for v in found)

    def test_a_skipped_task_must_still_join(self, tmp_path: Path) -> None:
        """
        ADR 0005's load-bearing claim: a confirmed skip records in full.
        Were it not to, the chain would break exactly where caching
        worked best, and a re-run workflow is mostly skips.
        """
        record = json.loads(json.dumps(RECORD))
        record["task"]["status"] = "skipped"
        record["outputs"][0].pop("sha256")
        record["incomplete"] = ["digests_partial"]
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("nothing downstream can join" in v for v in found)


class TestShareability:
    """
    Records are meant to be safe to hand over.
    """

    def test_labels_must_be_strings(self, tmp_path: Path) -> None:
        """
        A reader indexes on labels, and a value it cannot compare is
        worse than an absent one.
        """
        record = json.loads(json.dumps(RECORD))
        record["inputs"][0]["labels"] = {"subject": ["batch_017"]}
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("string keys and values" in v for v in found)

    def test_empty_labels_are_a_violation(self, tmp_path: Path) -> None:
        """
        Absent when there are none, so an unlabelled run reads exactly
        as it did before the field existed.
        """
        record = json.loads(json.dumps(RECORD))
        record["inputs"][0]["labels"] = {}
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("empty rather than absent" in v for v in found)

    def test_a_malformed_digest_is_caught(self, tmp_path: Path) -> None:
        """
        Truncated or uppercase digests compare unequal to the real one.
        """
        record = json.loads(json.dumps(RECORD))
        record["outputs"][0]["sha256"] = DIGEST.upper()
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("expected a sha256" in v for v in found)

    def test_a_naive_timestamp_is_caught(self, tmp_path: Path) -> None:
        """
        Without an offset, two hosts' records cannot be ordered.
        """
        plan = dict(PLAN, started_at="2026-09-01T14:20:02")
        found = violations(write(tmp_path, plan=plan))
        assert any("ISO 8601" in v for v in found)

    def test_a_naive_task_timestamp_is_caught(self, tmp_path: Path) -> None:
        """
        Task stamps are optional, and checked when present.
        """
        record = json.loads(json.dumps(RECORD))
        record["task"]["finished_at"] = "2026-09-01T14:22:31"
        found = violations(
            write(tmp_path, records={"prep.abcd1234.json": record})
        )
        assert any("task.finished_at" in v for v in found)


class TestAnUnfinishedRun:
    """
    A run that died is a fact to record, not a defect.
    """

    def test_a_missing_finished_at_is_allowed(self, tmp_path: Path) -> None:
        """
        The task records that exist are the lineage of how far it got.
        """
        plan = dict(PLAN, finished_at=None)
        assert violations(write(tmp_path, plan=plan)) == []

    def test_a_plan_with_no_records_is_caught(self, tmp_path: Path) -> None:
        """
        A directory describing no lineage should not read as clean.
        """
        (tmp_path / "run.json").write_text(json.dumps(PLAN))
        assert any("no task records" in v for v in violations(tmp_path))


class TestCommand:
    """
    ``horus-lineage conformance``.
    """

    def test_it_exits_zero_on_a_conforming_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        So it can gate a build.
        """
        assert conformance.main([str(write(tmp_path))]) == 0
        assert "conforms" in capsys.readouterr().out

    def test_it_exits_nonzero_and_names_each_violation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Reporting all of them at once, so fixing is not iterative.
        """
        plan = dict(PLAN, format="horus-lineage/v2")
        assert conformance.main([str(write(tmp_path, plan=plan))]) == 1
        assert "format" in capsys.readouterr().out

    def test_a_directory_without_a_plan_is_reported(
        self, tmp_path: Path
    ) -> None:
        """
        Pointed at the wrong directory, say so rather than pass vacuously.
        """
        assert any("not a run directory" in v for v in violations(tmp_path))
