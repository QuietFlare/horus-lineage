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
Catches the tasks the task middleware never sees.

A skipped task returns from ``BaseTask.run`` before the task middleware
chain is entered, so nothing else can record it. Skips are the common case
in any workflow that is re-run, and a skipped task's outputs are real, so
leaving them out would break every edge through a cached task.

``dispatch`` only schedules the task and returns, so this waits on the
future the scheduler is about to wait on anyway, then records whatever the
task middleware did not (ADR 0007).
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from horus_runtime.middleware.target import (
    TargetMiddleware,
    TargetMiddlewareContext,
)

from horus_lineage.observer import observe
from horus_lineage.record import build_task_record
from horus_lineage.session import current
from horus_lineage.writer import RunWriter

R = TypeVar("R")


class LineageTargetMiddleware(TargetMiddleware):
    """
    Records tasks that never reached the task middleware.
    """

    async def wrap(
        self,
        context: TargetMiddlewareContext,
        call_next: Callable[[], Awaitable[R]],
    ) -> R:
        """
        Let dispatch happen, wait for the outcome, then record the gap.
        """
        result = await call_next()
        await observe(
            f"observe dispatch of {context.task.id}",
            lambda: self._settle(context),
        )
        return result

    async def _settle(self, context: TargetMiddlewareContext) -> None:
        """
        Wait for the dispatched task, then record it if nothing else did.

        The wait is on an ``asyncio.Task`` the scheduler awaits again on
        its next line. Awaiting one twice is safe and the second await
        returns at once, so its exception still surfaces there exactly as
        it would have. Swallowing here removes no failure path, it only
        avoids adding one.
        """
        task = context.task
        try:
            await context.target.wait()
        except Exception:
            pass

        session = current()
        if session is None or task.id in session.recorded:
            return

        record = await build_task_record(
            task=task,
            status=task.status,
            session=session,
            command=session.commands.pop(task.id, None),
        )
        session.recorded.add(task.id)
        RunWriter(session.directory).write_task(task.id, record)
