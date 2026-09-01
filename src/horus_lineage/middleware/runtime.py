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
Captures the command a task actually ran.

A workflow's arguments carry templates like ``${measurements}``, and the
engine substitutes them inside ``setup_runtime``, whose return value is
the formatted result. Wrapping that call is the only place the resolved
form exists, and the context carries the task, so it can be attributed.

The value is parked on the run's session for the task middleware to fold
into its record, because this fires while the task is still running.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from horus_runtime.middleware.runtime import (
    RuntimeMiddleware,
    RuntimeMiddlewareContext,
)

from horus_lineage.session import current

R = TypeVar("R")

MAX_COMMAND = 64 * 1024
"""
A command is a line, not a payload. A runtime free to return anything
could return something enormous, and a record is not the place for it.
"""


class LineageRuntimeMiddleware(RuntimeMiddleware):
    """
    Remembers each task's substituted command.
    """

    async def wrap(
        self,
        context: RuntimeMiddlewareContext,
        call_next: Callable[[], Awaitable[R]],
    ) -> R:
        """
        Pass the setup through untouched, keeping a copy of its result.
        """
        result = await call_next()
        session = current()
        if session is not None and isinstance(result, str):
            session.commands[context.task.id] = result[:MAX_COMMAND]
        return result
