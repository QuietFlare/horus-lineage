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
Turning engine objects into the shapes ADR 0005 describes.

Nothing here writes files or touches middleware. It reads a workflow or a
task and returns plain dictionaries, which makes the format testable
without running anything.
"""

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from horus_runtime.core.artifact.store import ArtifactStore

from horus_lineage import RECORD_FORMAT
from horus_lineage.writer import digest_of, now

if TYPE_CHECKING:
    from horus_runtime.core.artifact.base import BaseArtifact
    from horus_runtime.core.target.base import BaseTarget
    from horus_runtime.core.task.base import BaseTask
    from horus_runtime.core.task.status import TaskStatus
    from horus_runtime.core.workflow.base import BaseWorkflow

    from horus_lineage.session import LineageSession

MANIFEST_DIR = ".horus"
"""Where the engine files its fingerprint, under the target's workdir."""

UNHASHABLE = "unhashable"
"""
What the engine records for an artifact it could not hash, currently any
folder. Not a digest, so it never reaches a record.
"""

_CODE_SUFFIXES = frozenset({".py", ".sh", ".R", ".r", ".jl", ".pl", ".rb"})
"""
Suffixes worth digesting as code.

Deliberately narrow. A runtime names its script by path rather than
carrying its bytes, so these files are invisible to the engine's own
fingerprint and this is the only record of them (ADR 0005).
"""


def project_definition(workflow: "BaseWorkflow") -> dict[str, Any]:
    """
    The workflow as an explicit allowlist of fields.

    A full model dump would carry whatever a third-party target or
    executor defines, credentials included, and records must be safe to
    share. Unknown fields are dropped rather than passed through.
    """
    return {
        "name": workflow.name,
        "tasks": [_project_task(task) for task in workflow.tasks],
        "edges": [
            {
                "source": edge.source,
                "source_output": edge.source_output,
                "target": edge.target,
                "target_input": edge.target_input,
                "transfer": edge.transfer,
            }
            for edge in workflow.edges
        ],
    }


def _project_task(task: "BaseTask") -> dict[str, Any]:
    """
    One task's declared shape, without its executor or target internals.
    """
    return {
        "id": task.id,
        "definition_id": task.definition_id,
        "kind": task.kind,
        "name": task.name,
        "executor": task.executor.kind,
        "runtime": task.runtime.kind,
        "target": task.target.kind,
        "inputs": [_declared(a) for a in task.inputs],
        "outputs": [_declared(a) for a in task.outputs],
    }


def labels_of(artifact: "BaseArtifact") -> dict[str, str]:
    """
    An artifact's domain labels, or empty on an engine without them.

    Read defensively: ``BaseArtifact.labels`` arrived in horus-runtime
    after this recorder, and a record written against an older engine
    should say "no labels" rather than fail.

    Only string keys and values survive. A reader groups and indexes on
    these, so a value it cannot compare is worse than an absent one.
    """
    raw = getattr(artifact, "labels", None)
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _declared(artifact: "BaseArtifact") -> dict[str, Any]:
    """
    An artifact as the workflow declared it, before any run resolved it.
    """
    declared = artifact.declared_path
    projected: dict[str, Any] = {
        "id": artifact.id,
        "kind": artifact.kind,
        "path": str(declared) if declared is not None else str(artifact.path),
    }
    labels = labels_of(artifact)
    if labels:
        projected["labels"] = labels
    return projected


def environment(task: "BaseTask") -> dict[str, Any]:
    """
    Digests identifying the executor and runtime this task ran under.

    Hashes only, never the dumps, for the same reason the definition is a
    projection. ``config_sha256`` reproduces the engine's own fingerprint
    field, so a reader inherits its invalidation rule rather than
    reimplementing one that can drift.
    """
    runtime = task.runtime.model_dump(mode="json")
    executor = task.executor.model_dump(mode="json")
    combined = json.dumps(
        {"runtime": runtime, "executor": executor}, sort_keys=True
    )
    return {
        "executor": {
            "kind": task.executor.kind,
            "sha256": digest_of(executor),
        },
        "runtime": {"kind": task.runtime.kind, "sha256": digest_of(runtime)},
        "config_sha256": hashlib.sha256(combined.encode()).hexdigest(),
    }


def code_files(task: "BaseTask") -> list[dict[str, Any]]:
    """
    Digests of the local code files this task's runtime referenced.

    Found by scanning the runtime's own fields for values that resolve to
    an existing local file with a code suffix, because ``BaseRuntime``
    knows its local paths (it anchors them) but does not expose them. An
    accessor upstream would replace this heuristic.
    """
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for key, value in task.runtime.model_dump(mode="json").items():
        path = _as_code_path(value)
        if path is None or path in seen:
            continue
        seen.add(path)
        found.append(
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": _digest_local(path),
                "role": key,
            }
        )
    return found


def _as_code_path(value: Any) -> Path | None:
    """
    *value* as a local code file, or ``None`` when it is not one.
    """
    if not isinstance(value, str) or not value or "${" in value:
        return None
    path = Path(value)
    if path.suffix not in _CODE_SUFFIXES:
        return None
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _digest_local(path: Path) -> str:
    """
    sha256 of a file on the machine running the orchestrator.
    """
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


async def read_fingerprint(task: "BaseTask") -> dict[str, Any] | None:
    """
    The fingerprint the engine recorded for *task*, or ``None``.

    This is what the skip decision was made against, so its input digests
    are the current input state whenever a task skipped as complete. It
    also saves re-hashing inputs the engine already hashed (ADR 0003).
    """
    try:
        base = task.target.resolved_working_directory
    except Exception:
        return None

    path = f"{base}/{MANIFEST_DIR}/{task.id}.json"
    try:
        raw = await task.target.get_file(path)
    except Exception:
        return None

    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def build_task_record(
    *,
    task: "BaseTask",
    status: "TaskStatus",
    session: "LineageSession",
    command: str | None = None,
) -> dict[str, Any]:
    """
    One task's observation, as ADR 0005 describes it.

    Input digests come from the engine's fingerprint rather than a fresh
    hash, so the record holds the value the engine acted on and the bytes
    are read once per run instead of twice. A skipped task is recorded in
    full for the same reason an executed one is: its outputs exist, and
    omitting them would break every edge through a cached task.
    """
    known = _known_digests(await read_fingerprint(task))

    reader = ArtifactReader(task.target, session.config.digests)
    inputs = [
        await reader.entry(artifact, known.get(artifact.id))
        for artifact in task.inputs
    ]
    outputs = [await reader.entry(artifact) for artifact in task.outputs]

    # A missing fingerprint is not itself a gap. Falling back to hashing
    # the bytes costs a read and loses nothing, and some task kinds never
    # write one. What a reader needs to know is whether any artifact ended
    # up without a digest, because that is an edge it will not see.
    incomplete: list[str] = []
    if not session.config.digests:
        incomplete.append("digests_disabled")
    elif any("sha256" not in entry for entry in (*inputs, *outputs)):
        incomplete.append("digests_partial")

    return {
        "format": RECORD_FORMAT,
        "run": session.run,
        "execution": task._execution_id,  # noqa: SLF001
        "definition_sha256": session.definition_sha256,
        "recorded_at": now(),
        "task": {
            "id": task.id,
            "definition_id": task.definition_id,
            "kind": task.kind,
            "name": task.name,
            "status": status.value,
            "skip_reason": (
                task.skip_reason.value
                if task.skip_reason is not None
                else None
            ),
            "runs": task.runs,
        },
        "target": {
            "kind": task.target.kind,
            "location_id": _location(task.target),
        },
        "working_dir": _working_dir(task),
        "command": command,
        "environment": environment(task),
        "code": code_files(task),
        "inputs": inputs,
        "outputs": outputs,
        "incomplete": incomplete,
    }


def _known_digests(fingerprint: dict[str, Any] | None) -> dict[str, str]:
    """
    Input digests from a fingerprint, minus the unhashable placeholder.
    """
    if fingerprint is None:
        return {}
    inputs = fingerprint.get("inputs")
    if not isinstance(inputs, dict):
        return {}
    return {
        key: value
        for key, value in inputs.items()
        if isinstance(value, str) and value != UNHASHABLE
    }


def _location(target: "BaseTarget") -> str | None:
    """
    A target's location id, which some targets compute and may refuse.
    """
    try:
        return target.location_id
    except Exception:
        return None


def _working_dir(task: "BaseTask") -> str | None:
    """
    A task's scratch directory, which needs a target working directory.
    """
    try:
        return task.working_dir
    except Exception:
        return None


class ArtifactReader:
    """
    Resolves artifacts to record entries against one task's target.

    Sizes come from directory listings, cached per parent, because
    ``ArtifactStore`` offers a digest and no size. A listing is expensive
    on a large directory, so a missing size is normal rather than an
    error (ADR 0003).
    """

    def __init__(self, target: "BaseTarget", digests: bool) -> None:
        """
        Read artifacts against *target*, hashing them when *digests*.
        """
        self.target = target
        self.digests = digests
        self.store = ArtifactStore(target)
        self._sizes: dict[str, dict[str, int]] = {}

    async def entry(
        self,
        artifact: "BaseArtifact",
        known_digest: str | None = None,
    ) -> dict[str, Any]:
        """
        One artifact as it appears in ``inputs`` or ``outputs``.

        Args:
            artifact: The artifact to describe.
            known_digest: A digest already recorded by the engine, used
                in place of hashing the bytes again.
        """
        path = self.target.path_on_target(artifact)
        entry: dict[str, Any] = {"id": artifact.id, "path": path}

        # What this artifact is, in the workflow author's own vocabulary.
        # Omitted when empty so an unlabelled run reads exactly as before.
        labels = labels_of(artifact)
        if labels:
            entry["labels"] = labels

        size = await self._size(path)
        if size is not None:
            entry["size"] = size

        sha256 = known_digest
        if sha256 is None and self.digests:
            sha256 = await self.store.digest(artifact)
        if sha256 is not None:
            entry["sha256"] = sha256
        return entry

    async def _size(self, path: str) -> int | None:
        """
        Size of *path* from a cached listing of its parent, or ``None``.
        """
        parent = path.rsplit("/", 1)[0] or "/"
        if parent not in self._sizes:
            try:
                listing = await self.target.list_dir(parent)
            except Exception:
                self._sizes[parent] = {}
            else:
                self._sizes[parent] = {
                    item.path: item.size for item in listing if not item.is_dir
                }
        return self._sizes[parent].get(path)
