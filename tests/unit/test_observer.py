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
Tests for the guard that makes ADR 0004 true.
"""

from asyncio import CancelledError

import pytest

from horus_lineage.observer import observe
from horus_lineage.session import (
    LineageSession,
    begin,
    current,
    end,
    mint_run_id,
)

MINTED = 1000
"""Enough ids that a weak generator would collide."""


class TestObserve:
    """
    A recorder failure must never reach the run.
    """

    async def test_it_returns_what_the_body_returned(self) -> None:
        """
        The happy path is transparent.
        """

        async def body() -> str:
            return "written"

        assert await observe("write a record", body) == "written"

    async def test_a_failure_is_swallowed(self) -> None:
        """
        Compute time is expensive and records are not worth a run.
        """

        async def body() -> str:
            raise RuntimeError("the target went away")

        assert await observe("write a record", body) is None

    async def test_cancellation_still_propagates(self) -> None:
        """
        Swallowing cancellation would outlive the run's teardown, which
        is a behaviour change rather than a recovery.
        """

        async def body() -> str:
            raise CancelledError

        with pytest.raises(CancelledError):
            await observe("write a record", body)


class TestSession:
    """
    The state one run shares between its middlewares.
    """

    def test_there_is_no_session_outside_a_run(self) -> None:
        """
        A task run on its own must not blow up the recorder.
        """
        assert current() is None

    def test_a_session_is_visible_until_it_ends(
        self, tmp_path: object
    ) -> None:
        """
        The workflow middleware publishes it, everything else reads it.
        """
        session = LineageSession(
            run=mint_run_id(),
            directory=tmp_path,  # type: ignore[arg-type]
            config=None,  # type: ignore[arg-type]
            definition_sha256="abc",
        )
        token = begin(session)
        try:
            assert current() is session
        finally:
            end(token)
        assert current() is None

    def test_run_ids_do_not_repeat(self) -> None:
        """
        The id namespaces task nodes, so a collision merges two runs.
        """
        assert len({mint_run_id() for _ in range(MINTED)}) == MINTED
