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
The state one run shares between its four middlewares.

Middleware instances are constructed per context, so they cannot hold
shared state on ``self``. A context variable can: the workflow middleware
sets it before the chain runs, and every task the run creates inherits it,
because a new asyncio task copies the current context. Two workflows in
one process therefore keep separate sessions without coordinating.
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex

from horus_lineage.config import LineageConfig

_RUN_ID_BYTES = 8
"""Sixteen hex characters, unique by construction and never parsed."""


@dataclass
class LineageSession:
    """
    One run's identity, destination and shared scratch.
    """

    run: str
    """The minted run id (ADR 0006)."""

    directory: Path
    """This run's record directory, already created."""

    config: LineageConfig
    """Settings resolved once at run start."""

    definition_sha256: str
    """Digest of the projected definition every task record cites."""

    commands: dict[str, str] = field(default_factory=dict)
    """
    Resolved commands captured by the runtime middleware, by task id, for
    the task middleware to fold into its record.
    """

    recorded: set[str] = field(default_factory=set)
    """
    Task ids the task middleware already wrote, so the target middleware
    writes only the tasks it never saw (ADR 0007).
    """


_session: ContextVar[LineageSession | None] = ContextVar(
    "horus_lineage_session", default=None
)


def mint_run_id() -> str:
    """
    A fresh run id.
    """
    return token_hex(_RUN_ID_BYTES)


def current() -> LineageSession | None:
    """
    The session for the run in progress, or ``None`` outside one.

    Every hook tolerates ``None``. A task middleware can fire without a
    workflow middleware having run, for instance when a task is executed
    on its own rather than through a workflow.
    """
    return _session.get()


def begin(session: LineageSession) -> Token[LineageSession | None]:
    """
    Make *session* current, returning the token that undoes it.
    """
    return _session.set(session)


def end(token: Token[LineageSession | None]) -> None:
    """
    Restore whatever was current before the matching :func:`begin`.
    """
    _session.reset(token)
