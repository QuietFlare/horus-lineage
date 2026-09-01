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
Recording a real run, which is the only way to exercise the middlewares.

Each test runs a two-task workflow on the local target and reads the
records back, so the assertions are about files on disk rather than about
the recorder's internals.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from horus_runtime.core.task.exceptions import TaskExecutionError
from horus_runtime.core.workflow.base import BaseWorkflow

WORKFLOW = """
kind: horus_workflow
name: Recording probe
tasks:
  - kind: horus_task
    id: prep
    name: Prepare
    inputs:
      - {id: items, name: Items, kind: file, path: items.txt}
    outputs:
      - {id: prepared, name: Prepared, kind: file, path: prepared.txt}
    executor: {kind: shell}
    runtime:
      kind: python_script
      script: prep.py
      python: python3
      args: --items ${items} --out ${prepared}
    target: {kind: local}

  - kind: horus_task
    id: report
    name: Report
    inputs:
      - {id: prepared, name: Prepared, kind: file, path: prepared.txt}
    outputs:
      - {id: report, name: Report, kind: file, path: report.txt}
    executor: {kind: shell}
    runtime: {kind: command, command: "wc -l < $prepared > $report"}
    target: {kind: local}

edges:
  - source: prep
    source_output: prepared
    target: report
    target_input: prepared

orchestrator_target:
  kind: local
  working_directory: results
"""

PREP_SCRIPT = """\
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--items", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()

with open(args.out, "w") as handle:
    handle.write(open(args.items).read().upper())
"""

SHA256_HEX = 64
EXPECTED_RUNS = 2


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """
    A workflow directory the tests can run and edit.
    """
    (tmp_path / "workflow.yaml").write_text(WORKFLOW)
    (tmp_path / "prep.py").write_text(PREP_SCRIPT)
    (tmp_path / "items.txt").write_text("alpha\nbeta\n")
    return tmp_path


async def run_workflow(project: Path) -> None:
    """
    Run the probe workflow once, as the CLI would.
    """
    workflow = BaseWorkflow.from_yaml(project / "workflow.yaml")
    await workflow.run(trigger_id="prep")


def runs(records_dir: Path) -> list[Path]:
    """
    Every run directory written so far, oldest first.
    """
    return sorted(records_dir.iterdir(), key=lambda p: p.stat().st_mtime)


def record(run: Path, task_id: str) -> dict[str, Any]:
    """
    One task's record, found by the id it describes.
    """
    for path in run.glob(f"{task_id}.*.json"):
        parsed: dict[str, Any] = json.loads(path.read_text())
        return parsed
    raise AssertionError(f"no record for {task_id} in {run}")


def plan(run: Path) -> dict[str, Any]:
    """
    The run's own record.
    """
    parsed: dict[str, Any] = json.loads((run / "run.json").read_text())
    return parsed


@pytest.mark.usefixtures("horus_context", "init_registry")
class TestAFreshRun:
    """
    What a run that executes everything leaves behind.
    """

    async def test_it_writes_a_record_per_task_plus_the_plan(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        ADR 0002: the run directory is the unit.
        """
        await run_workflow(project)
        run = runs(records_dir)[0]
        assert {p.name for p in run.iterdir()} >= {
            "run.json",
            "definition.json",
        }
        assert record(run, "prep")["task"]["status"] == "completed"
        assert record(run, "report")["task"]["status"] == "completed"

    async def test_the_plan_closes_with_the_real_outcome(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        The status is derived, because the workflow assigns its own
        after the middleware chain returns (ADR 0007).
        """
        await run_workflow(project)
        closed = plan(runs(records_dir)[0])
        assert closed["status"] == "completed"
        assert closed["finished_at"] is not None

    async def test_every_task_cites_the_definition_it_ran_under(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        ADR 0002: a mismatched plan is detected, not silently joined.
        """
        await run_workflow(project)
        run = runs(records_dir)[0]
        expected = plan(run)["definition"]["sha256"]
        assert record(run, "prep")["definition_sha256"] == expected

    async def test_outputs_carry_digests_that_match_the_bytes(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        A digest that does not match the file is worse than none.
        """
        await run_workflow(project)
        output = record(runs(records_dir)[0], "prep")["outputs"][0]
        on_disk = Path(output["path"]).read_bytes()
        assert output["sha256"] == hashlib.sha256(on_disk).hexdigest()

    async def test_the_resolved_command_is_captured(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        The runtime middleware exists to substitute the templates.
        """
        await run_workflow(project)
        command = record(runs(records_dir)[0], "prep")["command"]
        assert command is not None
        assert "${" not in command

    async def test_the_environment_digests_identify_the_task(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        Naming the cause of a change needs the parts kept separate.
        """
        await run_workflow(project)
        environment = record(runs(records_dir)[0], "prep")["environment"]
        assert environment["executor"]["kind"] == "shell"
        assert environment["runtime"]["kind"] == "python_script"
        assert len(environment["config_sha256"]) == SHA256_HEX

    async def test_a_referenced_script_is_digested(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        The engine's fingerprint cannot see script bytes, so this is the
        only record of them (ADR 0005).
        """
        await run_workflow(project)
        code = record(runs(records_dir)[0], "prep")["code"]
        assert [entry["role"] for entry in code] == ["script"]
        assert code[0]["path"].endswith("prep.py")

    async def test_the_digest_join_reproduces_the_declared_edge(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        The whole design rests on this join closing.
        """
        await run_workflow(project)
        run = runs(records_dir)[0]
        produced = record(run, "prep")["outputs"][0]["sha256"]
        consumed = record(run, "report")["inputs"][0]["sha256"]
        assert produced == consumed


@pytest.mark.usefixtures("horus_context", "init_registry")
class TestASkippedRun:
    """
    The common case in any workflow that is re-run.
    """

    async def test_a_second_run_gets_its_own_directory(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        ADR 0006: re-runs never overwrite history.
        """
        await run_workflow(project)
        await run_workflow(project)
        assert len(runs(records_dir)) == EXPECTED_RUNS

    async def test_skipped_tasks_are_still_recorded(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        A skipped task never reaches the task middleware, so only the
        target middleware can see it (ADR 0007).
        """
        await run_workflow(project)
        await run_workflow(project)
        second = record(runs(records_dir)[1], "prep")
        assert second["task"]["status"] == "skipped"
        assert second["task"]["skip_reason"] == "complete"

    async def test_a_skipped_record_still_joins(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        Omitting digests here would break every edge through a cached
        task, which is most of them in a re-run workflow.
        """
        await run_workflow(project)
        await run_workflow(project)
        run = runs(records_dir)[1]
        assert record(run, "prep")["outputs"][0]["sha256"]
        assert (
            record(run, "prep")["outputs"][0]["sha256"]
            == record(run, "report")["inputs"][0]["sha256"]
        )

    async def test_a_skipped_task_keeps_its_code_digests(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        Without these, a changed script maps to none of the tasks that
        use it, precisely because they were cached.
        """
        await run_workflow(project)
        await run_workflow(project)
        assert record(runs(records_dir)[1], "prep")["code"]


@pytest.mark.usefixtures("horus_context", "init_registry")
class TestDigestsSwitchedOff:
    """
    ADR 0003's one switch for cost-sensitive runs.
    """

    async def test_records_still_appear_and_say_what_is_missing(
        self,
        project: Path,
        records_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Report what was not captured, rather than looking complete.
        """
        monkeypatch.setenv("HORUS_LINEAGE_DIGESTS", "0")
        await run_workflow(project)
        prep = record(runs(records_dir)[0], "prep")
        assert "digests_disabled" in prep["incomplete"]
        assert "sha256" not in prep["outputs"][0]


@pytest.mark.usefixtures("horus_context", "init_registry")
class TestWhenThingsGoWrong:
    """
    The guarantees ADR 0004 makes about failure.
    """

    async def test_a_failing_task_is_recorded_as_failed(
        self, project: Path, records_dir: Path
    ) -> None:
        """
        The status is derived from the outcome, because the engine
        assigns its own only after the chain returns (ADR 0007).
        """
        (project / "prep.py").write_text("raise SystemExit(3)\n")
        with pytest.raises(TaskExecutionError):
            await run_workflow(project)
        assert (
            record(runs(records_dir)[0], "prep")["task"]["status"] == "failed"
        )

    async def test_a_broken_recorder_does_not_break_the_run(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The whole point of ADR 0004. A recorder that can fail a run gets
        uninstalled the first time it does.
        """
        monkeypatch.setattr(
            "horus_lineage.record.build_task_record",
            _explode,
        )
        await run_workflow(project)
        assert (project / "results" / "prepared.txt").is_file()

    async def test_an_unwritable_destination_does_not_break_the_run(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A records directory that cannot be created is not the run's
        problem.
        """
        monkeypatch.setenv("HORUS_LINEAGE_DIR", "/proc/nope/records")
        await run_workflow(project)
        assert (project / "results" / "prepared.txt").is_file()


async def _explode(**_kwargs: Any) -> dict[str, Any]:
    """
    Stand-in for a recorder step that fails at the worst moment.
    """
    raise RuntimeError("the recorder is broken")
