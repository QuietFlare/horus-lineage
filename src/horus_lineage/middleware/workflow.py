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
Opens and closes the run directory.

Writes ``run.json`` before any task starts, so a run that dies partway
still leaves its plan and the records of how far it got, then fills in
``finished_at`` and the final status on the way out.
"""

import hashlib
from asyncio import CancelledError
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from horus_runtime.core.workflow.base import BaseWorkflow
from horus_runtime.core.workflow.status import WorkflowStatus
from horus_runtime.middleware.workflow import (
    WorkflowMiddleware,
    WorkflowMiddlewareContext,
)

from horus_lineage import RECORD_FORMAT
from horus_lineage.config import LineageConfig
from horus_lineage.observer import observe
from horus_lineage.record import code_files, project_definition
from horus_lineage.session import LineageSession, begin, end, mint_run_id
from horus_lineage.writer import RunWriter, digest_of, now

R = TypeVar("R")

DEFINITION_FILE = "definition.json"
RUN_FILE = "run.json"
SOURCE_FILE = "workflow.yaml"

_SETTLED = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELED,
        WorkflowStatus.PARTIAL,
    }
)
"""Statuses the workflow reached on its own, which outrank a guess."""


class LineageWorkflowMiddleware(WorkflowMiddleware):
    """
    Records the plan, then closes the record out.
    """

    def __init__(self) -> None:
        """
        Start with no run directory, opened when the workflow runs.
        """
        self._writer: RunWriter | None = None
        self._plan: dict[str, Any] | None = None

    async def wrap(
        self,
        context: WorkflowMiddlewareContext,
        call_next: Callable[[], Awaitable[R]],
    ) -> R:
        """
        Open the run directory, run the workflow, then close it out.
        """
        token = await observe(
            "start recording", lambda: self._open(context.workflow)
        )
        try:
            result = await call_next()
        except CancelledError:
            await self._finish(context, WorkflowStatus.CANCELED, token)
            raise
        except Exception:
            await self._finish(context, WorkflowStatus.FAILED, token)
            raise
        await self._finish(context, WorkflowStatus.COMPLETED, token)
        return result

    async def _finish(
        self,
        context: WorkflowMiddlewareContext,
        outcome: WorkflowStatus,
        token: Any,
    ) -> None:
        """
        Close the record out and drop the session, whatever happened.
        """
        await observe("finish run.json", lambda: self._close(context, outcome))
        if token is not None:
            end(token)

    async def _open(self, workflow: BaseWorkflow) -> Any:
        """
        Mint the run id, write the plan, and publish the session.
        """
        config = LineageConfig.from_env()
        run = mint_run_id()
        run_directory = Path(workflow.run_directory)
        writer = RunWriter(config.resolve_root(run_directory) / run)

        definition = project_definition(workflow)
        definition_sha256 = digest_of(definition)
        writer.write(DEFINITION_FILE, definition)

        code = self._code(workflow)
        source = self._copy_source(workflow, writer)

        self._writer = writer
        self._plan = {
            "format": RECORD_FORMAT,
            "run": run,
            "run_scope": workflow.run_scope,
            "run_directory": str(run_directory),
            "workflow": {
                "id": str(workflow.id),
                "slug": workflow.workflow_slug,
                "name": workflow.name,
            },
            "started_at": now(),
            "finished_at": None,
            "status": None,
            "definition": {
                "file": DEFINITION_FILE,
                "sha256": definition_sha256,
            },
            "source": source,
            "code": code,
            "tasks": [task.id for task in workflow.tasks],
        }
        writer.write(RUN_FILE, self._plan)

        return begin(
            LineageSession(
                run=run,
                directory=writer.directory,
                config=config,
                definition_sha256=definition_sha256,
            )
        )

    async def _close(
        self,
        context: WorkflowMiddlewareContext,
        outcome: WorkflowStatus,
    ) -> None:
        """
        Stamp the outcome onto the plan already on disk.

        The status is derived from whether the chain raised, not read off
        the workflow, because ``BaseWorkflow.run`` assigns it after the
        chain returns. Reading it here would record RUNNING every time.
        A status the workflow already settled on itself wins, so a
        PARTIAL stop is not overwritten with COMPLETED.
        """
        if self._writer is None or self._plan is None:
            return
        settled = context.workflow.status
        self._plan["finished_at"] = now()
        self._plan["status"] = (
            settled.value if settled in _SETTLED else outcome.value
        )
        self._writer.write(RUN_FILE, self._plan)

    @staticmethod
    def _code(workflow: BaseWorkflow) -> list[dict[str, Any]]:
        """
        Every code file any task referenced, deduplicated. Attribution
        lives on the task records, this is the rollup.
        """
        rollup: dict[str, dict[str, Any]] = {}
        for task in workflow.tasks:
            for entry in code_files(task):
                rollup.setdefault(entry["path"], entry)
        return sorted(rollup.values(), key=lambda entry: entry["path"])

    @staticmethod
    def _copy_source(
        workflow: BaseWorkflow, writer: RunWriter
    ) -> dict[str, Any] | None:
        """
        Copy the workflow's own YAML in when it came from one.

        A workflow built in Python has no source file, and its projected
        definition is the only description there is.
        """
        source = getattr(workflow, "source_path", None)
        if source is None:
            return None
        path = Path(str(source))
        if not path.is_file():
            return None
        raw = path.read_bytes()
        writer.write_bytes(SOURCE_FILE, raw)
        return {
            "file": SOURCE_FILE,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
