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
What ``horus-lineage/v1`` promises, as something you can run.

ADR 0005 states the format in prose. Prose is read once and then
paraphrased, so this states the same contract as assertions a build can
fail on. A field renamed inside v1 is the change the version check
cannot catch, and it is the one that quietly empties a downstream graph
rather than raising anything.

Shipped rather than kept in tests, because the party who needs it most
is the reader on the other side of the format. A consumer runs this
against records it was handed and learns whether it holds a v1 record
or something that merely says it is one.

Two rules govern what belongs here:

Only what a reader would misread. A field that may be absent is checked
for type when present and never for presence, so an optional field never
becomes mandatory by being tested.

Never the recorder's internals. This reads a directory, so any producer
of v1 records can be held to it, not only this one.
"""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAT = "horus-lineage/v1"
"""The only version this suite describes."""

SHA256 = re.compile(r"^[0-9a-f]{64}$")
"""Lowercase hex, the form every digest field takes."""

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+(?:[+-]\d{2}:\d{2}|Z)$")
"""ISO 8601 with an offset. A naive timestamp is not comparable."""

INCOMPLETE_CODES = frozenset({"digests_disabled", "digests_partial"})
"""The codes ADR 0005 defines. An unknown code is a reader's blind spot."""

SKIPPED_STATUSES = frozenset({"skipped"})
"""Statuses that mean the engine confirmed rather than executed."""


@dataclass(frozen=True)
class Violation:
    """One broken promise, located well enough to fix."""

    where: str
    """The file, and the path within it."""

    detail: str
    """What was expected, and what was found instead."""

    def __str__(self) -> str:
        """One line, so a failure reads without unpacking."""
        return f"{self.where}: {self.detail}"


class Check:
    """
    Accumulates violations rather than raising on the first.

    A record with four broken fields should report four, or fixing it
    becomes four runs of the same command.
    """

    def __init__(self) -> None:
        """Start with nothing broken."""
        self.violations: list[Violation] = []

    def fail(self, where: str, detail: str) -> None:
        """Record a violation."""
        self.violations.append(Violation(where, detail))

    def typed(
        self, where: str, obj: Any, key: str, kind: type | tuple[type, ...]
    ) -> bool:
        """
        Require *key* to be present and of *kind*. True when it holds.
        """
        if key not in obj:
            self.fail(f"{where}.{key}", "required field is missing")
            return False
        if not isinstance(obj[key], kind):
            names = getattr(kind, "__name__", None) or " or ".join(
                k.__name__
                for k in kind  # type: ignore[union-attr]
            )
            self.fail(
                f"{where}.{key}",
                f"expected {names}, found {type(obj[key]).__name__}",
            )
            return False
        return True

    def optional(
        self, where: str, obj: Any, key: str, kind: type | tuple[type, ...]
    ) -> bool:
        """
        Check *key* only when present, so optional stays optional.
        """
        if key not in obj or obj[key] is None:
            return False
        return self.typed(where, obj, key, kind)

    def digest(self, where: str, value: Any) -> None:
        """A digest is 64 lowercase hex characters or it is not one."""
        if not isinstance(value, str) or not SHA256.match(value):
            self.fail(where, f"expected a sha256, found {value!r}")

    def timestamp(self, where: str, value: Any) -> None:
        """A timestamp without an offset cannot be ordered across hosts."""
        if not isinstance(value, str) or not TIMESTAMP.match(value):
            self.fail(where, f"expected an ISO 8601 instant, found {value!r}")


def _artifact(check: Check, where: str, entry: Any) -> None:
    """
    One input or output entry.

    ``sha256`` is optional by design: a folder has none, and ADR 0003
    says an absent digest is reported rather than invented. ``labels``
    is absent when empty, so an unlabelled run reads as it did before
    the field existed.
    """
    if not isinstance(entry, dict):
        check.fail(where, f"expected an object, found {type(entry).__name__}")
        return
    check.typed(where, entry, "id", str)
    check.typed(where, entry, "path", str)
    check.optional(where, entry, "size", int)
    if entry.get("sha256") is not None:
        check.digest(f"{where}.sha256", entry["sha256"])
    if "labels" in entry:
        labels = entry["labels"]
        if not isinstance(labels, dict):
            check.fail(f"{where}.labels", "expected an object")
        elif not labels:
            check.fail(
                f"{where}.labels",
                "empty rather than absent; an artifact with no labels "
                "omits the field",
            )
        else:
            for key, value in labels.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    check.fail(
                        f"{where}.labels",
                        f"only string keys and values are kept, "
                        f"found {key!r}: {value!r}",
                    )


def _code(check: Check, where: str, entry: Any, role: bool) -> None:
    """One code file. ``role`` appears on task records, not on run.json."""
    if not isinstance(entry, dict):
        check.fail(where, f"expected an object, found {type(entry).__name__}")
        return
    check.typed(where, entry, "path", str)
    check.optional(where, entry, "size", int)
    if entry.get("sha256") is not None:
        check.digest(f"{where}.sha256", entry["sha256"])
    if role:
        check.optional(where, entry, "role", str)


def check_plan(check: Check, plan: Any, where: str = "run.json") -> None:
    """
    ``run.json``: the prospective half, completed when the run ends.
    """
    if not isinstance(plan, dict):
        check.fail(where, "expected an object")
        return

    if plan.get("format") != FORMAT:
        check.fail(
            f"{where}.format",
            f"expected {FORMAT!r}, found {plan.get('format')!r}",
        )

    check.typed(where, plan, "run", str)
    check.typed(where, plan, "status", str)
    if check.typed(where, plan, "started_at", str):
        check.timestamp(f"{where}.started_at", plan["started_at"])
    # Absent means the run died partway, which is a fact about the run
    # rather than a defect in the record.
    if plan.get("finished_at") is not None:
        check.timestamp(f"{where}.finished_at", plan["finished_at"])

    if check.typed(where, plan, "workflow", dict):
        check.typed(f"{where}.workflow", plan["workflow"], "name", str)

    _plan_files(check, plan, where)


def _plan_files(check: Check, plan: Any, where: str) -> None:
    """
    The plan's references: the definition it projected, the workflow file
    it came from, the code it saw, and the tasks it declared.
    """
    if check.typed(where, plan, "definition", dict):
        check.typed(f"{where}.definition", plan["definition"], "file", str)
        check.digest(
            f"{where}.definition.sha256", plan["definition"].get("sha256")
        )

    # Null when the workflow was built in Python rather than loaded.
    source = plan.get("source")
    if source is not None:
        if isinstance(source, dict):
            check.typed(f"{where}.source", source, "file", str)
            check.digest(f"{where}.source.sha256", source.get("sha256"))
        else:
            check.fail(f"{where}.source", "expected an object or null")

    if check.typed(where, plan, "code", list):
        for i, entry in enumerate(plan["code"]):
            _code(check, f"{where}.code[{i}]", entry, role=False)

    if check.typed(where, plan, "tasks", list):
        for i, task in enumerate(plan["tasks"]):
            if not isinstance(task, str):
                check.fail(f"{where}.tasks[{i}]", "expected a task id")


def check_record(check: Check, record: Any, where: str) -> None:
    """
    One ``<task-id>.json``: the retrospective half.
    """
    if not isinstance(record, dict):
        check.fail(where, "expected an object")
        return

    if record.get("format") != FORMAT:
        check.fail(
            f"{where}.format",
            f"expected {FORMAT!r}, found {record.get('format')!r}",
        )

    check.typed(where, record, "run", str)
    check.typed(where, record, "execution", str)
    check.digest(f"{where}.definition_sha256", record.get("definition_sha256"))
    if check.typed(where, record, "recorded_at", str):
        check.timestamp(f"{where}.recorded_at", record["recorded_at"])

    if check.typed(where, record, "task", dict):
        task = record["task"]
        check.typed(f"{where}.task", task, "id", str)
        check.typed(f"{where}.task", task, "status", str)
        check.optional(f"{where}.task", task, "name", str)
        check.optional(f"{where}.task", task, "runs", int)
        # Null on a skip, and on records older than the fields.
        for instant in ("started_at", "finished_at"):
            if task.get(instant) is not None:
                check.timestamp(f"{where}.task.{instant}", task[instant])

    _record_evidence(check, record, where)


def _record_evidence(check: Check, record: Any, where: str) -> None:
    """
    What the task ran on, ran as, and ran over: target, environment,
    code, and the artifacts either side of it.
    """
    # Kind and location id only. A record carrying credentials is not
    # shareable, and shareable is the whole point (ADR 0005).
    if check.typed(where, record, "target", dict):
        check.typed(f"{where}.target", record["target"], "kind", str)

    # Null when the command could not be resolved, notably on a skip.
    check.optional(where, record, "command", str)

    if check.typed(where, record, "environment", dict):
        env = record["environment"]
        for part in ("executor", "runtime"):
            if check.typed(f"{where}.environment", env, part, dict):
                check.typed(
                    f"{where}.environment.{part}", env[part], "kind", str
                )
                check.digest(
                    f"{where}.environment.{part}.sha256",
                    env[part].get("sha256"),
                )
        check.digest(
            f"{where}.environment.config_sha256", env.get("config_sha256")
        )

    if check.typed(where, record, "code", list):
        for i, entry in enumerate(record["code"]):
            _code(check, f"{where}.code[{i}]", entry, role=True)

    for side in ("inputs", "outputs"):
        if check.typed(where, record, side, list):
            for i, entry in enumerate(record[side]):
                _artifact(check, f"{where}.{side}[{i}]", entry)

    if check.typed(where, record, "incomplete", list):
        for code in record["incomplete"]:
            if code not in INCOMPLETE_CODES:
                check.fail(
                    f"{where}.incomplete",
                    f"unknown code {code!r}, v1 defines "
                    f"{sorted(INCOMPLETE_CODES)}",
                )
        _digests_accounted(check, record, where)


def _digests_accounted(check: Check, record: Any, where: str) -> None:
    """
    Every artifact either carries a digest or the record says why not.

    This is what catches a field renamed inside v1, which the version
    check cannot see. ``sha256`` is optional on its own, so a rename is
    indistinguishable from a folder, and a reader that trusts the field
    silently loses every edge through that artifact.

    It is not indistinguishable from both fields at once. ADR 0005 makes
    the recorder declare an unhashed artifact in ``incomplete``, so a
    missing digest with nothing declared is the record contradicting
    itself, and a contradiction is loud where an absence is not.
    """
    declared = set(record.get("incomplete") or [])
    if declared & {"digests_disabled", "digests_partial"}:
        return

    for side in ("inputs", "outputs"):
        for i, entry in enumerate(record.get(side) or []):
            if isinstance(entry, dict) and not entry.get("sha256"):
                check.fail(
                    f"{where}.{side}[{i}]",
                    "no sha256, yet incomplete declares no reason. Either "
                    "the digest is missing or the field was renamed; both "
                    "cost a reader every edge through this artifact",
                )


def check_joins(check: Check, plan: Any, records: dict[str, Any]) -> None:
    """
    The promises that hold *between* files, which is where a reader
    actually lives.

    A record that parses but does not join is the failure worth
    engineering against: it produces a graph with no edges, and a
    downstream tool reports that nothing is affected rather than
    reporting that it could not tell.
    """
    if not isinstance(plan, dict):
        return

    run = plan.get("run")
    definition = (plan.get("definition") or {}).get("sha256")
    declared = set(plan.get("tasks") or [])

    for name, record in records.items():
        if not isinstance(record, dict):
            continue

        if record.get("run") != run:
            check.fail(
                f"{name}.run",
                f"{record.get('run')!r} does not match run.json "
                f"{run!r}; the record does not belong to this run",
            )

        if record.get("definition_sha256") != definition:
            check.fail(
                f"{name}.definition_sha256",
                "does not match run.json definition.sha256; the task ran "
                "under a plan this directory does not contain",
            )

        task_id = (record.get("task") or {}).get("id")
        if declared and task_id not in declared:
            check.fail(
                f"{name}.task.id",
                f"{task_id!r} is absent from run.json tasks",
            )

        # The claim that makes caching safe to read: a confirmed skip
        # carries digests, so it joins exactly like an executed task.
        # Without this the chain breaks where caching worked best.
        status = (record.get("task") or {}).get("status")
        if status in SKIPPED_STATUSES and "digests_disabled" not in (
            record.get("incomplete") or []
        ):
            outputs = record.get("outputs") or []
            undigested = [
                o
                for o in outputs
                if isinstance(o, dict) and not o.get("sha256")
            ]
            if outputs and len(undigested) == len(outputs):
                check.fail(
                    f"{name}.outputs",
                    "a skipped task carries no digests at all, so nothing "
                    "downstream can join to it; ADR 0005 records a "
                    "confirmed skip in full",
                )


def load(run_dir: Path) -> tuple[Any, dict[str, Any]]:
    """
    Read a run directory in either layout, per-task files or merged.
    """
    plan = json.loads((run_dir / "run.json").read_text())

    records: dict[str, Any] = {}
    merged = run_dir / "records.jsonl"
    if merged.is_file():
        for i, line in enumerate(merged.read_text().splitlines()):
            if line.strip():
                records[f"records.jsonl:{i + 1}"] = json.loads(line)
        return plan, records

    for path in sorted(run_dir.glob("*.json")):
        if path.name in ("run.json", "definition.json"):
            continue
        records[path.name] = json.loads(path.read_text())
    return plan, records


def check_run(run_dir: Path) -> list[Violation]:
    """
    Every v1 promise, for one run directory. Empty means conformant.
    """
    check = Check()

    if not (run_dir / "run.json").is_file():
        check.fail(str(run_dir), "no run.json; not a run directory")
        return check.violations

    try:
        plan, records = load(run_dir)
    except json.JSONDecodeError as exc:
        check.fail(str(run_dir), f"invalid JSON: {exc}")
        return check.violations

    check_plan(check, plan)
    for name, record in records.items():
        check_record(check, record, name)
    check_joins(check, plan, records)

    if not records:
        check.fail(
            str(run_dir),
            "no task records; a run directory with a plan and nothing "
            "else describes no lineage",
        )
    return check.violations


def main(argv: list[str] | None = None) -> int:
    """``horus-lineage conformance <run-dir>``."""
    parser = argparse.ArgumentParser(
        prog="horus-lineage conformance",
        description=f"Check a run directory against {FORMAT}.",
    )
    parser.add_argument("run_dir", type=Path, help="a run directory")
    parser.add_argument(
        "--quiet", action="store_true", help="print nothing, exit 0 or 1"
    )
    args = parser.parse_args(argv)

    violations = check_run(args.run_dir)
    if args.quiet:
        return 1 if violations else 0

    if not violations:
        print(f"{args.run_dir}: conforms to {FORMAT}")
        return 0

    print(f"{args.run_dir}: {len(violations)} violations of {FORMAT}")
    for violation in violations:
        print(f"  {violation}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
