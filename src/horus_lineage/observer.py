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
The guard that makes ADR 0004 true.

A recorder that can break the runs it records gets uninstalled the first
time it does. Every hook body goes through :func:`observe`, which logs and
swallows anything that goes wrong.

``CancelledError`` is deliberately not caught. It is how the event loop
tears a run down, and swallowing it would leave a coroutine running past
its own cancellation, which is a behaviour change rather than a recovery.
"""

from asyncio import CancelledError
from collections.abc import Awaitable, Callable

from horus_runtime.logging import horus_logger

from horus_lineage.i18n import tr as _


async def observe[R](
    what: str,
    body: Callable[[], Awaitable[R]],
) -> R | None:
    """
    Run *body*, returning ``None`` if it fails for any reason short of
    cancellation.

    Args:
        what: Short description of the step, used in the warning so a
            partial run directory can be explained after the fact.
        body: The recording work to attempt.

    Returns:
        Whatever *body* returned, or ``None`` when it raised.
    """
    try:
        return await body()
    except CancelledError:
        raise
    except Exception as error:
        horus_logger.log.warning(
            _("horus-lineage could not %(what)s: %(error)s")
            % {"what": what, "error": error}
        )
        return None
