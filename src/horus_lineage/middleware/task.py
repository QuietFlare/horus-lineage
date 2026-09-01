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
The full record for a task that actually executed.

This overrides ``wrap`` rather than using ``after``, because ``after``
cannot see the outcome: ``BaseTask.run`` assigns COMPLETED or FAILED in
the block *around* the middleware chain, so inside ``after`` the status is
always RUNNING. Watching whether ``call_next`` raised gives the status the
engine is about to assign (ADR 0007).
"""

from asyncio import CancelledError
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from horus_runtime.core.task.base import BaseTask
from horus_runtime.core.task.status import TaskStatus
from horus_runtime.middleware.task import (
    TaskMiddleware,
    TaskMiddlewareContext,
)

from horus_lineage.observer import observe
from horus_lineage.record import build_task_record
from horus_lineage.session import current
from horus_lineage.writer import RunWriter

R = TypeVar("R")


class LineageTaskMiddleware(TaskMiddleware):
    """
    Records every task that reaches execution.
    """

    async def wrap(
        self,
        context: TaskMiddlewareContext,
        call_next: Callable[[], Awaitable[R]],
    ) -> R:
        """
        Run the task, then record it under the status its outcome implies.
        """
        try:
            result = await call_next()
        except CancelledError:
            await self._record(context.task, TaskStatus.CANCELED)
            raise
        except Exception:
            await self._record(context.task, TaskStatus.FAILED)
            raise
        await self._record(context.task, TaskStatus.COMPLETED)
        return result

    async def _record(self, task: BaseTask, status: TaskStatus) -> None:
        """
        Write one task record, or log why it could not be written.
        """
        session = current()
        if session is None:
            return

        async def body() -> Any:
            record = await build_task_record(
                task=task,
                status=status,
                session=session,
                command=session.commands.pop(task.id, None),
            )
            session.recorded.add(task.id)
            RunWriter(session.directory).write_task(task.id, record)

        await observe(f"record task {task.id}", body)
